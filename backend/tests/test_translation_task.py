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
from app.tasks.translation import fail_queued_translation_job, translate_job


class FakeTranslator:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def translate_page(self, page_path: Path) -> PageTranslation:
        self.pages.append(page_path.name)
        return PageTranslation(regions=[])


class FailingTranslator:
    def __init__(self, fail_on_page: str, *, http_status: int | None = None) -> None:
        self.fail_on_page = fail_on_page
        self.http_status = http_status
        self.pages: list[str] = []

    def translate_page(self, page_path: Path) -> PageTranslation:
        self.pages.append(page_path.name)
        if page_path.name == self.fail_on_page:
            raise GeminiTranslationError(
                "Gemini request failed.",
                http_status=self.http_status,
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

    assert first_result == JobStatus.FAILED
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
        assert job.status == JobStatus.FAILED
        assert job.failure_code == "AI_RATE_LIMITED"
        assert job.translated_page_count == 7
        assert job.checkpoint_updated_at is not None
        job.status = JobStatus.TRANSLATION_QUEUED
        job.failure_code = None
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
