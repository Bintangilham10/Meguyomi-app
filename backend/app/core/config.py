from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://meguyomi:change-me@localhost:5432/meguyomi"
    )
    redis_url: str = "redis://localhost:6379/0"
    admin_username: str = "admin"
    admin_password_hash: str = ""
    session_secret: str = "development-only-session-secret-change-me"
    session_max_age_seconds: int = 86_400
    login_max_failures: int = 5
    login_window_seconds: int = 60
    storage_root: Path = Path("../storage")
    max_upload_bytes: int = 50 * 1024 * 1024
    max_pdf_pages: int = 100
    upload_chunk_bytes: int = 1024 * 1024

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
