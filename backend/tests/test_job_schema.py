from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.schemas.job import JobResponse


@pytest.mark.parametrize(
    "job_status",
    [
        "QUEUED",
        "PROCESSING",
        "READY_FOR_TRANSLATION",
        "TRANSLATION_QUEUED",
        "TRANSLATING",
        "TRANSLATION_RETRY_WAIT",
        "TRANSLATION_STOPPING",
        "TRANSLATION_STOPPED",
        "COMPLETED",
        "FAILED",
    ],
)
def test_job_response_supports_translation_lifecycle(job_status: str) -> None:
    response = JobResponse.model_validate(
        {
            "id": uuid4(),
            "original_filename": "chapter.pdf",
            "size_bytes": 1_024,
            "page_count": 10,
            "translated_page_count": 3,
            "status": job_status,
            "created_at": datetime.now(timezone.utc),
            "started_at": None,
            "prepared_at": None,
            "translation_started_at": None,
            "translation_retry_attempt": (
                1 if job_status == "TRANSLATION_RETRY_WAIT" else 0
            ),
            "translation_next_retry_at": (
                datetime(2026, 7, 23, 12, 0)
                if job_status == "TRANSLATION_RETRY_WAIT"
                else None
            ),
            "translation_wait_reason": (
                "service_unavailable"
                if job_status == "TRANSLATION_RETRY_WAIT"
                else None
            ),
            "completed_at": None,
            "failure_code": None,
            "result_available": job_status == "COMPLETED",
            "can_resume_translation": job_status == "TRANSLATION_STOPPED",
        }
    )

    assert response.status == job_status
    assert response.translated_page_count == 3
    assert response.result_available is (job_status == "COMPLETED")
    assert response.can_resume_translation is (
        job_status == "TRANSLATION_STOPPED"
    )
    if job_status == "TRANSLATION_RETRY_WAIT":
        assert response.translation_next_retry_at is not None
        assert response.translation_next_retry_at.tzinfo == timezone.utc
