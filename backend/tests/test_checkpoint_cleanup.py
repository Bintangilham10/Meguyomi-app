from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.db.base import Base
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.tasks.celery_app import celery_app
from app.tasks.maintenance import cleanup_translation_checkpoints


def make_session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def add_job(
    session_factory,
    *,
    status: str,
    checkpoint_updated_at: datetime | None,
    translated_page_count: int = 1,
) -> str:
    job_id = str(uuid4())
    with session_factory() as session:
        session.add(
            TranslationJob(
                id=job_id,
                owner_username="owner",
                original_filename="chapter.pdf",
                stored_filename=f"{job_id}.pdf",
                size_bytes=1_024,
                page_count=2,
                translated_page_count=translated_page_count,
                status=status,
                created_at=datetime.now(timezone.utc),
                prepared_at=datetime.now(timezone.utc),
                checkpoint_updated_at=checkpoint_updated_at,
            )
        )
        session.commit()
    return job_id


def make_checkpoint(storage_root: Path, job_id: str) -> Path:
    checkpoint = storage_root / "temporary" / f"{job_id}.translation"
    pages = checkpoint / "pages"
    pages.mkdir(parents=True)
    (pages / "page-0001.png").write_bytes(b"checkpoint")
    return checkpoint


def test_cleanup_removes_only_expired_failed_completed_and_orphaned_checkpoints(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    now = datetime(2026, 7, 19, 3, 0, tzinfo=timezone.utc)
    settings = Settings(
        storage_root=tmp_path,
        translation_checkpoint_retention_days=7,
    )
    expired_job_id = add_job(
        session_factory,
        status=JobStatus.FAILED,
        checkpoint_updated_at=now - timedelta(days=8),
    )
    young_job_id = add_job(
        session_factory,
        status=JobStatus.FAILED,
        checkpoint_updated_at=now - timedelta(days=6),
    )
    active_job_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATING,
        checkpoint_updated_at=now - timedelta(days=8),
    )
    completed_job_id = add_job(
        session_factory,
        status=JobStatus.COMPLETED,
        checkpoint_updated_at=None,
        translated_page_count=2,
    )
    orphaned_job_id = str(uuid4())
    checkpoints = {
        job_id: make_checkpoint(tmp_path, job_id)
        for job_id in (
            expired_job_id,
            young_job_id,
            active_job_id,
            completed_job_id,
            orphaned_job_id,
        )
    }
    unrelated_preview = tmp_path / "temporary" / "render.preview"
    unrelated_preview.mkdir(parents=True)
    live_records = tmp_path / "translations" / completed_job_id
    live_records.mkdir(parents=True)
    (live_records / "page-0001.json").write_text('{"regions": []}')
    orphaned_records = tmp_path / "translations" / str(uuid4())
    orphaned_records.mkdir(parents=True)
    (orphaned_records / "page-0001.json").write_text('{"regions": []}')

    result = cleanup_translation_checkpoints(
        session_factory,
        settings,
        now=now,
    )

    assert result == {
        "expired": 1,
        "completed": 1,
        "orphaned": 1,
        "orphanedRecords": 1,
    }
    assert not checkpoints[expired_job_id].exists()
    assert checkpoints[young_job_id].is_dir()
    assert checkpoints[active_job_id].is_dir()
    assert not checkpoints[completed_job_id].exists()
    assert not checkpoints[orphaned_job_id].exists()
    assert unrelated_preview.is_dir()
    assert live_records.is_dir()
    assert not orphaned_records.exists()
    with session_factory() as session:
        expired_job = session.get(TranslationJob, expired_job_id)
        assert expired_job is not None
        assert expired_job.translated_page_count == 0
        assert expired_job.checkpoint_updated_at is None
        young_job = session.get(TranslationJob, young_job_id)
        assert young_job is not None
        assert young_job.translated_page_count == 1
    engine.dispose()


def test_celery_beat_schedules_daily_checkpoint_cleanup() -> None:
    schedule = celery_app.conf.beat_schedule["cleanup-translation-checkpoints"]

    assert schedule["task"] == "meguyomi.cleanup_translation_checkpoints"
    assert str(schedule["schedule"]) == "<crontab: 0 3 * * * (m/h/dM/MY/d)>"
