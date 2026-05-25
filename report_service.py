"""Сервисный слой для FastAPI-эндпойнтов.

В этом модуле собрано всё, что main.py использовал как помощников:
валидация report_id, разрешение URL, построение плана изменений,
сохранение и чтение отчётов, а также сбор диагностики по target-БД.

main.py остаётся "тонким" - только FastAPI-приложение, Pydantic-модели
и эндпойнты. Любая бизнес-логика, не связанная напрямую с HTTP, живёт
здесь и переиспользуется тестами или сторонним кодом.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Literal, cast

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.engine import Engine

from compare_database import compare_databases
from config import settings
from db import create_db_engine
from plan import classify_changes
from reports_meta import REPORT_ID_RE, REPORTS_DIR, utc_now_iso_z, utc_now_report_id
from sql_generator import qualified_name, quote_ident, quote_ident_list

logger = logging.getLogger(__name__)

Mode = Literal["safe", "risky", "destructive"]
Change = dict[str, Any]


def validate_report_id(report_id: str) -> str:
    """Проверить формат report_id и вернуть его, либо бросить HTTP 400.

    report_id используется как имя файла внутри REPORTS_DIR, поэтому
    нельзя пропускать произвольные строки - иначе можно вылезти за
    пределы каталога отчётов.
    """
    if not REPORT_ID_RE.match(report_id):
        raise HTTPException(
            status_code=400,
            detail=f"invalid report_id format: {report_id!r}",
        )
    return report_id


def resolve_url(value: str | None, fallback: str, role: str) -> str:
    """Вернуть URL подключения для роли source/target.

    Приоритет: явно переданное значение, затем fallback из settings.
    Если оба пустые - HTTP 400 с понятным сообщением, чтобы клиент
    сразу видел, какой именно URL нужно дозаполнить.
    """
    url = value or fallback
    if not url:
        raise HTTPException(
            status_code=400,
            detail=f"{role} url is not provided and {role}_database_url is empty",
        )
    return url


def build_plan_from_urls(
    source_url: str,
    target_url: str,
    source_schema: str | None,
    target_schema: str | None,
) -> dict[str, list[Change]]:
    """Сравнить две БД по URL и вернуть план, разбитый на safe/risky/destructive."""
    source: Engine = create_db_engine(source_url)
    target: Engine = create_db_engine(target_url)
    changes = compare_databases(
        source,
        target,
        source_schema=source_schema,
        target_schema=target_schema,
    )
    return classify_changes(changes)


def collect_changes_for_mode(plan: dict[str, list[Change]], mode: Mode) -> list[Change]:
    """Накопительно собрать изменения для выбранного режима.

    safe -> только safe; risky -> safe+risky; destructive -> всё.
    Так пользователь, выбирая режим, явно повышает уровень риска того,
    что реально поедет в БД.
    """
    if mode == "safe":
        return list(plan["safe"])
    if mode == "risky":
        return plan["safe"] + plan["risky"]
    if mode == "destructive":
        return plan["safe"] + plan["risky"] + plan["destructive"]
    raise HTTPException(status_code=400, detail=f"unknown mode: {mode}")


def save_report(
    mode: Mode,
    changes: list[Change],
    sql: str,
    diagnostics: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Сохранить SQL-отчёт и метаданные на диск, вернуть пути и id."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_id = utc_now_report_id(mode)
    sql_path = REPORTS_DIR / f"{report_id}.sql"
    meta_path = REPORTS_DIR / f"{report_id}.json"

    sql_path.write_text(sql, encoding="utf-8")
    meta = {
        "report_id": report_id,
        "mode": mode,
        "created_at": utc_now_iso_z(),
        "changes": changes,
        "diagnostics": diagnostics or [],
    }
    meta_path.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Сохранён отчёт %s (%s изменений)", report_id, len(changes))
    return {
        "report_id": report_id,
        "sql_path": str(sql_path),
        "meta_path": str(meta_path),
    }


def load_report(report_id: str) -> tuple[str, dict[str, Any]]:
    """Прочитать SQL и meta ранее сохранённого отчёта по id."""
    validate_report_id(report_id)
    sql_path = REPORTS_DIR / f"{report_id}.sql"
    meta_path = REPORTS_DIR / f"{report_id}.json"
    if not sql_path.exists() or not meta_path.exists():
        raise HTTPException(status_code=404, detail=f"report not found: {report_id}")
    sql = sql_path.read_text(encoding="utf-8")
    meta = cast(dict[str, Any], json.loads(meta_path.read_text(encoding="utf-8")))
    return sql, meta


def collect_report_diagnostics(target: Engine, changes: list[Change]) -> list[dict[str, Any]]:
    """Собрать диагностику по изменениям, требующим внимания.

    Заглядывает в target-БД (FK-нарушения, дубли UNIQUE, размер таблицы)
    и возвращает список структур, которые попадают в meta-файл отчёта.
    """
    diagnostics: list[dict[str, Any]] = []
    unique_index_keys = {
        (
            change.get("schema"),
            change.get("table"),
            tuple((change.get("source") or {}).get("columns") or []),
        )
        for change in changes
        if change["kind"] == "missing_unique_constraint"
    }
    with target.connect() as conn:
        for change in changes:
            kind = change["kind"]
            if kind == "missing_foreign_key":
                diagnostics.append(foreign_key_diagnostic(conn, change))
            elif kind == "missing_unique_constraint":
                diagnostics.append(unique_constraint_diagnostic(conn, change))
            elif kind == "missing_index":
                index = change.get("source") or {}
                index_key = (
                    change.get("schema"),
                    change.get("table"),
                    tuple(index.get("columns") or []),
                )
                if index.get("unique") and index_key in unique_index_keys:
                    diagnostics.append(unique_index_diagnostic(change))
            elif kind == "different_primary_key":
                diagnostics.append(primary_key_diagnostic(conn, change))
            elif kind == "extra_table":
                diagnostics.append(extra_table_diagnostic(conn, change))
    return diagnostics


def primary_key_diagnostic(conn: Any, change: Change) -> dict[str, Any]:
    """Сформировать предупреждение о пересоздании PRIMARY KEY.

    PG берёт ACCESS EXCLUSIVE на DROP CONSTRAINT и держит его до конца
    транзакции. На больших таблицах это блокирует все чтения и записи,
    поэтому диагностика отдельно отмечает row_count и поднимает severity.
    """
    table = qualified_name(change["table"], change.get("schema"))
    try:
        row_count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    except Exception as exc:
        return {
            "kind": "primary_key_rewrite",
            "severity": "warning",
            "table": change.get("table"),
            "behavior": "Could not estimate row count for primary key rewrite.",
            "error": str(exc),
        }
    severity = "warning" if row_count > 10_000 else "info"
    return {
        "kind": "primary_key_rewrite",
        "severity": severity,
        "table": change.get("table"),
        "row_count": row_count,
        "source_pk": change.get("source"),
        "target_pk": change.get("target"),
        "behavior": (
            "DROP CONSTRAINT + ADD CONSTRAINT берёт ACCESS EXCLUSIVE на таблицу. "
            "Все чтения и записи в таблицу будут заблокированы до конца транзакции."
        ),
        "follow_up": (
            "Для больших таблиц рассмотрите онлайн-стратегию: создать новый UNIQUE "
            "индекс через CREATE INDEX CONCURRENTLY и затем менять PK в короткой "
            "транзакции, либо вынести операцию в окно обслуживания."
        ),
    }


def extra_table_diagnostic(conn: Any, change: Change) -> dict[str, Any]:
    """Оценить последствия DROP TABLE для лишней в target таблицы."""
    table = qualified_name(change["table"], change.get("schema"))
    target_definition = change.get("target") or {}
    try:
        row_count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    except Exception as exc:
        return {
            "kind": "extra_table_drop",
            "severity": "warning",
            "table": change.get("table"),
            "behavior": "Could not estimate row count for extra table.",
            "error": str(exc),
        }
    severity = "warning" if row_count > 0 else "info"
    return {
        "kind": "extra_table_drop",
        "severity": severity,
        "table": change.get("table"),
        "row_count": row_count,
        "columns": [c.get("name") for c in target_definition.get("columns") or []],
        "foreign_keys": [fk.get("name") for fk in target_definition.get("foreign_keys") or []],
        "behavior": (
            "DROP TABLE удалит все строки и связанные объекты (FK, индексы, права). "
            "Закомментировано в safe/risky; выполняется только в режиме destructive."
        ),
        "follow_up": (
            "Если данные нужны - сделайте бэкап (pg_dump) или переименуйте таблицу "
            "вместо удаления."
        ),
    }


def unique_index_diagnostic(change: Change) -> dict[str, Any]:
    """Объяснить, почему отдельный CREATE UNIQUE INDEX не генерируется.

    PostgreSQL создаёт нижележащий unique-индекс автоматически при
    добавлении UNIQUE constraint, поэтому отдельный CREATE INDEX был бы
    дубликатом.
    """
    index = change.get("source") or {}
    return {
        "kind": "unique_index_covered_by_constraint",
        "severity": "info",
        "table": change.get("table"),
        "index": index.get("name"),
        "columns": list(index.get("columns") or []),
        "behavior": (
            "No separate CREATE UNIQUE INDEX is generated because PostgreSQL "
            "creates the backing unique index automatically when the UNIQUE "
            "constraint is added."
        ),
        "follow_up": (
            "If the guarded UNIQUE constraint is skipped because duplicates exist, "
            "this index will also remain absent until duplicates are cleaned."
        ),
    }


def foreign_key_diagnostic(conn: Any, change: Change) -> dict[str, Any]:
    """Найти примеры строк target, нарушающих создаваемый FK.

    SQL добавляет ограничение с NOT VALID, но пользователю полезно
    увидеть первые 10 битых ссылок ещё до применения - чтобы решить,
    очищать их или нет перед последующим VALIDATE CONSTRAINT.
    """
    fk = change.get("source") or {}
    referred_table = fk.get("referred_table")
    if not referred_table:
        return {
            "kind": "foreign_key_not_valid",
            "severity": "warning",
            "table": change.get("table"),
            "constraint": fk.get("name"),
            "behavior": "Cannot preflight this foreign key: referred_table is missing.",
        }
    table = qualified_name(change["table"], change.get("schema"))
    ref_table = qualified_name(
        referred_table,
        fk.get("referred_schema") or change.get("schema"),
    )
    constrained_columns = list(fk.get("constrained_columns") or [])
    referred_columns = list(fk.get("referred_columns") or [])
    join_clause = " AND ".join(
        f"src.{quote_ident(src)} = ref.{quote_ident(ref)}"
        for src, ref in zip(constrained_columns, referred_columns, strict=True)
    )
    missing_clause = " AND ".join(
        f"ref.{quote_ident(ref)} IS NULL" for ref in referred_columns
    )
    sample_cols = ", ".join(
        f"src.{quote_ident(col)} AS {quote_ident(col)}" for col in constrained_columns
    )
    sample_sql = (
        f"SELECT {sample_cols} FROM {table} AS src "
        f"LEFT JOIN {ref_table} AS ref ON {join_clause} "
        f"WHERE {missing_clause} LIMIT 10"
    )
    sample_rows = [dict(row._mapping) for row in conn.execute(text(sample_sql))]
    return {
        "kind": "foreign_key_not_valid",
        "severity": "warning" if sample_rows else "info",
        "table": change.get("table"),
        "constraint": fk.get("name"),
        "columns": constrained_columns,
        "referred_table": fk.get("referred_table"),
        "referred_columns": referred_columns,
        "behavior": (
            "SQL is generated with NOT VALID: the constraint is created without "
            "checking existing rows, but new writes are protected."
        ),
        "existing_violations_sample": sample_rows,
        "follow_up": (
            "Clean existing violating rows and run VALIDATE CONSTRAINT when you "
            "need the constraint fully validated."
        ),
    }


def unique_constraint_diagnostic(conn: Any, change: Change) -> dict[str, Any]:
    """Найти примеры дублей, которые помешают добавлению UNIQUE constraint."""
    unique = change.get("source") or {}
    table = qualified_name(change["table"], change.get("schema"))
    columns = list(unique.get("columns") or [])
    cols = quote_ident_list(columns)
    not_null = " AND ".join(f"{quote_ident(col)} IS NOT NULL" for col in columns)
    duplicate_sql = (
        f"SELECT {cols}, COUNT(*) AS duplicate_count FROM {table}"
        + (f" WHERE {not_null}" if not_null else "")
        + f" GROUP BY {cols} HAVING COUNT(*) > 1 LIMIT 10"
    )
    duplicates = [dict(row._mapping) for row in conn.execute(text(duplicate_sql))]
    return {
        "kind": "unique_constraint_guarded",
        "severity": "warning" if duplicates else "info",
        "table": change.get("table"),
        "constraint": unique.get("name"),
        "columns": columns,
        "behavior": (
            "SQL checks duplicate key values first. If duplicates exist, it emits "
            "a database WARNING and skips adding the UNIQUE constraint instead of "
            "failing the whole apply."
        ),
        "duplicate_values_sample": duplicates,
        "follow_up": "Remove duplicates and rerun the report to add the UNIQUE constraint.",
    }
