from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from PIL import Image
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.services.manga_translation import PageTranslation
from app.tasks.translation import translate_job


class FakeTranslator:
    def __init__(self) -> None:
        self.pages: list[str] = []

    def translate_page(self, page_path: Path) -> PageTranslation:
        self.pages.append(page_path.name)
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
    engine.dispose()
