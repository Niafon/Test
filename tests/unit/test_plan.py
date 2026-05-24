from plan import classify_changes, is_type_change_safe, parse_type


def test_parse_type_handles_params():
    assert parse_type("VARCHAR(255)") == ("VARCHAR", [255])
    assert parse_type("NUMERIC(12, 2)") == ("NUMERIC", [12, 2])
    assert parse_type("integer") == ("INTEGER", [])


def test_is_type_change_safe_widening_int():
    # source шире/равен target -> расширение типа безопасно.
    assert is_type_change_safe("BIGINT", "INTEGER") is True
    assert is_type_change_safe("INTEGER", "SMALLINT") is True
    # Сужение -> небезопасно.
    assert is_type_change_safe("SMALLINT", "BIGINT") is False
    # Разные семейства -> небезопасно.
    assert is_type_change_safe("VARCHAR(50)", "INTEGER") is False


def test_is_type_change_safe_varchar_widening():
    assert is_type_change_safe("VARCHAR(255)", "VARCHAR(100)") is True
    assert is_type_change_safe("VARCHAR(50)", "VARCHAR(255)") is False


def test_classify_changes_buckets():
    changes = [
        {"kind": "missing_table", "table": "t", "schema": None},
        {"kind": "missing_column", "table": "t", "column": "c", "source_nullable": True, "source_default": None},
        {"kind": "missing_column", "table": "t", "column": "c2", "source_nullable": False, "source_default": None},
        {"kind": "missing_index", "table": "t", "source": {"unique": False}},
        {"kind": "missing_index", "table": "t", "source": {"unique": True}},
        {"kind": "different_column_type", "table": "t", "column": "c", "source": "BIGINT", "target": "INTEGER"},
        {"kind": "different_column_type", "table": "t", "column": "c", "source": "INTEGER", "target": "BIGINT"},
        {"kind": "different_primary_key", "table": "t", "source": ["id"], "target": ["id", "x"]},
        {"kind": "extra_table", "table": "t"},
        {"kind": "missing_foreign_key", "table": "t", "source": {}},
    ]
    plan = classify_changes(changes)
    assert {c["kind"] for c in plan["safe"]} == {
        "missing_table",
        "missing_column",  # nullable
        "missing_index",  # not unique
        "different_column_type",  # widening
    }
    assert "missing_column" in {c["kind"] for c in plan["risky"]}  # not null без default
    assert "missing_index" in {c["kind"] for c in plan["risky"]}  # unique index
    assert "missing_foreign_key" in {c["kind"] for c in plan["risky"]}
    assert {c["kind"] for c in plan["destructive"]} >= {"different_primary_key", "extra_table"}
    # Все changes получают description.
    assert all(c.get("description") for bucket in plan.values() for c in bucket)
