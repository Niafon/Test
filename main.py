"""Точка входа DB Diff API.

Только сборка FastAPI-приложения и запуск uvicorn. Все эндпойнты
живут в routes.py и подключаются через include_router. Вся бизнес-
логика - в report_service.py.

Запуск без Docker:
    python main.py
Хост/порт/уровень логов переопределяются через DB_DIFF_HOST /
DB_DIFF_PORT / DB_DIFF_LOG_LEVEL.
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from routes import router

app = FastAPI(title="DB Diff API")
app.include_router(router)


if __name__ == "__main__":
    import os

    import uvicorn

    log_level = os.environ.get("DB_DIFF_LOG_LEVEL", "info").lower()
    logging.basicConfig(
        level=log_level.upper(),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    uvicorn.run(
        "main:app",
        host=os.environ.get("DB_DIFF_HOST", "127.0.0.1"),
        port=int(os.environ.get("DB_DIFF_PORT", "8000")),
        log_level=log_level,
        reload=False,
    )
