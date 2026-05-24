"""Unit-тесты сравнения схем. Здесь мокаем только сами входные данные:
compare.py получает уже распарсенные SQLAlchemy-структуры, поэтому достаточно
передавать список dict-ов в форме reflection-результатов.
"""
from compare import (
    freeze_value,
    get_diff_check_constraints,
    get_diff_column_attrs,
    get_diff_columns,
    get_diff_foreign_keys,
    get_diff_indexes,
    get_diff_primary_keys,
    get_diff_tables,
    get_diff_unique_constraints,
)


def test_freeze_value_makes_dicts_hashable():
    a = {"x": 1, "y": [1, 2, {"z": 3}]}
    b = {"y": [1, 2, {"z": 3}], "x": 1}
    assert freeze_value(a) == freeze_value(b)
    assert hash(freeze_value(a)) == hash(freeze_value(b))


def test_get_diff_tables_classifies_missing_and_extra():
    diffs, common = get_diff_tables(
        ["users", "orders", "products"],
        ["users", "orders", "legacy"],
        target_schema="public",
    )
    kinds = {(c["kind"], c["table"]) for c in diffs}
    assert ("missing_table", "products") in kinds
    assert ("extra_table", "legacy") in kinds
    assert set(common) == {"users", "orders"}
    assert all(c["schema"] == "public" for c in diffs)


def test_get_diff_columns_reports_missing_extra_common():
    source = [
        {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
        {"name": "email", "type": "VARCHAR(255)", "nullable": True, "default": None},
    ]
    target = [
        {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
        {"name": "full_name", "type": "VARCHAR(255)", "nullable": True, "default": None},
    ]
    diffs, common = get_diff_columns("users", source, target, target_schema="public")
    kinds = {c["kind"] for c in diffs}
    assert kinds == {"missing_column", "extra_column"}
    missing = next(c for c in diffs if c["kind"] == "missing_column")
    assert missing["column"] == "email"
    assert missing["source_type"] == "VARCHAR(255)"
    extra = next(c for c in diffs if c["kind"] == "extra_column")
    assert extra["column"] == "full_name"
    assert len(common) == 1 and common[0]["column"] == "id"


def test_get_diff_column_attrs_catches_type_nullable_default():
    common = [
        {
            "kind": "common",
            "table": "users",
            "schema": None,
            "column": "age",
            "source_column": {
                "name": "age",
                "type": "BIGINT",
                "nullable": False,
                "default": "0",
            },
            "target_column": {
                "name": "age",
                "type": "INTEGER",
                "nullable": True,
                "default": None,
            },
        }
    ]
    diffs = get_diff_column_attrs(common)
    kinds = {d["kind"] for d in diffs}
    assert kinds == {
        "different_column_type",
        "different_column_nullable",
        "different_column_default",
    }


def test_get_diff_primary_keys():
    source = {"users": {"name": "users_pkey", "constrained_columns": ["id"]}}
    target = {"users": {"name": "users_pkey", "constrained_columns": ["id", "tenant_id"]}}
    diffs = get_diff_primary_keys(source, target)
    assert len(diffs) == 1
    assert diffs[0]["kind"] == "different_primary_key"
    assert diffs[0]["source"] == ["id"]
    assert diffs[0]["target"] == ["id", "tenant_id"]


def test_get_diff_foreign_keys_detects_missing():
    source = {
        "orders": [
            {
                "name": "fk_orders_user_id",
                "constrained_columns": ["user_id"],
                "referred_schema": None,
                "referred_table": "users",
                "referred_columns": ["id"],
                "options": {},
            }
        ]
    }
    target = {"orders": []}
    diffs = get_diff_foreign_keys(source, target)
    assert len(diffs) == 1
    assert diffs[0]["kind"] == "missing_foreign_key"
    assert diffs[0]["source"]["name"] == "fk_orders_user_id"


def test_get_diff_unique_and_indexes_and_checks():
    diff_u = get_diff_unique_constraints(
        {"u": [{"name": "uq_a", "column_names": ["a"]}]},
        {"u": []},
    )
    diff_i = get_diff_indexes(
        {"u": [{"name": "idx", "column_names": ["a"], "unique": False, "dialect_options": {}}]},
        {"u": []},
    )
    diff_c = get_diff_check_constraints(
        {"u": [{"name": "ck", "sqltext": "a > 0"}]},
        {"u": []},
    )
    assert diff_u[0]["kind"] == "missing_unique_constraint"
    assert diff_i[0]["kind"] == "missing_index"
    assert diff_c[0]["kind"] == "missing_check_constraint"
