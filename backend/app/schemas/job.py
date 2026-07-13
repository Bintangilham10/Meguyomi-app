from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


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
    status: Literal["QUEUED"]
    created_at: datetime


class JobListResponse(BaseModel):
    data: list[JobResponse]
