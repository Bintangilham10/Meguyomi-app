from datetime import datetime, timezone
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic.alias_generators import to_camel

from app.models.job_status import JobStatus
from app.core.languages import JobSourceLanguage


TranslationWaitReason = Literal[
    "rate_limited",
    "service_unavailable",
    "worker_recovery",
    "queue_unavailable",
]


class JobResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )

    id: UUID
    original_filename: str
    size_bytes: int
    page_count: int
    source_language: JobSourceLanguage = "ja"
    translated_page_count: int = 0
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    prepared_at: datetime | None = None
    translation_started_at: datetime | None = None
    translation_retry_attempt: int = 0
    translation_next_retry_at: datetime | None = None
    translation_wait_reason: TranslationWaitReason | None = None
    completed_at: datetime | None = None
    failure_code: str | None = None
    result_available: bool = False
    can_resume_translation: bool = False
    can_retry_translation: bool = False
    can_retry_preparation: bool = False

    @field_validator("translation_next_retry_at")
    @classmethod
    def normalize_retry_time_to_utc(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class PaginationResponse(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
    )

    page: int
    page_size: int
    total_items: int
    total_pages: int


class JobListResponse(BaseModel):
    data: list[JobResponse]
    pagination: PaginationResponse
