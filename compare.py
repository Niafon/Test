from typing import Any

from sqlalchemy.engine.interfaces import (
    ReflectedCheckConstraint,
    ReflectedColumn,
    ReflectedForeignKeyConstraint,
    ReflectedIndex,
    ReflectedPrimaryKeyConstraint,
    ReflectedUniqueConstraint,
)

# Можно было бы разбить на несколько классов, но решил не плодить файли и все в одном сбацать
# Тут тольуо функции для сравнивания схемок + тип для описания изменений, которые мы нашли при сравнении
# Обычно чисто комонка и диффы

Change = dict[str, Any]
PrimaryKeyMap = dict[str, ReflectedPrimaryKeyConstraint]

# Ютилити для распарсивания диктов, листов, туплов, сетов в тупли, чтобы можно
# было сравнивать их по значению, а не по ссылке
def freeze_value(value: Any) -> Any:
    if isinstance(value, dict):
        return tuple(sorted((k, freeze_value(v)) for k, v in value.items()))
    if isinstance(value, list | tuple):
        return tuple(freeze_value(v) for v in value)
    if isinstance(value, set):
        return tuple(sorted(freeze_value(v) for v in value))
    return value

# Функции для сравнивания схемок и получения отчета об отличиях
def column_to_report(column: ReflectedColumn) -> Change:
# Превращаем колонку в дикт для удобного сравнения и генерации отчета
# Тут можно было бы еще добавить всяких атрибутов, но для примера хватит этих трех
    return {
        "name": column["name"],
        "type": str(column["type"]).upper(),
        "nullable": column["nullable"],
        "default": column.get("default"),
    }

# Превращаем первичный ключ в дикт для удобного сравнения и генерации отчета
def primary_key_to_report(pk: ReflectedPrimaryKeyConstraint) -> Change:

    return {
        "name": pk.get("name"),
        "constrained_columns": list(pk.get("constrained_columns") or []),
    }

# Ищем отличия в списках таблиц, возвращаем список отличий и список общих таблиц для дальнейшего сравнения
def get_diff_tables(
    source_table: list[str],
    target_table: list[str],
    target_schema: str | None = None,
) -> tuple[list[Change], list[str]]:

    source_tables = set(source_table)
    target_tables = set(target_table)

    diff_tables: list[Change] = []
    common_tables = []
    for x in source_tables:
        if x not in target_tables:
            diff_tables.append(
                {
                    "kind": "missing_table",
                    "table": x,
                    "schema": target_schema,
                }
            )
    for x in target_tables:
        if x not in source_tables:
            diff_tables.append(
                {
                    "kind": "extra_table",
                    "table": x,
                    "schema": target_schema,
                }
            )
    for x in source_tables:
        if x in target_tables:
            common_tables.append(x) # Тип данных для общих таблиц - просто строка с именем, так как для дальнейшего сравнения нам достаточно будет имени таблицы
    return diff_tables, common_tables

# Ищем отличия в списках колонок, возвращаем список отличий и список общих колонок для дальнейшего сравнения
def get_diff_columns(
    table_name: str,
    source_columns: list[ReflectedColumn],
    target_columns: list[ReflectedColumn],
    target_schema: str | None = None,
) -> tuple[list[Change], list[Change]]:

    source_columns_by_name = {column["name"]: column for column in source_columns}
    target_columns_by_name = {column["name"]: column for column in target_columns}

    source_columns_set = set(source_columns_by_name)
    target_columns_set = set(target_columns_by_name)

    diff_columns: list[Change] = []
    common_column_details: list[Change] = []
    for x in sorted(source_columns_set - target_columns_set):
        source_column = source_columns_by_name[x]
        # Тут так много из-за того, что я хочу в отчете видеть не только имя колонки,
        #  но и ее тип, nullable, дефолтное значение, чтобы было понятно, что именно
        #  мы потеряли при отсутствии колонки в таргете
        diff_columns.append(
            {
                "kind": "missing_column",
                "table": table_name,
                "schema": target_schema,
                "column": x,
                "source_type": str(source_column["type"]).upper(),
                "source_nullable": source_column["nullable"],
                "source_default": source_column.get("default"),
            }
        )
    for x in sorted(target_columns_set - source_columns_set):
        target_column = target_columns_by_name[x]
        diff_columns.append(
            {
                "kind": "extra_column",
                "table": table_name,
                "schema": target_schema,
                "column": x,
                "target_type": str(target_column["type"]).upper(),
                "target_nullable": target_column["nullable"],
                "target_default": target_column.get("default"),
            }
        )
    for x in sorted(source_columns_set & target_columns_set):
        source_column = source_columns_by_name[x]
        target_column = target_columns_by_name[x]
        common_column_details.append(
            {
                "kind": "common",
                "table": table_name,
                "schema": target_schema,
                "column": x,
                "source_column": source_column,
                "target_column": target_column,
            }
        )
    return diff_columns, common_column_details

# Ищем отличия в атрибутах общих колонок, возвращаем список отличий
def get_diff_column_attrs(
    common_column_details: list[Change],
) -> list[Change]:

    attr_diffs: list[Change] = []

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
                    "schema": column.get("schema"),
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
                    "schema": column.get("schema"),
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
                    "schema": column.get("schema"),
                    "column": column["column"],
                    "source": source_default,
                    "target": target_default,
                }
            )

    return attr_diffs

# Ищем отличия в первичных ключах, возвращаем список отличий
def get_diff_primary_keys(
    source_pk: PrimaryKeyMap,
    target_pk: PrimaryKeyMap,
    target_schema: str | None = None,
) -> list[Change]:
    diffs: list[Change] = []
    common_tables = set(source_pk) & set(target_pk)
    for table in sorted(common_tables):
        source_pk_columns = sorted(source_pk[table].get("constrained_columns") or [])
        target_pk_columns = sorted(target_pk[table].get("constrained_columns") or [])

        if source_pk_columns != target_pk_columns:
            diffs.append(
                {
                    "kind": "different_primary_key",
                    "table": table,
                    "schema": target_schema,
                    "source_name": source_pk[table].get("name"),
                    "target_name": target_pk[table].get("name"),
                    "source": sorted(source_pk_columns),
                    "target": sorted(target_pk_columns),
                }
            )

    return diffs

# Тут кароче мы нормализуем атрибуты тк они по разному могу бывть в бд
def _portable_referred_schema(
    fk: ReflectedForeignKeyConstraint, owner_schema: str | None
) -> str | None:
    # FK на свою же схему -> referred_schema=None, иначе при разных именах
    # схем в source и target same-schema FK ошибочно классифицируется как
    # разный, и при apply SQL ссылается на source-имя схемы.
    referred_schema = fk.get("referred_schema")
    if referred_schema == owner_schema:
        return None
    return referred_schema


def normalize_foreign_key(
    fk: ReflectedForeignKeyConstraint, owner_schema: str | None = None
) -> tuple[Any, ...]:
    return (
        tuple(fk.get("constrained_columns") or []),
        _portable_referred_schema(fk, owner_schema),
        fk.get("referred_table"),
        tuple(fk.get("referred_columns") or []),
        freeze_value(fk.get("options") or {}),
    )

# Превращаем внешний ключ в дикт для удобного сравнения и генерации отчета
def foreign_key_to_report(
    fk: ReflectedForeignKeyConstraint, owner_schema: str | None = None
) -> Change:
    return {
        "name": fk.get("name"),
        "constrained_columns": list(fk.get("constrained_columns") or []),
        "referred_schema": _portable_referred_schema(fk, owner_schema),
        "referred_table": fk.get("referred_table"),
        "referred_columns": list(fk.get("referred_columns") or []),
        "options": dict(fk.get("options") or {}),
    }

# Ищем отличия в списках внешних ключей, возвращаем список отличий
def get_diff_foreign_keys(
    source_fk: dict[str, list[ReflectedForeignKeyConstraint]],
    target_fk: dict[str, list[ReflectedForeignKeyConstraint]],
    target_schema: str | None = None,
    source_schema: str | None = None,
) -> list[Change]:
    diffs: list[Change] = []

    common_tables = set(source_fk) & set(target_fk)

    for table_name in sorted(common_tables):
        source_fk_by_key = {
            normalize_foreign_key(fk, owner_schema=source_schema): fk
            for fk in source_fk[table_name]
        }
        target_fk_by_key = {
            normalize_foreign_key(fk, owner_schema=target_schema): fk
            for fk in target_fk[table_name]
        }

        source_keys = set(source_fk_by_key)
        target_keys = set(target_fk_by_key)

        for key in sorted(source_keys - target_keys):
            diffs.append(
                {
                    "kind": "missing_foreign_key",
                    "table": table_name,
                    "schema": target_schema,
                    "source": foreign_key_to_report(
                        source_fk_by_key[key], owner_schema=source_schema
                    ),
                }
            )

        for key in sorted(target_keys - source_keys):
            diffs.append(
                {
                    "kind": "extra_foreign_key",
                    "table": table_name,
                    "schema": target_schema,
                    "target": foreign_key_to_report(
                        target_fk_by_key[key], owner_schema=target_schema
                    ),
                }
            )

    return diffs

# Нормализуем
def normalize_unique_constraint(unique: ReflectedUniqueConstraint) -> tuple[str, ...]:

    return tuple(unique.get("column_names") or [])

# в репорт кидаем
def unique_constraint_to_report(unique: ReflectedUniqueConstraint) -> Change:

    return {
        "name": unique.get("name"),
        "columns": list(unique.get("column_names") or []),
    }

# Ищем отличия в списках уникальных ключей, возвращаем список отличий
def get_diff_unique_constraints(
    source_uniques: dict[str, list[ReflectedUniqueConstraint]],
    target_uniques: dict[str, list[ReflectedUniqueConstraint]],
    target_schema: str | None = None,
) -> list[Change]:
    diffs: list[Change] = []

    common_tables = set(source_uniques) & set(target_uniques)

    for table_name in sorted(common_tables):
        source_unique_by_key = {
            normalize_unique_constraint(u): u for u in source_uniques[table_name]
        }
        target_unique_by_key = {
            normalize_unique_constraint(u): u for u in target_uniques[table_name]
        }

        source_keys = set(source_unique_by_key)
        target_keys = set(target_unique_by_key)

        for key in sorted(source_keys - target_keys):
            diffs.append(
                {
                    "kind": "missing_unique_constraint",
                    "table": table_name,
                    "schema": target_schema,
                    "source": unique_constraint_to_report(source_unique_by_key[key]),
                }
            )

        for key in sorted(target_keys - source_keys):
            diffs.append(
                {
                    "kind": "extra_unique_constraint",
                    "table": table_name,
                    "schema": target_schema,
                    "target": unique_constraint_to_report(target_unique_by_key[key]),
                }
            )

    return diffs

# Нормализуем индекс для сравнения
def normalize_index(index: ReflectedIndex) -> tuple[Any, ...]:

    return (
        tuple(index.get("column_names") or []),
        bool(index.get("unique") or False),
        freeze_value(index.get("dialect_options") or {}),
    )

# Превращаем индекс в дикт для удобного сравнения и генерации отчета
def index_to_report(index: ReflectedIndex) -> Change:

    return {
        "name": index.get("name"),
        "columns": list(index.get("column_names") or []),
        "unique": bool(index.get("unique") or False),
        "dialect_options": dict(index.get("dialect_options") or {}),
    }

# Ищем отличия в списках индексов, возвращаем список отличий
def get_diff_indexes(
    source_indexes: dict[str, list[ReflectedIndex]],
    target_indexes: dict[str, list[ReflectedIndex]],
    target_schema: str | None = None,
) -> list[Change]:
    diffs: list[Change] = []

    common_tables = set(source_indexes) & set(target_indexes)

    for table_name in sorted(common_tables):
        source_index_by_key = {
            normalize_index(i): i for i in source_indexes[table_name]
        }
        target_index_by_key = {
            normalize_index(i): i for i in target_indexes[table_name]
        }

        source_keys = set(source_index_by_key)
        target_keys = set(target_index_by_key)

        for key in sorted(source_keys - target_keys):
            diffs.append(
                {
                    "kind": "missing_index",
                    "table": table_name,
                    "schema": target_schema,
                    "source": index_to_report(source_index_by_key[key]),
                }
            )

        for key in sorted(target_keys - source_keys):
            diffs.append(
                {
                    "kind": "extra_index",
                    "table": table_name,
                    "schema": target_schema,
                    "target": index_to_report(target_index_by_key[key]),
                }
            )

    return diffs


def normalize_check_constraint(check: ReflectedCheckConstraint) -> str:

    return (check.get("sqltext") or "").strip()


def check_constraint_to_report(check: ReflectedCheckConstraint) -> Change:

    return {
        "name": check.get("name"),
        "sqltext": check.get("sqltext"),
    }

# Чекаем чеки на отличия, возвращаем список отличий
def get_diff_check_constraints(
    source_checks: dict[str, list[ReflectedCheckConstraint]],
    target_checks: dict[str, list[ReflectedCheckConstraint]],
    target_schema: str | None = None,
) -> list[Change]:
    diffs: list[Change] = []

    common_tables = set(source_checks) & set(target_checks)

    for table_name in sorted(common_tables):
        source_check_by_key = {
            normalize_check_constraint(c): c for c in source_checks[table_name]
        }
        target_check_by_key = {
            normalize_check_constraint(c): c for c in target_checks[table_name]
        }

        source_keys = set(source_check_by_key)
        target_keys = set(target_check_by_key)

        for key in sorted(source_keys - target_keys):
            diffs.append(
                {
                    "kind": "missing_check_constraint",
                    "table": table_name,
                    "schema": target_schema,
                    "source": check_constraint_to_report(source_check_by_key[key]),
                }
            )

        for key in sorted(target_keys - source_keys):
            diffs.append(
                {
                    "kind": "extra_check_constraint",
                    "table": table_name,
                    "schema": target_schema,
                    "target": check_constraint_to_report(target_check_by_key[key]),
                }
            )

    return diffs


# Итого - тут для сравнивания схемы функции
