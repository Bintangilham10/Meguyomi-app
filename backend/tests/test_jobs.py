from io import BytesIO
from pathlib import Path
from collections.abc import Iterator
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.session import get_db
from app.main import app
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob


TEST_PASSWORD_HASH = (
    "$argon2id$v=19$m=65536,t=3,p=4$JJsgtT5z5+neM/k5hS1+jg$"
    "CFAKkq/ZOtKk/e1QiFm/KkEPBxYjw7x+6Sc2RJQsAxw"
)


def make_pdf(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=600, height=800)
    writer.write(output)
    return output.getvalue()


def make_encrypted_pdf() -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=600, height=800)
    writer.encrypt("secret")
    writer.write(output)
    return output.getvalue()


def update_job(job_id: str, **values: object) -> None:
    dependency = app.dependency_overrides[get_db]
    session_iterator = dependency()
    session = next(session_iterator)
    try:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        for field, value in values.items():
            setattr(job, field, value)
        session.commit()
    finally:
        session_iterator.close()


@pytest.fixture
def authenticated_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> TestClient:
    monkeypatch.setenv("ADMIN_USERNAME", "owner")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", TEST_PASSWORD_HASH)
    monkeypatch.setenv("STORAGE_ROOT", str(tmp_path))
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.api.jobs.dispatch_preparation_job",
        lambda _job_id: None,
        raising=False,
    )

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    test_session = sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.create_all(engine)

    def override_get_db() -> Iterator[Session]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as client:
        login_response = client.post(
            "/auth/login",
            json={"username": "owner", "password": "test-password"},
        )
        assert login_response.status_code == 200
        yield client

    app.dependency_overrides.clear()
    Base.metadata.drop_all(engine)
    engine.dispose()
    get_settings.cache_clear()


def test_upload_requires_authenticated_session() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/jobs",
            files={"file": ("chapter.pdf", make_pdf(), "application/pdf")},
        )

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "NOT_AUTHENTICATED",
            "message": "Sesi login tidak valid.",
        }
    }


def test_upload_accepts_valid_pdf(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    pdf = make_pdf(page_count=2)
    dispatched_job_ids: list[str] = []
    monkeypatch.setattr(
        "app.api.jobs.dispatch_preparation_job",
        dispatched_job_ids.append,
        raising=False,
    )

    response = authenticated_client.post(
        "/jobs",
        files={"file": ("chapter-01.pdf", pdf, "application/pdf")},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["originalFilename"] == "chapter-01.pdf"
    assert body["sizeBytes"] == len(pdf)
    assert body["pageCount"] == 2
    assert body["status"] == "QUEUED"
    assert body["id"]
    assert body["createdAt"]
    assert dispatched_job_ids == [body["id"]]
    stored_files = list((tmp_path / "originals").glob("*.pdf"))
    assert len(stored_files) == 1
    assert stored_files[0].name != "chapter-01.pdf"


@pytest.mark.parametrize(
    ("filename", "content", "content_type", "expected_code"),
    [
        ("fake.pdf", b"not a pdf", "application/pdf", "INVALID_PDF"),
        ("chapter.txt", make_pdf(), "text/plain", "INVALID_FILE_TYPE"),
        ("locked.pdf", make_encrypted_pdf(), "application/pdf", "ENCRYPTED_PDF"),
        ("long.pdf", make_pdf(page_count=101), "application/pdf", "TOO_MANY_PAGES"),
    ],
)
def test_upload_rejects_invalid_pdf(
    authenticated_client: TestClient,
    tmp_path: Path,
    filename: str,
    content: bytes,
    content_type: str,
    expected_code: str,
) -> None:
    response = authenticated_client.post(
        "/jobs",
        files={"file": (filename, content, content_type)},
    )

    assert response.status_code in {400, 415, 422}
    assert response.json()["error"]["code"] == expected_code
    assert list((tmp_path / "originals").glob("*")) == []
    assert list((tmp_path / "temporary").glob("*")) == []


def test_upload_marks_job_failed_when_queue_is_unavailable(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_dispatch(_job_id: str) -> None:
        raise RuntimeError("broker connection failed")

    monkeypatch.setattr(
        "app.api.jobs.dispatch_preparation_job",
        fail_dispatch,
        raising=False,
    )

    response = authenticated_client.post(
        "/jobs",
        files={"file": ("chapter.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 201
    assert response.json()["status"] == "FAILED"
    assert response.json()["failureCode"] == "QUEUE_UNAVAILABLE"


def test_upload_rejects_file_over_size_limit(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "128")
    get_settings.cache_clear()

    response = authenticated_client.post(
        "/jobs",
        files={"file": ("large.pdf", make_pdf(), "application/pdf")},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert list((tmp_path / "originals").glob("*")) == []
    assert list((tmp_path / "temporary").glob("*")) == []


def test_list_returns_uploaded_jobs(authenticated_client: TestClient) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("history.pdf", make_pdf(), "application/pdf")},
    )
    assert upload_response.status_code == 201

    list_response = authenticated_client.get("/jobs")

    assert list_response.status_code == 200
    body = list_response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["id"] == upload_response.json()["id"]
    assert body["data"][0]["originalFilename"] == "history.pdf"


def test_start_translation_claims_ready_job_once(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("chapter.pdf", make_pdf(), "application/pdf")},
    )
    job_id = upload_response.json()["id"]
    update_job(job_id, status=JobStatus.READY_FOR_TRANSLATION)
    dispatched_job_ids: list[str] = []
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.api.jobs.dispatch_translation_job",
        dispatched_job_ids.append,
        raising=False,
    )

    response = authenticated_client.post(f"/jobs/{job_id}/translation")

    assert response.status_code == 202
    assert response.json()["status"] == "TRANSLATION_QUEUED"
    assert dispatched_job_ids == [job_id]

    duplicate_response = authenticated_client.post(f"/jobs/{job_id}/translation")
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["error"]["code"] == "JOB_NOT_READY"
    get_settings.cache_clear()


def test_start_translation_requires_ai_configuration(
    authenticated_client: TestClient,
) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("chapter.pdf", make_pdf(), "application/pdf")},
    )
    job_id = upload_response.json()["id"]
    update_job(job_id, status=JobStatus.READY_FOR_TRANSLATION)

    response = authenticated_client.post(f"/jobs/{job_id}/translation")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "AI_NOT_CONFIGURED"


@pytest.mark.parametrize(
    "failure_code",
    ["AI_TRANSLATION_FAILED", "AI_RATE_LIMITED"],
)
def test_start_translation_retries_recoverable_ai_failure(
    authenticated_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    failure_code: str,
) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("chapter.pdf", make_pdf(), "application/pdf")},
    )
    job_id = upload_response.json()["id"]
    update_job(
        job_id,
        status=JobStatus.FAILED,
        prepared_at=datetime.now(timezone.utc),
        failure_code=failure_code,
        translated_page_count=1,
    )
    dispatched_job_ids: list[str] = []
    monkeypatch.setenv("GEMINI_API_KEY", "test-gemini-key")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "app.api.jobs.dispatch_translation_job",
        dispatched_job_ids.append,
        raising=False,
    )

    response = authenticated_client.post(f"/jobs/{job_id}/translation")

    assert response.status_code == 202
    assert response.json()["status"] == "TRANSLATION_QUEUED"
    assert response.json()["translatedPageCount"] == 1
    assert response.json()["canRetryTranslation"] is False
    assert dispatched_job_ids == [job_id]
    get_settings.cache_clear()


def test_download_returns_completed_job_result(
    authenticated_client: TestClient,
    tmp_path: Path,
) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("chapter.pdf", make_pdf(), "application/pdf")},
    )
    job_id = upload_response.json()["id"]
    result_filename = f"{job_id}.pdf"
    results = tmp_path / "results"
    results.mkdir(parents=True)
    result_bytes = make_pdf(page_count=2)
    (results / result_filename).write_bytes(result_bytes)
    update_job(
        job_id,
        status=JobStatus.COMPLETED,
        result_filename=result_filename,
    )

    response = authenticated_client.get(f"/jobs/{job_id}/result")

    assert response.status_code == 200
    assert response.content == result_bytes
    assert response.headers["content-type"] == "application/pdf"
    assert "chapter-indonesia.pdf" in response.headers["content-disposition"]
    assert response.headers["cache-control"] == "private, no-store"


def test_delete_terminal_job_removes_record_and_all_artifacts(
    authenticated_client: TestClient,
    tmp_path: Path,
) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("chapter.pdf", make_pdf(), "application/pdf")},
    )
    job_id = upload_response.json()["id"]
    preview_directory = tmp_path / "previews" / job_id
    preview_directory.mkdir(parents=True)
    (preview_directory / "page-0001.png").write_bytes(b"preview")
    checkpoint_directory = tmp_path / "temporary" / f"{job_id}.translation"
    checkpoint_directory.mkdir(parents=True)
    (checkpoint_directory / "page.part").write_bytes(b"checkpoint")
    result_path = tmp_path / "results" / f"{job_id}.pdf"
    result_path.parent.mkdir(parents=True)
    result_path.write_bytes(make_pdf())
    update_job(
        job_id,
        status=JobStatus.COMPLETED,
        result_filename=result_path.name,
    )

    response = authenticated_client.delete(f"/jobs/{job_id}")

    assert response.status_code == 204
    assert response.content == b""
    assert not (tmp_path / "originals" / f"{job_id}.pdf").exists()
    assert not preview_directory.exists()
    assert not checkpoint_directory.exists()
    assert not result_path.exists()
    assert authenticated_client.get("/jobs").json()["data"] == []


@pytest.mark.parametrize(
    "job_status",
    [
        JobStatus.QUEUED,
        JobStatus.PROCESSING,
        JobStatus.TRANSLATION_QUEUED,
        JobStatus.TRANSLATING,
    ],
)
def test_delete_rejects_active_job_without_removing_source(
    authenticated_client: TestClient,
    tmp_path: Path,
    job_status: str,
) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("active.pdf", make_pdf(), "application/pdf")},
    )
    job_id = upload_response.json()["id"]
    update_job(job_id, status=job_status)

    response = authenticated_client.delete(f"/jobs/{job_id}")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "JOB_ACTIVE"
    assert (tmp_path / "originals" / f"{job_id}.pdf").is_file()
    assert len(authenticated_client.get("/jobs").json()["data"]) == 1


def test_delete_hides_job_owned_by_another_user(
    authenticated_client: TestClient,
    tmp_path: Path,
) -> None:
    upload_response = authenticated_client.post(
        "/jobs",
        files={"file": ("private.pdf", make_pdf(), "application/pdf")},
    )
    job_id = upload_response.json()["id"]
    update_job(
        job_id,
        owner_username="another-owner",
        status=JobStatus.FAILED,
    )

    response = authenticated_client.delete(f"/jobs/{job_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "JOB_NOT_FOUND"
    assert (tmp_path / "originals" / f"{job_id}.pdf").is_file()
