from typing import Any

from sqlalchemy.engine.interfaces import ReflectedColumn


def get_diff_tables(
    source_table: list[str], target_table: list[str]
) -> tuple[list[dict[str, str]], list[str]]:
    source_tables = set(source_table)
    target_tables = set(target_table)

    diff_tables = []
    common_tables = []
    for x in source_tables:
        if x not in target_tables:
            diff_tables.append(
                {
                    "kind": "missing_table",
                    "table": x,
                }
            )
    for x in target_tables:
        if x not in source_tables:
            diff_tables.append(
                {
                    "kind": "extra_table",
                    "table": x,
                }
            )
    for x in source_tables:
        if x in target_tables:
            common_tables.append(x)
    return diff_tables, common_tables


def get_diff_columns(
    table_name: str,
    source_columns: list[ReflectedColumn],
    target_columns: list[ReflectedColumn],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    source_columns_by_name = {column["name"]: column for column in source_columns}
    target_columns_by_name = {column["name"]: column for column in target_columns}

    source_columns_set = set(source_columns_by_name)
    target_columns_set = set(target_columns_by_name)

    diff_columns = []
    common_column_details = []
    for x in sorted(source_columns_set - target_columns_set):
        diff_columns.append(
            {
                "kind": "missing_column",
                "table": table_name,
                "column": x,
            }
        )
    for x in sorted(target_columns_set - source_columns_set):
        diff_columns.append(
            {
                "kind": "extra_column",
                "table": table_name,
                "column": x,
            }
        )
    for x in sorted(source_columns_set & target_columns_set):
        source_column = source_columns_by_name[x]
        target_column = target_columns_by_name[x]
        common_column_details.append(
            {
                "kind": "common",
                "table": table_name,
                "column": x,
                "source_column": source_column,
                "target_column": target_column,
            }
        )
    return diff_columns, common_column_details


def get_diff_column_attrs(
    common_column_details: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    attr_diffs = []

    for column in common_column_details:
        source_column = column["source_column"]
        target_column = column["target_column"]

        source_type = str(source_column["type"]).upper()
        target_type = str(target_column["type"]).upper()
        if source_type != target_type:
            attr_diffs.append(
                {
                    "kind": "different_column_type",
                    "table": column["table"],
                    "column": column["column"],
                    "source": source_type,
                    "target": target_type,
                }
            )

        source_nullable = source_column["nullable"]
        target_nullable = target_column["nullable"]
        if source_nullable != target_nullable:
            attr_diffs.append(
                {
                    "kind": "different_column_nullable",
                    "table": column["table"],
                    "column": column["column"],
                    "source": source_nullable,
                    "target": target_nullable,
                }
            )

        source_default = source_column.get("default")
        target_default = target_column.get("default")
        if source_default != target_default:
            attr_diffs.append(
                {
                    "kind": "different_column_default",
                    "table": column["table"],
                    "column": column["column"],
                    "source": source_default,
                    "target": target_default,
                }
            )

    return attr_diffs


def get_diff_primary_keys(
    source_pk, # Тип данных тут: Название таблицы и список полей, входящих в первичный ключ
    target_pk,
):
    diffs = []

    common_tables = set(source_pk) & set(target_pk) # Находим общие таблицы с вот таким примером {"table": "users", "constrained_columns": ["id"]}
    for table in sorted(common_tables):
        source_pk_columns = source_pk[table].get("constrained_columns") or []
        target_pk_columns = target_pk[table].get("constrained_columns") or []

        if source_pk_columns != target_pk_columns:
            diffs.append(
                {
                    "kind": "different_primary_key",
                    "table": table,
                    "source": sorted(source_pk_columns),
                    "target": sorted(target_pk_columns),
                }
            )
