from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.services.manga_translation import (
    GeminiTranslationError,
    PageTranslation,
)
from app.services.translated_pdf import ResultBuildError
from app.tasks import translation as translation_module
from app.tasks.translation import (
    defer_translation_retry,
    fail_queued_translation_job,
    record_translation_progress,
    translate_job,
)


class FakeTranslator:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def translate_page(self, page_path: Path) -> PageTranslation:
        self.pages.append(page_path.name)
        return PageTranslation(regions=[])


class FailingTranslator:
    def __init__(
        self,
        fail_on_page: str,
        *,
        http_status: int | None = None,
        retryable: bool = False,
        retry_after_seconds: float | None = None,
    ) -> None:
        self.fail_on_page = fail_on_page
        self.http_status = http_status
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.pages: list[str] = []

    def translate_page(self, page_path: Path) -> PageTranslation:
        self.pages.append(page_path.name)
        if page_path.name == self.fail_on_page:
            raise GeminiTranslationError(
                "Gemini request failed.",
                http_status=self.http_status,
                retryable=self.retryable,
                retry_after_seconds=self.retry_after_seconds,
            )
        return PageTranslation(regions=[])


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def add_translation_job(session_factory, storage_root: Path, page_count: int = 2) -> str:
    job_id = str(uuid4())
    previews = storage_root / "previews" / job_id
    previews.mkdir(parents=True)
    for page_number in range(1, page_count + 1):
        Image.new("RGB", (120, 160), "white").save(
            previews / f"page-{page_number:04d}.png",
            format="PNG",
        )

    with session_factory() as session:
        session.add(
            TranslationJob(
                id=job_id,
                owner_username="owner",
                original_filename="chapter.pdf",
                stored_filename=f"{job_id}.pdf",
                size_bytes=1_024,
                page_count=page_count,
                status=JobStatus.TRANSLATION_QUEUED,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    return job_id


def test_translate_job_builds_pdf_and_marks_job_completed(tmp_path: Path) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path)
    translator = FakeTranslator()

    result = translate_job(job_id, session_factory, settings, translator)

    assert result == JobStatus.COMPLETED
    assert translator.pages == ["page-0001.png", "page-0002.png"]
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.status == JobStatus.COMPLETED
        assert job.translation_started_at is not None
        assert job.completed_at is not None
        assert job.failure_code is None
        assert job.result_filename == f"{job_id}.pdf"
        assert job.translated_page_count == 2
    result_pdf = tmp_path / "results" / f"{job_id}.pdf"
    assert result_pdf.is_file()
    assert len(PdfReader(result_pdf).pages) == 2
    engine.dispose()


def test_translate_job_marks_missing_preview_as_failed(tmp_path: Path) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=1)
    (tmp_path / "previews" / job_id / "page-0001.png").unlink()

    result = translate_job(job_id, session_factory, settings, FakeTranslator())

    assert result == JobStatus.FAILED
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.failure_code == "PREVIEW_NOT_FOUND"
        assert job.translated_page_count == 0
    engine.dispose()


def test_translate_job_resumes_from_first_unfinished_checkpoint(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=10)
    first_translator = FailingTranslator(
        "page-0008.png",
        http_status=429,
    )

    first_result = translate_job(
        job_id,
        session_factory,
        settings,
        first_translator,
    )

    assert first_result == JobStatus.TRANSLATION_RETRY_WAIT
    assert first_translator.pages == [
        f"page-{page_number:04d}.png" for page_number in range(1, 9)
    ]
    checkpoint_pages = (
        tmp_path / "temporary" / f"{job_id}.translation" / "pages"
    )
    assert sorted(path.name for path in checkpoint_pages.glob("*.png")) == [
        f"page-{page_number:04d}.png" for page_number in range(1, 8)
    ]
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.status == JobStatus.TRANSLATION_RETRY_WAIT
        assert job.failure_code is None
        assert job.translated_page_count == 7
        assert job.checkpoint_updated_at is not None
        assert job.translation_retry_attempt == 1
        assert job.translation_wait_reason == "rate_limited"
        assert job.translation_next_retry_at is not None
        job.status = JobStatus.TRANSLATION_QUEUED
        job.translation_next_retry_at = None
        job.translation_wait_reason = None
        session.commit()

    resume_translator = FakeTranslator()
    resumed_result = translate_job(
        job_id,
        session_factory,
        settings,
        resume_translator,
    )

    assert resumed_result == JobStatus.COMPLETED
    assert resume_translator.pages == [
        "page-0008.png",
        "page-0009.png",
        "page-0010.png",
    ]
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.translated_page_count == 10
        assert job.checkpoint_updated_at is None
    assert not checkpoint_pages.parent.exists()
    assert len(PdfReader(tmp_path / "results" / f"{job_id}.pdf").pages) == 10
    engine.dispose()


def test_deferred_retry_uses_latest_error_schedule_and_global_attempt(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=1)
    reference = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)

    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        job.status = JobStatus.TRANSLATING
        session.commit()

    assert defer_translation_retry(
        job_id,
        session_factory,
        settings,
        GeminiTranslationError(
            "unavailable",
            http_status=503,
            retryable=True,
        ),
        now=reference,
        jitter=lambda _start, _end: 0,
    )
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.translation_retry_attempt == 1
        assert job.translation_next_retry_at.replace(
            tzinfo=timezone.utc
        ) == reference + timedelta(seconds=60)
        job.status = JobStatus.TRANSLATING
        session.commit()

    assert defer_translation_retry(
        job_id,
        session_factory,
        settings,
        GeminiTranslationError(
            "limited",
            http_status=429,
            retryable=True,
        ),
        now=reference,
        jitter=lambda _start, _end: 0,
    )
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.translation_retry_attempt == 2
        assert job.translation_wait_reason == "rate_limited"
        assert job.translation_next_retry_at.replace(
            tzinfo=timezone.utc
        ) == reference + timedelta(seconds=900)
        job.status = JobStatus.TRANSLATING
        session.commit()

    assert defer_translation_retry(
        job_id,
        session_factory,
        settings,
        GeminiTranslationError(
            "unavailable",
            http_status=503,
            retryable=True,
        ),
        now=reference,
        jitter=lambda _start, _end: 0,
    )
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.translation_retry_attempt == 3
        assert job.translation_wait_reason == "service_unavailable"
        assert job.translation_next_retry_at.replace(
            tzinfo=timezone.utc
        ) == reference + timedelta(seconds=900)
        job.status = JobStatus.TRANSLATING
        session.commit()

    assert not defer_translation_retry(
        job_id,
        session_factory,
        settings,
        GeminiTranslationError(
            "limited",
            http_status=429,
            retryable=True,
        ),
        now=reference,
        jitter=lambda _start, _end: 0,
    )
    engine.dispose()


def test_deferred_retry_honors_provider_delay_cap_and_positive_jitter(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=1)
    reference = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        job.status = JobStatus.TRANSLATING
        session.commit()

    assert defer_translation_retry(
        job_id,
        session_factory,
        settings,
        GeminiTranslationError(
            "limited",
            http_status=429,
            retryable=True,
            retry_after_seconds=172_800,
        ),
        now=reference,
        jitter=lambda _start, end: end,
    )

    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.translation_next_retry_at.replace(
            tzinfo=timezone.utc
        ) == reference + timedelta(seconds=86_460)
    engine.dispose()


@pytest.mark.parametrize(
    ("http_status", "retryable", "failure_code"),
    [
        (429, True, "AI_RATE_LIMITED"),
        (503, True, "AI_SERVICE_UNAVAILABLE"),
    ],
)
def test_translate_job_marks_transient_failure_after_deferred_retries_exhausted(
    tmp_path: Path,
    http_status: int,
    retryable: bool,
    failure_code: str,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=1)
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        job.translation_retry_attempt = 3
        session.commit()

    result = translate_job(
        job_id,
        session_factory,
        settings,
        FailingTranslator(
            "page-0001.png",
            http_status=http_status,
            retryable=retryable,
        ),
    )

    assert result == JobStatus.FAILED
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.failure_code == failure_code
        assert job.translation_retry_attempt == 3
        assert job.translation_next_retry_at is None
    engine.dispose()


def test_successful_page_resets_deferred_retry_attempt(tmp_path: Path) -> None:
    engine, session_factory = make_session_factory()
    job_id = add_translation_job(session_factory, tmp_path, page_count=1)
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        job.status = JobStatus.TRANSLATING
        job.translation_retry_attempt = 2
        job.translation_next_retry_at = datetime.now(timezone.utc)
        job.translation_wait_reason = "service_unavailable"
        session.commit()

    assert record_translation_progress(job_id, session_factory, 1)
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.translation_retry_attempt == 0
        assert job.translation_next_retry_at is None
        assert job.translation_wait_reason is None
        assert job.translation_heartbeat_at is not None
    engine.dispose()


def test_translate_job_recovers_checkpoint_written_before_database_progress(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=3)
    checkpoint_pages = (
        tmp_path / "temporary" / f"{job_id}.translation" / "pages"
    )
    checkpoint_pages.mkdir(parents=True)
    Image.new("RGB", (120, 160), "white").save(
        checkpoint_pages / "page-0001.png",
        format="PNG",
    )
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        job.status = JobStatus.TRANSLATING
        job.translation_started_at = datetime.now(timezone.utc)
        session.commit()
    translator = FakeTranslator()

    result = translate_job(job_id, session_factory, settings, translator)

    assert result == JobStatus.COMPLETED
    assert translator.pages == ["page-0002.png", "page-0003.png"]
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.translated_page_count == 3
    engine.dispose()


def test_translate_job_restarts_at_first_corrupt_checkpoint(tmp_path: Path) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=3)
    checkpoint_pages = (
        tmp_path / "temporary" / f"{job_id}.translation" / "pages"
    )
    checkpoint_pages.mkdir(parents=True)
    Image.new("RGB", (120, 160), "white").save(
        checkpoint_pages / "page-0001.png",
        format="PNG",
    )
    (checkpoint_pages / "page-0002.png").write_bytes(b"not-a-png")
    Image.new("RGB", (120, 160), "white").save(
        checkpoint_pages / "page-0003.png",
        format="PNG",
    )
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        job.translated_page_count = 3
        job.checkpoint_updated_at = datetime.now(timezone.utc)
        session.commit()
    translator = FakeTranslator()

    result = translate_job(job_id, session_factory, settings, translator)

    assert result == JobStatus.COMPLETED
    assert translator.pages == ["page-0002.png", "page-0003.png"]
    engine.dispose()


def test_translate_job_rebuilds_pdf_without_retranslating_checkpoint_pages(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    job_id = add_translation_job(session_factory, tmp_path, page_count=2)
    real_build_result_pdf = translation_module.build_result_pdf

    def fail_result_build(_page_paths, _destination) -> None:
        raise ResultBuildError("forced result failure")

    monkeypatch.setattr(
        translation_module,
        "build_result_pdf",
        fail_result_build,
    )
    first_translator = FakeTranslator()

    first_result = translate_job(
        job_id,
        session_factory,
        settings,
        first_translator,
    )

    assert first_result == JobStatus.FAILED
    assert first_translator.pages == ["page-0001.png", "page-0002.png"]
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.failure_code == "RESULT_BUILD_FAILED"
        assert job.translated_page_count == 2
        job.status = JobStatus.TRANSLATION_QUEUED
        job.failure_code = None
        session.commit()

    monkeypatch.setattr(
        translation_module,
        "build_result_pdf",
        real_build_result_pdf,
    )
    resume_translator = FakeTranslator()
    resumed_result = translate_job(
        job_id,
        session_factory,
        settings,
        resume_translator,
    )

    assert resumed_result == JobStatus.COMPLETED
    assert resume_translator.pages == []
    assert len(PdfReader(tmp_path / "results" / f"{job_id}.pdf").pages) == 2
    engine.dispose()


def test_translate_job_discards_checkpoint_older_than_retention(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(
        storage_root=tmp_path,
        translation_checkpoint_retention_days=7,
    )
    job_id = add_translation_job(session_factory, tmp_path, page_count=2)
    checkpoint_pages = (
        tmp_path / "temporary" / f"{job_id}.translation" / "pages"
    )
    checkpoint_pages.mkdir(parents=True)
    Image.new("RGB", (120, 160), "white").save(
        checkpoint_pages / "page-0001.png",
        format="PNG",
    )
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        job.translated_page_count = 1
        job.checkpoint_updated_at = datetime.now(timezone.utc) - timedelta(days=8)
        session.commit()
    translator = FakeTranslator()

    result = translate_job(job_id, session_factory, settings, translator)

    assert result == JobStatus.COMPLETED
    assert translator.pages == ["page-0001.png", "page-0002.png"]
    engine.dispose()


def test_fail_queued_translation_job_records_configuration_failure(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    job_id = add_translation_job(session_factory, tmp_path, page_count=1)

    result = fail_queued_translation_job(
        job_id,
        session_factory,
        "AI_NOT_CONFIGURED",
    )

    assert result == JobStatus.FAILED
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.failure_code == "AI_NOT_CONFIGURED"
        assert job.translated_page_count == 0
    engine.dispose()


def test_translate_job_task_configures_gemini_retry_and_pacing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    settings = Settings(
        storage_root=tmp_path,
        gemini_api_key="test-key",
        gemini_min_request_interval_seconds=18,
        gemini_max_retries=4,
        gemini_retry_base_delay_seconds=3,
        gemini_retry_max_delay_seconds=45,
        gemini_inline_retry_max_delay_seconds=11,
    )
    captured: dict[str, object] = {}

    class FakeGeminiPageTranslator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    def fake_translate_job(job_id, session_factory, configured_settings, translator):
        captured.update(
            job_id=job_id,
            session_factory=session_factory,
            settings=configured_settings,
            translator=translator,
        )
        return JobStatus.COMPLETED

    monkeypatch.setattr(translation_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        translation_module,
        "GeminiPageTranslator",
        FakeGeminiPageTranslator,
    )
    monkeypatch.setattr(translation_module, "translate_job", fake_translate_job)

    result = translation_module.translate_job_task(str(uuid4()))

    assert result == JobStatus.COMPLETED
    assert captured["min_request_interval_seconds"] == 18
    assert captured["max_retries"] == 4
    assert captured["retry_base_delay_seconds"] == 3
    assert captured["retry_max_delay_seconds"] == 45
    assert captured["inline_retry_max_delay_seconds"] == 11
