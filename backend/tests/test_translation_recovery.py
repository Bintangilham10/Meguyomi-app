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
from app.tasks.maintenance import recover_translation_jobs


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
    next_retry_at: datetime | None = None,
    heartbeat_at: datetime | None = None,
    started_at: datetime | None = None,
    retry_attempt: int = 0,
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
                page_count=1,
                status=status,
                created_at=datetime.now(timezone.utc),
                prepared_at=datetime.now(timezone.utc),
                translation_started_at=started_at,
                translation_retry_attempt=retry_attempt,
                translation_next_retry_at=next_retry_at,
                translation_heartbeat_at=heartbeat_at,
            )
        )
        session.commit()
    return job_id


def test_recovery_dispatches_due_job_and_recovers_stale_worker(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    due_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATION_RETRY_WAIT,
        next_retry_at=now - timedelta(seconds=1),
        retry_attempt=1,
    )
    future_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATION_RETRY_WAIT,
        next_retry_at=now + timedelta(minutes=10),
        retry_attempt=1,
    )
    stale_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATING,
        heartbeat_at=now - timedelta(minutes=6),
        started_at=now - timedelta(minutes=7),
        retry_attempt=2,
    )
    dispatched: list[str] = []

    counts = recover_translation_jobs(
        session_factory,
        settings,
        dispatch=dispatched.append,
        now=now,
        jitter=lambda _start, _end: 0,
    )

    assert counts == {
        "preparationRecovered": 0,
        "recovered": 1,
        "dispatched": 1,
        "dispatchFailed": 0,
    }
    assert dispatched == [due_id]
    with session_factory() as session:
        due = session.get(TranslationJob, due_id)
        future = session.get(TranslationJob, future_id)
        stale = session.get(TranslationJob, stale_id)
        assert due is not None
        assert future is not None
        assert stale is not None
        assert due.status == JobStatus.TRANSLATION_QUEUED
        assert due.translation_next_retry_at is None
        assert future.status == JobStatus.TRANSLATION_RETRY_WAIT
        assert stale.status == JobStatus.TRANSLATION_RETRY_WAIT
        assert stale.translation_wait_reason == "worker_recovery"
        assert stale.translation_retry_attempt == 2
        assert stale.translation_next_retry_at == now.replace(
            tzinfo=None
        ) + timedelta(seconds=60)
    engine.dispose()


def test_recovery_does_not_touch_fresh_or_normally_queued_jobs(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    fresh_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATING,
        heartbeat_at=now - timedelta(minutes=2),
        started_at=now - timedelta(minutes=20),
    )
    queued_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATION_QUEUED,
        started_at=now - timedelta(hours=2),
    )

    counts = recover_translation_jobs(
        session_factory,
        settings,
        dispatch=lambda _job_id: None,
        now=now,
        jitter=lambda _start, _end: 0,
    )

    assert counts == {
        "preparationRecovered": 0,
        "recovered": 0,
        "dispatched": 0,
        "dispatchFailed": 0,
    }
    with session_factory() as session:
        assert session.get(TranslationJob, fresh_id).status == JobStatus.TRANSLATING
        assert (
            session.get(TranslationJob, queued_id).status
            == JobStatus.TRANSLATION_QUEUED
        )
    engine.dispose()


def test_dispatch_failure_returns_job_to_future_wait_without_spending_attempt(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    job_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATION_RETRY_WAIT,
        next_retry_at=now,
        retry_attempt=2,
    )

    def fail_dispatch(_job_id: str) -> None:
        raise ConnectionError("redis unavailable")

    counts = recover_translation_jobs(
        session_factory,
        settings,
        dispatch=fail_dispatch,
        now=now,
        jitter=lambda _start, _end: 0,
    )

    assert counts == {
        "preparationRecovered": 0,
        "recovered": 0,
        "dispatched": 0,
        "dispatchFailed": 1,
    }
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        assert job is not None
        assert job.status == JobStatus.TRANSLATION_RETRY_WAIT
        assert job.translation_wait_reason == "queue_unavailable"
        assert job.translation_retry_attempt == 2
        assert job.translation_next_retry_at == now.replace(
            tzinfo=None
        ) + timedelta(seconds=60)
    engine.dispose()


def add_processing_job(session_factory, *, started_at: datetime) -> str:
    job_id = str(uuid4())
    with session_factory() as session:
        session.add(
            TranslationJob(
                id=job_id,
                owner_username="owner",
                original_filename="chapter.pdf",
                stored_filename=f"{job_id}.pdf",
                size_bytes=1_024,
                page_count=1,
                status=JobStatus.PROCESSING,
                created_at=datetime.now(timezone.utc),
                started_at=started_at,
            )
        )
        session.commit()
    return job_id


def test_recovery_fails_stalled_preparation_but_keeps_fresh_one(
    tmp_path: Path,
) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    stalled_id = add_processing_job(
        session_factory,
        started_at=now - timedelta(minutes=11),
    )
    fresh_id = add_processing_job(
        session_factory,
        started_at=now - timedelta(minutes=2),
    )

    counts = recover_translation_jobs(
        session_factory,
        settings,
        dispatch=lambda _job_id: None,
        now=now,
        jitter=lambda _start, _end: 0,
    )

    assert counts == {
        "preparationRecovered": 1,
        "recovered": 0,
        "dispatched": 0,
        "dispatchFailed": 0,
    }
    with session_factory() as session:
        stalled = session.get(TranslationJob, stalled_id)
        fresh = session.get(TranslationJob, fresh_id)
        assert stalled is not None
        assert fresh is not None
        assert stalled.status == JobStatus.FAILED
        assert stalled.failure_code == "PREPARATION_FAILED"
        assert stalled.can_retry_preparation is True
        assert fresh.status == JobStatus.PROCESSING
        assert fresh.failure_code is None
    engine.dispose()


def test_due_job_is_dispatched_only_once_across_scans(tmp_path: Path) -> None:
    engine, session_factory = make_session_factory()
    settings = Settings(storage_root=tmp_path)
    now = datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc)
    job_id = add_job(
        session_factory,
        status=JobStatus.TRANSLATION_RETRY_WAIT,
        next_retry_at=now,
    )
    dispatched: list[str] = []

    recover_translation_jobs(
        session_factory,
        settings,
        dispatch=dispatched.append,
        now=now,
        jitter=lambda _start, _end: 0,
    )
    recover_translation_jobs(
        session_factory,
        settings,
        dispatch=dispatched.append,
        now=now,
        jitter=lambda _start, _end: 0,
    )

    assert dispatched == [job_id]
    engine.dispose()
