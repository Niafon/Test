"""HTTP-маршруты DB Diff API.

Все эндпойнты вынесены в APIRouter, чтобы main.py остался "тонким" -
только сборка FastAPI-приложения и точка запуска. Подключается одной
строкой `app.include_router(router)`.
"""
from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.engine import Engine

from apply import apply_sql_text, save_apply_result
from config import settings
from db import create_db_engine
from report_service import (
    Mode,
    build_plan_from_urls,
    collect_changes_for_mode,
    collect_report_diagnostics,
    load_report,
    resolve_url,
    save_report,
    validate_report_id,
)
from sql_generator import generate_sql

logger = logging.getLogger(__name__)

router = APIRouter()


class GenerateIn(BaseModel):
    """Входные параметры для /generate и /report - URLs и схемы обеих БД."""

    source_url: str | None = Field(default=None, examples=[settings.source_database_url])
    target_url: str | None = Field(default=None, examples=[settings.target_database_url])
    source_schema: str | None = Field(
        default=None,
        description="PostgreSQL schema name. Leave null to use the default search path.",
        examples=[None],
    )
    target_schema: str | None = Field(
        default=None,
        description="PostgreSQL schema name. Leave null to use the default search path.",
        examples=[None],
    )

    @field_validator("source_schema", "target_schema")
    @classmethod
    def reject_swagger_placeholder(cls, value: str | None) -> str | None:
        """Не пропустить дефолтное "string" из Swagger UI как имя схемы."""
        if value == "string":
            raise ValueError("schema must be a real schema name or null, not 'string'")
        return value


class ApplyIn(BaseModel):
    """Входные параметры для /apply - только target, source трогать незачем."""

    target_url: str | None = Field(default=None, examples=[settings.target_database_url])


@router.post("/report/{bucket}")
def report_bucket(
    bucket: Literal["safe", "risky", "destructive"],
    payload: GenerateIn,
) -> dict[str, Any]:
    """Просмотр одной корзины без сохранения файла - удобно для UI/CLI.

    Принимает те же URLs, что и /generate: вся информация о подключении
    приходит в теле запроса, глобального состояния нет.
    """
    source_url = resolve_url(payload.source_url, settings.source_database_url, "source")
    target_url = resolve_url(payload.target_url, settings.target_database_url, "target")
    plan = build_plan_from_urls(
        source_url,
        target_url,
        payload.source_schema or settings.source_schema,
        payload.target_schema or settings.target_schema,
    )
    return {"bucket": bucket, "count": len(plan[bucket]), "changes": plan[bucket]}


@router.post("/generate/{mode}")
def generate_report(mode: Mode, payload: GenerateIn) -> dict[str, Any]:
    """Сравнить обе БД, собрать SQL-отчёт и положить его на диск.

    Один запрос делает всё: открывает подключения по присланным URL,
    считает план, формирует SQL для выбранного режима, пишет файлы в
    reports/ и возвращает report_id. После этого человек смотрит SQL и
    дёргает /apply/{report_id}.
    """
    source_url = resolve_url(payload.source_url, settings.source_database_url, "source")
    target_url = resolve_url(payload.target_url, settings.target_database_url, "target")

    plan = build_plan_from_urls(
        source_url,
        target_url,
        payload.source_schema or settings.source_schema,
        payload.target_schema or settings.target_schema,
    )
    changes = collect_changes_for_mode(plan, mode)
    sql = generate_sql(changes, mode)
    target: Engine = create_db_engine(target_url)
    diagnostics = collect_report_diagnostics(target, changes)
    saved = save_report(mode, changes, sql, diagnostics=diagnostics)

    logger.info(
        "Сгенерирован отчёт %s в режиме %s: %s изменений (safe=%d, risky=%d, destructive=%d)",
        saved["report_id"],
        mode,
        len(changes),
        len(plan["safe"]),
        len(plan["risky"]),
        len(plan["destructive"]),
    )

    return {
        "report_id": saved["report_id"],
        "mode": mode,
        "sql_path": saved["sql_path"],
        "meta_path": saved["meta_path"],
        "summary": {
            "safe": len(plan["safe"]),
            "risky": len(plan["risky"]),
            "destructive": len(plan["destructive"]),
            "included": len(changes),
        },
        "changes": [
            {
                "kind": c["kind"],
                "table": c.get("table"),
                "column": c.get("column"),
                "description": c.get("description"),
            }
            for c in changes
        ],
        "diagnostics": diagnostics,
        "sql": sql,
        "apply_hint": (
            f"Изучите SQL и затем примените: POST /apply/{saved['report_id']} "
            f"(в теле target_url) или `python apply.py {saved['report_id']}`."
        ),
    }


@router.post("/apply/{report_id}")
def apply_report(report_id: str, payload: ApplyIn) -> dict[str, Any]:
    """Применить ранее сгенерированный отчёт к target-БД.

    URL берём из тела запроса (или из settings по дефолту). Сам SQL
    читаем с диска - тот же файл, который человек видел в /generate.
    """
    validate_report_id(report_id)
    sql, meta = load_report(report_id)
    target_url = resolve_url(payload.target_url, settings.target_database_url, "target")
    target: Engine = create_db_engine(target_url)
    result = apply_sql_text(target, sql)
    saved_result = save_apply_result(report_id, result, target_url)
    logger.info(
        "Apply отчёта %s завершён со статусом %s (выполнено %s SQL-операций)",
        report_id,
        result.get("status"),
        result.get("executed_count"),
    )
    return {
        "report_id": report_id,
        "mode": meta.get("mode"),
        "apply_result_path": saved_result["path"],
        **result,
        "post_apply": saved_result.get("post_apply"),
    }
