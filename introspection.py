from typing import List

from sqlalchemy import Engine, inspect
from sqlalchemy.engine.interfaces import ReflectedColumn, ReflectedForeignKeyConstraint, ReflectedPrimaryKeyConstraint


def get_tables(engine: Engine) -> list[str]:
    inspector = inspect(engine)
    return inspector.get_table_names()

def get_columns(engine: Engine, table_name: str) -> list[ReflectedColumn]:
    inspector = inspect(engine)
    columns_info: List[ReflectedColumn] = inspector.get_columns(table_name)

    return columns_info

def get_primary_keys(engine: Engine, table_name: str) -> ReflectedPrimaryKeyConstraint:
    inspector = inspect(engine)
    return inspector.get_pk_constraint(table_name)

def get_primary_keys_map(engine: Engine, tables_name: list[str]) -> dict[str, ReflectedPrimaryKeyConstraint]:
    result = {}

    for table in tables_name:
        result[table] = get_primary_keys(engine, table)

    return result

def get_foreign_keys(engine: Engine, table_name: str) -> List[ReflectedForeignKeyConstraint]:
    inspector = inspect(engine)
    return inspector.get_foreign_keys(table_name)
