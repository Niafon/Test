from sqlalchemy import Engine, inspect
from sqlalchemy.engine.interfaces import (
    ReflectedCheckConstraint,
    ReflectedColumn,
    ReflectedForeignKeyConstraint,
    ReflectedIndex,
    ReflectedPrimaryKeyConstraint,
    ReflectedUniqueConstraint,
)


def get_tables(engine: Engine, schema: str | None = None) -> list[str]:
    inspector = inspect(engine)
    return inspector.get_table_names(schema=schema)


def get_columns(
    engine: Engine, table_name: str, schema: str | None = None
) -> list[ReflectedColumn]:
    inspector = inspect(engine)
    return inspector.get_columns(table_name, schema=schema)


def get_primary_keys(
    engine: Engine, table_name: str, schema: str | None = None
) -> ReflectedPrimaryKeyConstraint:
    inspector = inspect(engine)
    return inspector.get_pk_constraint(table_name, schema=schema)


def get_primary_keys_map(
    engine: Engine, tables_name: list[str], schema: str | None = None
) -> dict[str, ReflectedPrimaryKeyConstraint]:
    result: dict[str, ReflectedPrimaryKeyConstraint] = {}

    for table in tables_name:
        result[table] = get_primary_keys(engine, table, schema=schema)

    return result


def get_foreign_keys(
    engine: Engine, table_name: str, schema: str | None = None
) -> list[ReflectedForeignKeyConstraint]:
    inspector = inspect(engine)
    return inspector.get_foreign_keys(table_name, schema=schema)


def get_foreign_keys_map(
    engine: Engine, tables_name: list[str], schema: str | None = None
) -> dict[str, list[ReflectedForeignKeyConstraint]]:
    result: dict[str, list[ReflectedForeignKeyConstraint]] = {}

    for table in tables_name:
        result[table] = get_foreign_keys(engine, table, schema=schema)

    return result


def get_unique_constraints(
    engine: Engine,
    table_name: str,
    schema: str | None = None,
) -> list[ReflectedUniqueConstraint]:
    inspector = inspect(engine)
    return inspector.get_unique_constraints(table_name, schema=schema)


def get_unique_constraints_map(
    engine: Engine,
    table_names: list[str],
    schema: str | None = None,
) -> dict[str, list[ReflectedUniqueConstraint]]:
    result: dict[str, list[ReflectedUniqueConstraint]] = {}

    for table_name in table_names:
        result[table_name] = get_unique_constraints(engine, table_name, schema=schema)

    return result


def get_indexes(
    engine: Engine,
    table_name: str,
    schema: str | None = None,
) -> list[ReflectedIndex]:
    inspector = inspect(engine)
    return inspector.get_indexes(table_name, schema=schema)


def get_indexes_map(
    engine: Engine,
    table_names: list[str],
    schema: str | None = None,
) -> dict[str, list[ReflectedIndex]]:
    result: dict[str, list[ReflectedIndex]] = {}

    for table_name in table_names:
        result[table_name] = get_indexes(engine, table_name, schema=schema)

    return result


def get_check_constraints(
    engine: Engine,
    table_name: str,
    schema: str | None = None,
) -> list[ReflectedCheckConstraint]:
    inspector = inspect(engine)
    return inspector.get_check_constraints(table_name, schema=schema)


def get_check_constraints_map(
    engine: Engine,
    table_names: list[str],
    schema: str | None = None,
) -> dict[str, list[ReflectedCheckConstraint]]:
    result: dict[str, list[ReflectedCheckConstraint]] = {}

    for table_name in table_names:
        result[table_name] = get_check_constraints(engine, table_name, schema=schema)

    return result
