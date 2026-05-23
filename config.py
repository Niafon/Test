from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    source_database_url: str
    target_database_url: str

    model_config: SettingsConfigDict = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
    }

settings = Settings()
