import sys

import pytest

from sql_generator import (
    format_default,
    generate_add_column_sql,
    generate_add_foreign_key_sql,
    generate_alter_column_default_sql,
    generate_alter_column_type_sql,
    generate_create_table_fk_sql,
    generate_create_table_sql,
    generate_sql,
)


def test_format_default_passes_through_sql_expressions():
    assert format_default("nextval('users_id_seq'::regclass)") == "nextval('users_id_seq'::regclass)"
    assert format_default("'hello'::text") == "'hello'::text"
    assert format_default("CURRENT_TIMESTAMP") == "CURRENT_TIMESTAMP"
    assert format_default("NOW()") == "NOW()"


def test_format_default_quotes_bare_string_literal():
    assert format_default("hello") == "'hello'"
    assert format_default("o'reilly") == "'o''reilly'"


def test_format_default_handles_numbers_and_booleans():
    assert format_default(42) == "42"
    assert format_default(3.14) == "3.14"
    assert format_default(True) == "TRUE"
    assert format_default(False) == "FALSE"
    assert format_default(None) == "NULL"


def test_format_default_passes_through_numeric_strings():
    assert format_default("0") == "0"
    assert format_default("-1.5") == "-1.5"


def test_add_column_quotes_string_default():
    change = {
        "table": "users",
        "schema": None,
        "column": "status",
        "source_type": "VARCHAR(32)",
        "source_nullable": False,
        "source_default": "active",
    }
    sql = generate_add_column_sql(change)
    assert sql == [
        'ALTER TABLE "users" ADD COLUMN "status" VARCHAR(32) NOT NULL DEFAULT \'active\';'
    ]


def test_alter_column_type_emits_using_clause():
    change = {
        "table": "orders",
        "schema": "public",
        "column": "total",
        "source": "NUMERIC(12,2)",
        "target": "INTEGER",
    }
    sql = generate_alter_column_type_sql(change)
    assert sql == [
        'ALTER TABLE "public"."orders" ALTER COLUMN "total" TYPE NUMERIC(12,2) '
        'USING "total"::NUMERIC(12,2);'
    ]


def test_alter_column_default_quotes_string_value():
    change = {
        "table": "users",
        "schema": None,
        "column": "role",
        "source": "guest",
    }
    sql = generate_alter_column_default_sql(change)
    assert sql == ['ALTER TABLE "users" ALTER COLUMN "role" SET DEFAULT \'guest\';']


def test_create_table_does_not_inline_foreign_keys():
    change = {
        "kind": "missing_table",
        "table": "orders",
        "schema": None,
        "source": {
            "columns": [
                {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                {"name": "user_id", "type": "INTEGER", "nullable": False, "default": None},
            ],
            "primary_key": {"name": "orders_pkey", "constrained_columns": ["id"]},
            "foreign_keys": [
                {
                    "name": "orders_user_id_fk",
                    "constrained_columns": ["user_id"],
                    "referred_schema": None,
                    "referred_table": "users",
                    "referred_columns": ["id"],
                    "options": {},
                }
            ],
            "unique_constraints": [],
            "check_constraints": [],
            "indexes": [],
        },
    }
    create_sql = "\n".join(generate_create_table_sql(change))
    assert "FOREIGN KEY" not in create_sql
    assert "REFERENCES" not in create_sql

    fk_sql = generate_create_table_fk_sql(change)
    assert fk_sql == [
        'ALTER TABLE "orders" ADD CONSTRAINT "orders_user_id_fk" '
        'FOREIGN KEY ("user_id") REFERENCES "users" ("id");'
    ]


def test_generate_sql_emits_cyclic_fks_after_all_create_table():
    # A.b_id -> B, B.a_id -> A — классический цикл, ломающий inline FK.
    changes = [
        {
            "kind": "missing_table",
            "table": "a",
            "schema": None,
            "source": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                    {"name": "b_id", "type": "INTEGER", "nullable": True, "default": None},
                ],
                "primary_key": {"name": "a_pkey", "constrained_columns": ["id"]},
                "foreign_keys": [
                    {
                        "name": "a_b_id_fk",
                        "constrained_columns": ["b_id"],
                        "referred_schema": None,
                        "referred_table": "b",
                        "referred_columns": ["id"],
                        "options": {},
                    }
                ],
                "unique_constraints": [],
                "check_constraints": [],
                "indexes": [],
            },
        },
        {
            "kind": "missing_table",
            "table": "b",
            "schema": None,
            "source": {
                "columns": [
                    {"name": "id", "type": "INTEGER", "nullable": False, "default": None},
                    {"name": "a_id", "type": "INTEGER", "nullable": True, "default": None},
                ],
                "primary_key": {"name": "b_pkey", "constrained_columns": ["id"]},
                "foreign_keys": [
                    {
                        "name": "b_a_id_fk",
                        "constrained_columns": ["a_id"],
                        "referred_schema": None,
                        "referred_table": "a",
                        "referred_columns": ["id"],
                        "options": {},
                    }
                ],
                "unique_constraints": [],
                "check_constraints": [],
                "indexes": [],
            },
        },
    ]
    sql = generate_sql(changes, mode="safe")
    create_a = sql.index('CREATE TABLE "a"')
    create_b = sql.index('CREATE TABLE "b"')
    fk_a = sql.index('ADD CONSTRAINT "a_b_id_fk"')
    fk_b = sql.index('ADD CONSTRAINT "b_a_id_fk"')
    # Оба CREATE TABLE идут раньше любого ALTER TABLE с FK.
    assert max(create_a, create_b) < min(fk_a, fk_b)


def test_foreign_key_options_are_copied_for_existing_table():
    change = {
        "kind": "missing_foreign_key",
        "table": "orders",
        "schema": None,
        "source": {
            "name": "orders_user_id_fk",
            "constrained_columns": ["user_id"],
            "referred_schema": None,
            "referred_table": "users",
            "referred_columns": ["id"],
            "options": {
                "ondelete": "CASCADE",
                "onupdate": "SET NULL",
                "deferrable": True,
                "initially": "DEFERRED",
            },
        },
    }
    assert generate_add_foreign_key_sql(change) == [
        'ALTER TABLE "orders" ADD CONSTRAINT "orders_user_id_fk" '
        'FOREIGN KEY ("user_id") REFERENCES "users" ("id") '
        "ON DELETE CASCADE ON UPDATE SET NULL DEFERRABLE INITIALLY DEFERRED NOT VALID;"
    ]


def test_foreign_key_options_are_copied_for_new_table_deferred_fk():
    change = {
        "kind": "missing_table",
        "table": "orders",
        "schema": None,
        "source": {
            "foreign_keys": [
                {
                    "name": "orders_user_id_fk",
                    "constrained_columns": ["user_id"],
                    "referred_schema": None,
                    "referred_table": "users",
                    "referred_columns": ["id"],
                    "options": {
                        "match": "FULL",
                        "ondelete": "SET DEFAULT",
                        "deferrable": False,
                    },
                }
            ],
        },
    }
    assert generate_create_table_fk_sql(change) == [
        'ALTER TABLE "orders" ADD CONSTRAINT "orders_user_id_fk" '
        'FOREIGN KEY ("user_id") REFERENCES "users" ("id") '
        "MATCH FULL ON DELETE SET DEFAULT NOT DEFERRABLE;"
    ]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
