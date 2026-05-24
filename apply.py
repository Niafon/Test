from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from config import settings
from db import create_db_engine


REPORTS_DIR = Path(__file__).parent / "reports"

# См. main.py: report_id всегда имеет формат YYYYMMDDTHHMMSS_<mode>. Любой
# другой вход в save_apply_result отклоняем, чтобы '..' или абсолютный путь
# не позволил записать файл за пределами REPORTS_DIR.
_REPORT_ID_RE = re.compile(r"^[0-9]{8}T[0-9]{6}_(safe|risky|destructive)$")


def _dollar_quote_tag(sql_text: str, pos: int) -> str | None:
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
    statements = split_sql_statements(sql)
    executed: list[str] = []
    with engine.connect() as conn:
        transaction = conn.begin()
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except Exception as exc:
                transaction.rollback()
                return {
                    "status": "error",
                    "executed_count": len(executed),
                    "failed_statement": stmt,
                    "error": str(exc),
                    "executed_statements": executed,
                }
            executed.append(stmt)
        transaction.commit()
    return {
        "status": "ok",
        "executed_count": len(executed),
        "executed_statements": executed,
    }


def summarize_post_apply(target_url: str) -> dict[str, Any] | None:
    if not settings.source_database_url:
        return None

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
    # report_id из CLI - доверенный (локальный пользователь), из API - уже
    # отвалидирован в main.validate_report_id. Здесь проверяем ещё раз как
    # defense-in-depth, чтобы любой другой вызывающий код не записал файл за
    # пределы REPORTS_DIR.
    if not _REPORT_ID_RE.match(report_id):
        raise ValueError(f"invalid report_id format: {report_id!r}")
    post_apply = summarize_post_apply(target_url) if result["status"] == "ok" else None
    payload = {
        "report_id": report_id,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
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
    args = parser.parse_args(argv)

    sql_path = resolve_sql_path(args.report)
    sql = sql_path.read_text(encoding="utf-8")

    print(f"Отчет: {sql_path}")
    print("-" * 60)
    print(sql)
    print("-" * 60)

    if not args.yes:
        answer = input("Применить к target-БД? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            print("Отменено.")
            return 1

    target_url = args.target_url or settings.target_database_url
    engine = create_db_engine(target_url)
    result = apply_sql_text(engine, sql)
    # CLI принимает либо report_id, либо путь к .sql. save_apply_result требует
    # канонический id - если пользователь дал путь, извлекаем stem; если stem
    # не подходит, синтезируем id на основе текущего времени, чтобы apply всё
    # же отчитался файлом.
    candidate_id = sql_path.stem
    if not _REPORT_ID_RE.match(candidate_id):
        candidate_id = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_safe"
    saved_result = save_apply_result(candidate_id, result, target_url)

    if result["status"] == "ok":
        print(f"OK: выполнено SQL-операций: {result['executed_count']}")
        print(f"Результат применения: {saved_result['path']}")
        post_apply = saved_result.get("post_apply") or {}
        remaining = post_apply.get("remaining_summary")
        if remaining:
            print(f"Осталось diff: {remaining}")
        return 0

    print(f"Ошибка после {result['executed_count']} SQL-операций:")
    print(f"  statement: {result['failed_statement']}")
    print(f"  error:     {result['error']}")
    print("Транзакция откатана, БД не изменена.")
    print(f"Результат применения: {saved_result['path']}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
