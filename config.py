from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict

# Настройички для подк. к бд и схем
class Settings(BaseSettings):
    source_database_url: str = ""
    target_database_url: str = ""
    source_schema: str | None = None 
    target_schema: str | None = None

    model_config: ClassVar[SettingsConfigDict] = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }


settings = Settings()
