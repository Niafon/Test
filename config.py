"""Настройки приложения: URL подключений и имена схем.

Значения тянутся из переменных окружения и/или из файла .env рядом с
проектом. Конкретные URLs определяются переменными
SOURCE_DATABASE_URL / TARGET_DATABASE_URL, а имена схем -
SOURCE_SCHEMA / TARGET_SCHEMA.
"""
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Конфигурация подключения к source/target БД и используемых схем."""

    source_database_url: str = ""
    target_database_url: str = ""
    source_schema: str | None = None
    target_schema: str | None = None

    model_config: ClassVar[SettingsConfigDict] = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
