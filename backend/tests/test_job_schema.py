from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.job import JobResponse


@pytest.mark.parametrize(
    "job_status",
    ["QUEUED", "PROCESSING", "READY_FOR_TRANSLATION", "FAILED"],
)
def test_job_response_supports_preparation_lifecycle(job_status: str) -> None:
    response = JobResponse.model_validate(
        {
            "id": uuid4(),
            "original_filename": "chapter.pdf",
            "size_bytes": 1_024,
            "page_count": 10,
            "status": job_status,
            "created_at": datetime.now(timezone.utc),
            "started_at": None,
            "prepared_at": None,
            "failure_code": None,
        }
    )

    assert response.status == job_status
