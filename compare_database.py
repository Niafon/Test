from typing import Any

from sqlalchemy.engine import Engine

from compare import (
    check_constraint_to_report,
    column_to_report,
    foreign_key_to_report,
    get_diff_check_constraints,
    get_diff_column_attrs,
    get_diff_columns,
    get_diff_foreign_keys,
    get_diff_indexes,
    get_diff_primary_keys,
    get_diff_tables,
    get_diff_unique_constraints,
    index_to_report,
    primary_key_to_report,
    unique_constraint_to_report,
)
from introspection import (
    get_check_constraints,
    get_check_constraints_map,
    get_columns,
    get_foreign_keys,
    get_foreign_keys_map,
    get_indexes,
    get_indexes_map,
    get_primary_keys,
    get_primary_keys_map,
    get_tables,
    get_unique_constraints,
    get_unique_constraints_map,
)

# Изменения в структуре бд, которые мы будем собирать и возвращать в виде отчета
Change = dict[str, Any]


# Собираем полное описание таблицы для отчета
def collect_table_definition(
    engine: Engine, table_name: str, schema: str | None = None
) -> Change:
    return {
        "columns": [
            column_to_report(c) for c in get_columns(engine, table_name, schema=schema)
        ],
        "primary_key": primary_key_to_report(
            get_primary_keys(engine, table_name, schema=schema)
        ),
        "foreign_keys": [
            # owner_schema=schema: same-schema FK обнуляют referred_schema,
            # чтобы при переносе на target SQL не ссылался на source-имя.
            foreign_key_to_report(fk, owner_schema=schema)
            for fk in get_foreign_keys(engine, table_name, schema=schema)
        ],
        "unique_constraints": [
            unique_constraint_to_report(u)
            for u in get_unique_constraints(engine, table_name, schema=schema)
        ],
        "check_constraints": [
            check_constraint_to_report(c)
            for c in get_check_constraints(engine, table_name, schema=schema)
        ],
        "indexes": [
            index_to_report(i) for i in get_indexes(engine, table_name, schema=schema)
        ],
    }
# Само ссравнение бд
def compare_databases(
    source_db: Engine, 
    target_db: Engine,
    source_schema: str | None = None,
    target_schema: str | None = None,
) -> list[Change]:
    changes: list[Change] = []
    source_tables = get_tables(source_db, schema=source_schema)
    target_tables = get_tables(target_db, schema=target_schema)
    diff_tables, common_tables_details = get_diff_tables(
        source_tables, target_tables, target_schema=target_schema
    )
    for change in diff_tables:
        if change["kind"] == "missing_table":
            change["source"] = collect_table_definition(
                source_db, change["table"], schema=source_schema
            )
        elif change["kind"] == "extra_table":
            # Симметрично missing_table: для лишней в target таблицы собираем
            # полное описание, чтобы DROP TABLE мог отчитаться, что именно
            # удаляется, а диагностика - сколько строк и FK потеряется.
            change["target"] = collect_table_definition(
                target_db, change["table"], schema=target_schema
            )

    changes.extend(diff_tables)
    primary_keys_map_source = get_primary_keys_map(
        source_db, common_tables_details, schema=source_schema
    )
    primary_keys_map_target = get_primary_keys_map(
        target_db, common_tables_details, schema=target_schema
    )

    column_diffs_pk = get_diff_primary_keys(
        primary_keys_map_source, primary_keys_map_target, target_schema=target_schema
    )

    changes.extend(column_diffs_pk)
    foreign_keys_map_source = get_foreign_keys_map(
        source_db, common_tables_details, schema=source_schema
    )
    foreign_keys_map_target = get_foreign_keys_map(
        target_db, common_tables_details, schema=target_schema
    )

    column_diffs_fk = get_diff_foreign_keys(
        foreign_keys_map_source,
        foreign_keys_map_target,
        target_schema=target_schema,
        source_schema=source_schema,
    )
    changes.extend(column_diffs_fk)
    unique_constraints_map_source = get_unique_constraints_map(
        source_db, common_tables_details, schema=source_schema
    )
    unique_constraints_map_target = get_unique_constraints_map(
        target_db, common_tables_details, schema=target_schema
    )

    column_diffs_unique = get_diff_unique_constraints(
        unique_constraints_map_source,
        unique_constraints_map_target,
        target_schema=target_schema,
    )

    changes.extend(column_diffs_unique)

    source_indexes = get_indexes_map(
        source_db, common_tables_details, schema=source_schema
    )
    target_indexes = get_indexes_map(
        target_db, common_tables_details, schema=target_schema
    )

    changes.extend(
        get_diff_indexes(source_indexes, target_indexes, target_schema=target_schema)
    )
    source_checks = get_check_constraints_map(
        source_db, common_tables_details, schema=source_schema
    )
    target_checks = get_check_constraints_map(
        target_db, common_tables_details, schema=target_schema
    )

    changes.extend(
        get_diff_check_constraints(
            source_checks, target_checks, target_schema=target_schema
        )
    )
    for table in common_tables_details:
        source_columns = get_columns(source_db, table, schema=source_schema)
        target_columns = get_columns(target_db, table, schema=target_schema)
        diff_columns, common_column_details = get_diff_columns(
            table, source_columns, target_columns, target_schema=target_schema
        )

        changes.extend(diff_columns)
        column_attr_diffs = get_diff_column_attrs(common_column_details)

        changes.extend(column_attr_diffs)
    return changes
