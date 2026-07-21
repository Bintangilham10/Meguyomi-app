from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.models.job_status import JobStatus


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
    translated_page_count: int = 0
    status: JobStatus
    created_at: datetime
    started_at: datetime | None = None
    prepared_at: datetime | None = None
    translation_started_at: datetime | None = None
    completed_at: datetime | None = None
    failure_code: str | None = None
    result_available: bool = False
    can_retry_translation: bool = False


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
