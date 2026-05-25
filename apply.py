"""Применение сгенерированного SQL к target-БД.

Главное: SQL режется на отдельные statements, выполняется в одной
транзакции, и в случае ошибки делается полный rollback - "половины"
применения не бывает. Результат сохраняется в JSON-отчёт в reports/.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from config import settings
from db import create_db_engine
from reports_meta import REPORT_ID_RE, REPORTS_DIR, utc_now_iso_z, utc_now_report_id

logger = logging.getLogger(__name__)


def _dollar_quote_tag(sql_text: str, pos: int) -> str | None:
    """Распознать начало dollar-quote блока ($$...$$ или $tag$...$tag$).

    Возвращает сам открывающий тег ($$ или $foo$), по которому позже
    ищется парный закрывающий. Нужно потому, что внутри dollar-блока
    ';' не разделяет statement-ы.
    """
    if sql_text[pos] != "$":
        return None
    end = pos + 1
    while end < len(sql_text) and (
        sql_text[end].isalnum() or sql_text[end] == "_"
    ):
        end += 1
    if end < len(sql_text) and sql_text[end] == "$":
        return sql_text[pos : end + 1]
    return None


def _has_sql_code(statement: str) -> bool:
    """Проверить, что statement содержит код, а не только комменты и пробелы.

    Если между ';' оказался лишь "-- комментарий", в БД отправлять нечего -
    скипаем, чтобы пустые запросы не падали.
    """
    in_line_comment = False
    in_block_comment = False
    i = 0

    while i < len(statement):
        ch = statement[i]
        nxt = statement[i + 1] if i + 1 < len(statement) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if not ch.isspace():
            return True
        i += 1

    return False


def split_sql_statements(sql_text: str) -> list[str]:
    """Разрезать SQL-скрипт на отдельные statement-ы по ';'.

    sql.split(';') использовать нельзя: ';' может быть внутри строки
    'a;b', внутри комментария или внутри DO $$ ... ; ... $$ блока.
    Поэтому идём по символам и помним текущий контекст: одинарная
    кавычка, двойная кавычка, линейный или блочный коммент,
    dollar-quoted блок.
    """
    statements: list[str] = []
    start = 0
    in_single = False
    in_double = False
    in_line_comment = False
    in_block_comment = False
    dollar_tag: str | None = None
    i = 0

    while i < len(sql_text):
        ch = sql_text[i]
        nxt = sql_text[i + 1] if i + 1 < len(sql_text) else ""

        if in_line_comment:
            if ch == "\n":
                in_line_comment = False
            i += 1
            continue

        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
            else:
                i += 1
            continue

        if dollar_tag:
            if sql_text.startswith(dollar_tag, i):
                i += len(dollar_tag)
                dollar_tag = None
            else:
                i += 1
            continue

        if in_single:
            if ch == "'" and nxt == "'":
                i += 2
            elif ch == "'":
                in_single = False
                i += 1
            else:
                i += 1
            continue

        if in_double:
            if ch == '"' and nxt == '"':
                i += 2
            elif ch == '"':
                in_double = False
                i += 1
            else:
                i += 1
            continue

        if ch == "-" and nxt == "-":
            in_line_comment = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_block_comment = True
            i += 2
            continue
        if ch == "'":
            in_single = True
            i += 1
            continue
        if ch == '"':
            in_double = True
            i += 1
            continue
        if ch == "$":
            tag = _dollar_quote_tag(sql_text, i)
            if tag:
                dollar_tag = tag
                i += len(tag)
                continue
        if ch == ";":
            statement = sql_text[start:i].strip()
            if statement and _has_sql_code(statement):
                statements.append(statement)
            start = i + 1
        i += 1

    tail = sql_text[start:].strip()
    if tail and _has_sql_code(tail):
        statements.append(tail)
    return statements


def apply_sql_text(engine: Engine, sql: str) -> dict[str, Any]:
    """Применить SQL к target-БД одной транзакцией.

    Главное: если что-то упало посередине, делается rollback и target
    остаётся в том же виде, что и до запуска. Никаких "половина прошла,
    половина нет". В PG DDL транзакционный, поэтому работает даже для
    CREATE TABLE / ALTER TABLE.
    """
    statements = split_sql_statements(sql)
    executed: list[str] = []
    with engine.connect() as conn:
        transaction = conn.begin()
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                transaction.rollback()
                logger.error(
                    "SQL-операция упала после %s успешных, транзакция откатана: %s",
                    len(executed),
                    exc,
                )
                return {
                    "status": "error",
                    "executed_count": len(executed),
                    "failed_statement": stmt,
                    "error": str(exc),
                    "executed_statements": executed,
                }
            executed.append(stmt)
        transaction.commit()
    logger.info("Apply завершён успешно, выполнено %s SQL-операций", len(executed))
    return {
        "status": "ok",
        "executed_count": len(executed),
        "executed_statements": executed,
    }


def summarize_post_apply(target_url: str) -> dict[str, Any] | None:
    """Повторно сравнить БД после apply и посчитать оставшийся diff.

    Удобно для человека: видно "применили safe, осталось risky=3
    destructive=2" - понятно, что ещё надо доделать, чтобы target
    полностью совпал с source. Если source_database_url не задан -
    молча скипаем, не критично.
    """
    if not settings.source_database_url:
        return None

    # Импорты внутри функции, чтобы не было циклической зависимости
    # через main.py / report_service.py.
    from compare_database import compare_databases
    from plan import classify_changes

    source = create_db_engine(settings.source_database_url)
    target = create_db_engine(target_url)
    plan = classify_changes(
        compare_databases(
            source,
            target,
            source_schema=settings.source_schema,
            target_schema=settings.target_schema,
        )
    )
    return {
        "remaining_summary": {
            "safe": len(plan["safe"]),
            "risky": len(plan["risky"]),
            "destructive": len(plan["destructive"]),
        },
        "remaining_changes": [
            {
                "bucket": bucket,
                "kind": change.get("kind"),
                "table": change.get("table"),
                "column": change.get("column"),
                "description": change.get("description"),
            }
            for bucket, changes in plan.items()
            for change in changes
        ],
    }


def save_apply_result(
    report_id: str,
    result: dict[str, Any],
    target_url: str,
) -> dict[str, Any]:
    """Сохранить результат apply в reports/<report_id>_apply_result.json.

    По файлу видно: статус (ок/ошибка), сколько statement-ов прошло,
    на каком упал, и какой diff остался в БД после применения.
    """
    # report_id из CLI - доверенный (локальный пользователь), из API - уже
    # отвалидирован в report_service.validate_report_id. Здесь проверяем
    # ещё раз как defense-in-depth, чтобы любой другой вызывающий код не
    # записал файл за пределы REPORTS_DIR.
    if not REPORT_ID_RE.match(report_id):
        raise ValueError(f"invalid report_id format: {report_id!r}")
    # post_apply считаем только при успехе - если упало, target не менялся,
    # diff будет тот же, что и до apply.
    post_apply = summarize_post_apply(target_url) if result["status"] == "ok" else None
    payload = {
        "report_id": report_id,
        "created_at": utc_now_iso_z(),
        "status": result["status"],
        "executed_count": result.get("executed_count", 0),
        "failed_statement": result.get("failed_statement"),
        "error": result.get("error"),
        "post_apply": post_apply,
    }
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORTS_DIR / f"{report_id}_apply_result.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"path": str(path), "post_apply": post_apply}


def resolve_sql_path(report_arg: str) -> Path:
    """Найти .sql файл по аргументу CLI.

    Если аргумент - существующий файл, берём его как есть. Иначе
    считаем его report_id и ищем reports/<id>.sql. Так можно передать
    и "20240115T120000_safe", и "/tmp/my.sql".
    """
    candidate = Path(report_arg)
    if candidate.is_file():
        return candidate
    by_id = REPORTS_DIR / f"{report_arg}.sql"
    if by_id.is_file():
        return by_id
    raise FileNotFoundError(
        f"Не нашли отчет: {report_arg}. Проверили {candidate} и {by_id}."
    )


def main(argv: list[str] | None = None) -> int:
    """CLI-обёртка: `python apply.py <report_id>` или `python apply.py file.sql`.

    Парсит аргументы, печатает SQL человеку, спрашивает подтверждение,
    применяет SQL, сохраняет результат в JSON и возвращает exit code
    (0 успех, 1 отмена, 2 ошибка применения).
    """
    parser = argparse.ArgumentParser(
        description="Применить сгенерированный отчет к target-БД."
    )
    parser.add_argument(
        "report",
        help="report_id из /generate или путь к .sql-файлу.",
    )
    parser.add_argument(
        "--target-url",
        default=None,
        help="URL целевой БД. По умолчанию берется из settings.target_database_url.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Не спрашивать подтверждение перед выполнением.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Уровень логирования (DEBUG/INFO/WARNING/ERROR). По умолчанию INFO.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    sql_path = resolve_sql_path(args.report)
    sql = sql_path.read_text(encoding="utf-8")

    # SQL и интерактивный prompt идут в stdout, потому что это рабочий
    # вывод CLI: пользователь должен глазами прочитать SQL перед "y/N".
    # logger использован для журналируемых событий (старт/конец apply,
    # ошибки), которые могут идти в файл/централизованный лог.
    logger.info("Открыт отчёт: %s", sql_path)
    sys.stdout.write(f"Отчет: {sql_path}\n")
    sys.stdout.write("-" * 60 + "\n")
    sys.stdout.write(sql + "\n")
    sys.stdout.write("-" * 60 + "\n")
    sys.stdout.flush()

    if not args.yes:
        answer = input("Применить к target-БД? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            logger.info("Apply отменён пользователем")
            sys.stdout.write("Отменено.\n")
            return 1

    target_url = args.target_url or settings.target_database_url
    engine = create_db_engine(target_url)
    result = apply_sql_text(engine, sql)
    # CLI принимает либо report_id, либо путь к .sql. save_apply_result
    # требует канонический id - если пользователь дал путь, берём stem;
    # если stem не подходит под формат, синтезируем id на основе времени.
    candidate_id = sql_path.stem
    if not REPORT_ID_RE.match(candidate_id):
        candidate_id = utc_now_report_id("safe")
    saved_result = save_apply_result(candidate_id, result, target_url)

    if result["status"] == "ok":
        logger.info(
            "Apply OK: %s SQL-операций, отчёт %s",
            result["executed_count"],
            saved_result["path"],
        )
        sys.stdout.write(f"OK: выполнено SQL-операций: {result['executed_count']}\n")
        sys.stdout.write(f"Результат применения: {saved_result['path']}\n")
        post_apply = saved_result.get("post_apply") or {}
        remaining = post_apply.get("remaining_summary")
        if remaining:
            sys.stdout.write(f"Осталось diff: {remaining}\n")
        return 0

    logger.error(
        "Apply failed: %s SQL-операций до ошибки, statement=%r",
        result["executed_count"],
        result["failed_statement"],
    )
    sys.stdout.write(f"Ошибка после {result['executed_count']} SQL-операций:\n")
    sys.stdout.write(f"  statement: {result['failed_statement']}\n")
    sys.stdout.write(f"  error:     {result['error']}\n")
    sys.stdout.write("Транзакция откатана, БД не изменена.\n")
    sys.stdout.write(f"Результат применения: {saved_result['path']}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
