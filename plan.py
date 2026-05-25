"""Классификация diff'а по уровням риска и человекочитаемые описания.

Каждое изменение из compare.* попадает в одну из корзин:
- safe         - аддитивные операции, данных не теряем
- risky        - может упасть на существующих данных
- destructive  - явно теряет данные

Дополнительно к каждому change прикручивается description -
короткая фраза, которую видно в /generate ответе и в meta-файле.
"""
import re
from typing import Any

Change = dict[str, Any]

_TYPE_PATTERN = re.compile(
    r"^(?P<base>[A-Z][A-Z0-9_]*(?:\s+[A-Z][A-Z0-9_]*)*?)"
    r"(?:\s*\((?P<p1>\d+)(?:\s*,\s*(?P<p2>\d+))?\))?\s*$"
)


_INTEGER_SIZES = {
    "TINYINT": 1,
    "SMALLINT": 2,
    "MEDIUMINT": 3,
    "INT": 4,
    "INTEGER": 4,
    "BIGINT": 8,
}


def parse_type(type_string: str) -> tuple[str, list[int]]:
    """Разобрать SQL-тип на базу и параметры (VARCHAR(50) -> ("VARCHAR", [50]))."""
    match = _TYPE_PATTERN.match((type_string or "").strip().upper())
    if not match:
        return (type_string or "").strip().upper(), []
    base = match.group("base").strip()
    params = [int(p) for p in (match.group("p1"), match.group("p2")) if p is not None]
    return base, params


def is_type_change_safe(source_type: str, target_type: str) -> bool:
    """Безопасно ли менять тип target -> source без риска потери данных.

    Расширение размера строки (VARCHAR(50) -> VARCHAR(255)) и расширение
    int (SMALLINT -> BIGINT) безопасны. Сужение и смена базы между
    несовместимыми типами - нет.
    """
    source_base, source_params = parse_type(source_type)
    target_base, target_params = parse_type(target_type)
    if source_base == target_base:
        if not source_params and not target_params:
            return True
        if len(source_params) == len(target_params):
            return all(s >= t for s, t in zip(source_params, target_params))
        return False

    if source_base in _INTEGER_SIZES and target_base in _INTEGER_SIZES:
        return _INTEGER_SIZES[source_base] >= _INTEGER_SIZES[target_base]

    return False


def _table_label(change: Change) -> str:
    """Собрать читаемое имя таблицы для сообщения ("schema.table" или "table")."""
    schema = change.get("schema")
    table = change.get("table")
    return f"{schema}.{table}" if schema else str(table)


def describe_change(change: Change) -> str:
    """Сформировать человекочитаемое описание изменения.

    Идёт в поле description каждого change. Текст рассчитан на то,
    что его прочитает человек, который решает, применять SQL или нет.
    """
    kind = change["kind"]
    table = _table_label(change)

    if kind == "missing_table":
        return (
            f"Таблица '{table}' есть в эталоне, но отсутствует в целевой БД. "
            "Ее нужно создать."
        )

    if kind == "extra_table":
        return (
            f"Таблица '{table}' есть в целевой БД, но отсутствует в эталоне. "
            "При удалении будут потеряны данные."
        )

    if kind == "missing_column":
        column = change.get("column")
        nullable = change.get("source_nullable")
        default = change.get("source_default")
        col_type = change.get("source_type")
        if nullable:
            return (
                f"Колонка '{table}.{column}' ({col_type}, NULL) есть в эталоне, "
                "но отсутствует в целевой БД. Добавление безопасно."
            )
        if default is not None:
            return (
                f"Колонка '{table}.{column}' ({col_type}, NOT NULL DEFAULT "
                f"{default!r}) отсутствует в целевой БД. Существующие строки "
                "получат default."
            )
        return (
            f"Колонка '{table}.{column}' ({col_type}, NOT NULL без default) "
            "отсутствует в целевой БД. На непустой таблице нужен backfill."
        )

    if kind == "extra_column":
        column = change.get("column")
        col_type = change.get("target_type")
        return (
            f"Колонка '{table}.{column}' ({col_type}) есть в целевой БД, но "
            "отсутствует в эталоне. При удалении будут потеряны значения."
        )

    if kind == "different_column_type":
        column = change.get("column")
        return (
            f"Тип колонки '{table}.{column}' отличается: target={change.get('target')}, "
            f"source={change.get('source')}. Может потребоваться конвертация данных."
        )

    if kind == "different_column_nullable":
        column = change.get("column")
        return (
            f"NULLABLE у '{table}.{column}' отличается: target={change.get('target')}, "
            f"source={change.get('source')}. SET NOT NULL упадет, если есть NULL."
        )

    if kind == "different_column_default":
        column = change.get("column")
        return (
            f"DEFAULT у '{table}.{column}' отличается: target={change.get('target')}, "
            f"source={change.get('source')}. Изменение повлияет только на новые INSERT."
        )

    if kind == "different_primary_key":
        return (
            f"PRIMARY KEY у '{table}' отличается: target={change.get('target')}, "
            f"source={change.get('source')}. Пересоздание PK может блокировать таблицу."
        )

    if kind == "missing_foreign_key":
        fk = change.get("source") or {}
        return (
            f"FOREIGN KEY '{fk.get('name')}' {fk.get('constrained_columns')} -> "
            f"{fk.get('referred_table')}({fk.get('referred_columns')}) есть в эталоне, "
            "но отсутствует в целевой БД. Добавление упадет при битых ссылках."
        )

    if kind == "extra_foreign_key":
        fk = change.get("target") or {}
        return (
            f"FOREIGN KEY '{fk.get('name')}' есть в целевой БД, но отсутствует "
            "в эталоне. Будет удален."
        )

    if kind == "missing_unique_constraint":
        unique = change.get("source") or {}
        return (
            f"UNIQUE '{unique.get('name')}' по колонкам {unique.get('columns')} "
            "есть в эталоне, но отсутствует в целевой БД. Добавление упадет при дублях."
        )

    if kind == "extra_unique_constraint":
        unique = change.get("target") or {}
        return (
            f"UNIQUE '{unique.get('name')}' по колонкам {unique.get('columns')} "
            "есть в целевой БД, но отсутствует в эталоне. Будет удален."
        )

    if kind == "missing_index":
        index = change.get("source") or {}
        unique_mark = " UNIQUE" if index.get("unique") else ""
        return (
            f"Индекс{unique_mark} '{index.get('name')}' по колонкам "
            f"{index.get('columns')} есть в эталоне, но отсутствует в целевой БД."
        )

    if kind == "extra_index":
        index = change.get("target") or {}
        unique_mark = " UNIQUE" if index.get("unique") else ""
        return (
            f"Индекс{unique_mark} '{index.get('name')}' по колонкам "
            f"{index.get('columns')} есть в целевой БД, но отсутствует в эталоне. "
            "Будет удален."
        )

    if kind == "missing_check_constraint":
        check = change.get("source") or {}
        return (
            f"CHECK '{check.get('name')}' ({check.get('sqltext')}) есть в эталоне, "
            "но отсутствует в целевой БД. Добавление упадет при несовместимых строках."
        )

    if kind == "extra_check_constraint":
        check = change.get("target") or {}
        return (
            f"CHECK '{check.get('name')}' ({check.get('sqltext')}) есть в целевой БД, "
            "но отсутствует в эталоне. Будет удален."
        )

    return f"Неизвестный тип изменения: {kind}"


def classify_missing_column(change: Change) -> str:
    """Отнести добавление колонки к safe или risky.

    NULL-колонка или колонка с DEFAULT - safe (можно добавить без
    backfill'а). NOT NULL без DEFAULT - risky: на непустой таблице
    ALTER TABLE упадёт без явного бэкфилла.
    """
    if change.get("source_nullable"):
        return "safe"
    if change.get("source_default") is not None:
        return "safe"
    return "risky"


def classify_changes(changes: list[Change]) -> dict[str, list[Change]]:
    """Разложить список изменений по корзинам safe / risky / destructive.

    Заодно прикручивает каждое change поле description с человеко-
    читаемым объяснением, что именно поменяется.
    """
    plan: dict[str, list[Change]] = {
        "safe": [],
        "risky": [],
        "destructive": [],
    }

    for change in changes:
        change["description"] = describe_change(change)

        kind = change["kind"]
        if kind == "missing_table":
            plan["safe"].append(change)
        elif kind == "missing_column":
            plan[classify_missing_column(change)].append(change)
        elif kind == "missing_index":
            # Уникальный индекс без UNIQUE constraint = был запрет на
            # дубли. Удаление = риск, что появятся дубли. Обычный
            # индекс - просто оптимизация.
            if (change.get("source") or {}).get("unique"):
                plan["risky"].append(change)
            else:
                plan["safe"].append(change)
        elif kind == "different_column_type":
            if is_type_change_safe(change.get("source", ""), change.get("target", "")):
                plan["safe"].append(change)
            else:
                plan["risky"].append(change)
        elif kind == "different_primary_key":
            # Пересоздание PK блокирует таблицу и каскадирует на FK,
            # которые на неё ссылаются - всегда destructive.
            plan["destructive"].append(change)
        elif kind in {
            "extra_table",
            "extra_column",
            "extra_index",
            "extra_foreign_key",
            "extra_unique_constraint",
            "extra_check_constraint",
        }:
            plan["destructive"].append(change)
        elif kind in {
            "different_column_nullable",
            "different_column_default",
            "missing_foreign_key",
            "missing_unique_constraint",
            "missing_check_constraint",
        }:
            plan["risky"].append(change)

        else:
            plan["risky"].append(change)

    return plan
