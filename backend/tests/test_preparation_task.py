from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.tasks.preparation import prepare_translation_job


def make_pdf(page_count: int = 1) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    for _ in range(page_count):
        writer.add_blank_page(width=600, height=800)
    writer.write(output)
    return output.getvalue()


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def add_queued_job(session_factory, storage_root: Path, *, source_exists: bool) -> str:
    job_id = str(uuid4())
    stored_filename = f"{job_id}.pdf"
    if source_exists:
        originals = storage_root / "originals"
        originals.mkdir(parents=True)
        (originals / stored_filename).write_bytes(make_pdf(page_count=2))

    with session_factory() as session:
        session.add(
            TranslationJob(
                id=job_id,
                owner_username="owner",
                original_filename="chapter.pdf",
                stored_filename=stored_filename,
                size_bytes=1_024,
                page_count=2,
                status=JobStatus.QUEUED,
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()
    return job_id


def test_prepare_translation_job_renders_pages_and_marks_ready(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path, preview_render_scale=1.0)
    job_id = add_queued_job(session_factory, tmp_path, source_exists=True)

    result = prepare_translation_job(job_id, session_factory, settings)

    assert result == JobStatus.READY_FOR_TRANSLATION
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.status == JobStatus.READY_FOR_TRANSLATION
        assert job.started_at is not None
        assert job.prepared_at is not None
        assert job.failure_code is None
    assert sorted(path.name for path in (tmp_path / "previews" / job_id).iterdir()) == [
        "page-0001.png",
        "page-0002.png",
    ]
    assert prepare_translation_job(job_id, session_factory, settings) == (
        JobStatus.READY_FOR_TRANSLATION
    )
    engine.dispose()


def test_prepare_translation_job_replaces_stale_preview_directory(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path, preview_render_scale=1.0)
    job_id = add_queued_job(session_factory, tmp_path, source_exists=True)
    stale_destination = tmp_path / "previews" / job_id
    stale_destination.mkdir(parents=True)
    (stale_destination / "page-9999.png").write_bytes(b"stale preview")

    result = prepare_translation_job(job_id, session_factory, settings)

    assert result == JobStatus.READY_FOR_TRANSLATION
    assert sorted(path.name for path in stale_destination.iterdir()) == [
        "page-0001.png",
        "page-0002.png",
    ]
    engine.dispose()


def test_prepare_translation_job_marks_missing_source_as_failed(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path, preview_render_scale=1.0)
    job_id = add_queued_job(session_factory, tmp_path, source_exists=False)

    result = prepare_translation_job(job_id, session_factory, settings)

    assert result == JobStatus.FAILED
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.status == JobStatus.FAILED
        assert job.failure_code == "SOURCE_NOT_FOUND"
    engine.dispose()


def test_prepare_translation_job_rejects_invalid_job_id(tmp_path: Path) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path, preview_render_scale=1.0)

    result = prepare_translation_job("../../outside", session_factory, settings)

    assert result == "INVALID_JOB_ID"
    engine.dispose()
