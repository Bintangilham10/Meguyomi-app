from functools import lru_cache
from pathlib import Path
from typing import Annotated

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


RetryDelaySeconds = Annotated[int, Field(ge=1, le=86_400)]


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
    preview_render_scale: float = Field(default=2.0, ge=0.5, le=4.0)
    max_preview_pixels: int = 25_000_000
    max_preview_bytes: int = 512 * 1024 * 1024
    gemini_api_key: str = ""
    gemini_model: str = Field(
        default="gemini-3.5-flash",
        pattern=r"^[A-Za-z0-9._-]+$",
    )
    gemini_timeout_seconds: float = Field(default=90.0, ge=5.0, le=300.0)
    gemini_max_image_bytes: int = Field(
        default=13 * 1024 * 1024,
        ge=1024,
        le=14 * 1024 * 1024,
    )
    gemini_max_response_bytes: int = Field(
        default=2 * 1024 * 1024,
        ge=1024,
        le=10 * 1024 * 1024,
    )
    gemini_max_output_tokens: int = Field(default=8_192, ge=256, le=65_536)
    gemini_min_request_interval_seconds: float = Field(
        default=15.0,
        ge=0.0,
        le=300.0,
    )
    gemini_max_retries: int = Field(default=1, ge=0, le=10)
    gemini_retry_base_delay_seconds: float = Field(
        default=5.0,
        ge=0.1,
        le=60.0,
    )
    gemini_retry_max_delay_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
    )
    gemini_inline_retry_max_delay_seconds: float = Field(
        default=15.0,
        ge=0.1,
        le=300.0,
    )
    gemini_service_retry_delays_seconds: tuple[
        RetryDelaySeconds,
        RetryDelaySeconds,
        RetryDelaySeconds,
    ] = (
        60,
        300,
        900,
    )
    gemini_rate_limit_retry_delays_seconds: tuple[
        RetryDelaySeconds,
        RetryDelaySeconds,
        RetryDelaySeconds,
    ] = (
        60,
        900,
        3_600,
    )
    gemini_retry_hint_max_seconds: int = Field(
        default=86_400,
        ge=60,
        le=604_800,
    )
    gemini_deferred_retry_jitter_ratio: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
    )
    gemini_deferred_retry_jitter_max_seconds: float = Field(
        default=60.0,
        ge=0.0,
        le=600.0,
    )
    translation_heartbeat_timeout_seconds: int = Field(
        default=300,
        ge=60,
        le=3_600,
    )
    translation_queue_recovery_delay_seconds: int = Field(
        default=60,
        ge=1,
        le=3_600,
    )
    translation_checkpoint_retention_days: int = Field(
        default=7,
        ge=1,
        le=365,
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
