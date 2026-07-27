import json
import logging
import random
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree

from sqlalchemy import and_, or_, select, update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.tasks.celery_app import celery_app
from app.tasks.preparation import normalize_job_id
from app.tasks.translation import checkpoint_is_expired, resolve_checkpoint_directory
from app.tasks.translation import dispatch_translation_job


SessionFactory = Callable[[], Session]
Dispatcher = Callable[[str], None]
RetryJitter = Callable[[float, float], float]
logger = logging.getLogger(__name__)


def _remove_checkpoint(checkpoint: Path, job_id: str) -> bool:
    try:
        if checkpoint.exists():
            rmtree(checkpoint)
    except OSError:
        logger.exception(
            json.dumps(
                {
                    "event": "translation_checkpoint_cleanup_failed",
                    "jobId": job_id,
                }
            )
        )
        return False
    return True


def cleanup_translation_checkpoints(
    session_factory: SessionFactory,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> dict[str, int]:
    reference_time = now or datetime.now(timezone.utc)
    counts = {"expired": 0, "completed": 0, "orphaned": 0, "orphanedRecords": 0}
    temporary_root = (settings.storage_root / "temporary").resolve()
    temporary_root.mkdir(parents=True, exist_ok=True)
    translations_root = (settings.storage_root / "translations").resolve()

    with session_factory() as session:
        failed_jobs = session.scalars(
            select(TranslationJob)
            .where(
                TranslationJob.status == JobStatus.FAILED,
                TranslationJob.checkpoint_updated_at.is_not(None),
            )
            .with_for_update()
        ).all()
        for job in failed_jobs:
            if not checkpoint_is_expired(
                job.checkpoint_updated_at,
                settings.translation_checkpoint_retention_days,
                now=reference_time,
            ):
                continue
            checkpoint = resolve_checkpoint_directory(settings, job.id)
            if not _remove_checkpoint(checkpoint, job.id):
                continue
            job.translated_page_count = 0
            job.checkpoint_updated_at = None
            counts["expired"] += 1

        completed_jobs = session.scalars(
            select(TranslationJob)
            .where(TranslationJob.status == JobStatus.COMPLETED)
            .with_for_update()
        ).all()
        for job in completed_jobs:
            checkpoint = resolve_checkpoint_directory(settings, job.id)
            if not checkpoint.exists():
                continue
            if _remove_checkpoint(checkpoint, job.id):
                counts["completed"] += 1
        session.commit()

        for checkpoint in temporary_root.glob("*.translation"):
            if not checkpoint.is_dir():
                continue
            raw_job_id = checkpoint.name.removesuffix(".translation")
            job_id = normalize_job_id(raw_job_id)
            if job_id is None:
                continue
            if session.get(TranslationJob, job_id) is not None:
                continue
            if _remove_checkpoint(checkpoint, job_id):
                counts["orphaned"] += 1

        if translations_root.is_dir():
            for records in translations_root.iterdir():
                if not records.is_dir():
                    continue
                job_id = normalize_job_id(records.name)
                if job_id is None:
                    continue
                if session.get(TranslationJob, job_id) is not None:
                    continue
                if _remove_checkpoint(records, job_id):
                    counts["orphanedRecords"] += 1

    logger.info(
        json.dumps(
            {
                "event": "translation_checkpoint_cleanup_completed",
                "expiredJobs": counts["expired"],
                "completedJobs": counts["completed"],
                "orphanedCheckpoints": counts["orphaned"],
                "orphanedRecords": counts["orphanedRecords"],
            }
        )
    )
    return counts


@celery_app.task(name="meguyomi.cleanup_translation_checkpoints")
def cleanup_translation_checkpoints_task() -> dict[str, int]:
    return cleanup_translation_checkpoints(
        SessionLocal,
        get_settings(),
    )


def _queue_recovery_delay(
    settings: Settings,
    jitter: RetryJitter,
) -> float:
    base_delay = float(settings.translation_queue_recovery_delay_seconds)
    jitter_limit = min(
        settings.gemini_deferred_retry_jitter_max_seconds,
        base_delay * settings.gemini_deferred_retry_jitter_ratio,
    )
    jitter_seconds = min(
        jitter_limit,
        max(0.0, jitter(0.0, jitter_limit)),
    )
    return base_delay + jitter_seconds


def recover_translation_jobs(
    session_factory: SessionFactory,
    settings: Settings,
    *,
    dispatch: Dispatcher = dispatch_translation_job,
    now: datetime | None = None,
    jitter: RetryJitter = random.uniform,
) -> dict[str, int]:
    reference_time = now or datetime.now(timezone.utc)
    stale_before = reference_time - timedelta(
        seconds=settings.translation_heartbeat_timeout_seconds
    )
    preparation_stale_before = reference_time - timedelta(
        seconds=settings.preparation_timeout_seconds
    )
    counts = {
        "preparationRecovered": 0,
        "recovered": 0,
        "dispatched": 0,
        "dispatchFailed": 0,
    }

    with session_factory() as session:
        stalled_preparations = session.scalars(
            select(TranslationJob)
            .where(
                TranslationJob.status == JobStatus.PROCESSING,
                TranslationJob.started_at.is_not(None),
                TranslationJob.started_at <= preparation_stale_before,
            )
            .order_by(TranslationJob.started_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        ).all()
        for job in stalled_preparations:
            job.status = JobStatus.FAILED
            job.failure_code = "PREPARATION_FAILED"
            counts["preparationRecovered"] += 1
        session.commit()

    with session_factory() as session:
        stale_jobs = session.scalars(
            select(TranslationJob)
            .where(
                TranslationJob.status == JobStatus.TRANSLATING,
                or_(
                    TranslationJob.translation_heartbeat_at <= stale_before,
                    and_(
                        TranslationJob.translation_heartbeat_at.is_(None),
                        TranslationJob.translation_started_at.is_not(None),
                        TranslationJob.translation_started_at <= stale_before,
                    ),
                ),
            )
            .order_by(TranslationJob.translation_heartbeat_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        ).all()
        for job in stale_jobs:
            delay = _queue_recovery_delay(settings, jitter)
            job.status = JobStatus.TRANSLATION_RETRY_WAIT
            job.translation_next_retry_at = reference_time + timedelta(
                seconds=delay
            )
            job.translation_wait_reason = "worker_recovery"
            job.translation_heartbeat_at = None
            job.failure_code = None
            counts["recovered"] += 1
        session.commit()

    with session_factory() as session:
        due_jobs = session.scalars(
            select(TranslationJob)
            .where(
                TranslationJob.status == JobStatus.TRANSLATION_RETRY_WAIT,
                TranslationJob.translation_next_retry_at.is_not(None),
                TranslationJob.translation_next_retry_at <= reference_time,
            )
            .order_by(TranslationJob.translation_next_retry_at.asc())
            .limit(100)
            .with_for_update(skip_locked=True)
        ).all()
        due_job_ids = [job.id for job in due_jobs]
        for job in due_jobs:
            job.status = JobStatus.TRANSLATION_QUEUED
            job.translation_next_retry_at = None
            job.translation_wait_reason = None
            job.translation_heartbeat_at = None
        session.commit()

    for job_id in due_job_ids:
        try:
            dispatch(job_id)
        except Exception:
            logger.exception(
                json.dumps(
                    {
                        "event": "translation_retry_dispatch_failed",
                        "jobId": job_id,
                    }
                )
            )
            failed_at = now or datetime.now(timezone.utc)
            delay = _queue_recovery_delay(settings, jitter)
            with session_factory() as session:
                result = session.execute(
                    update(TranslationJob)
                    .where(
                        TranslationJob.id == job_id,
                        TranslationJob.status == JobStatus.TRANSLATION_QUEUED,
                    )
                    .values(
                        status=JobStatus.TRANSLATION_RETRY_WAIT,
                        translation_next_retry_at=failed_at
                        + timedelta(seconds=delay),
                        translation_wait_reason="queue_unavailable",
                        translation_heartbeat_at=None,
                    )
                )
                session.commit()
                if result.rowcount == 1:
                    counts["dispatchFailed"] += 1
            continue
        counts["dispatched"] += 1

    logger.info(
        json.dumps(
            {
                "event": "translation_retry_recovery_completed",
                "preparationRecoveredJobs": counts["preparationRecovered"],
                "recoveredJobs": counts["recovered"],
                "dispatchedJobs": counts["dispatched"],
                "dispatchFailedJobs": counts["dispatchFailed"],
            }
        )
    )
    return counts


@celery_app.task(name="meguyomi.recover_translation_jobs")
def recover_translation_jobs_task() -> dict[str, int]:
    return recover_translation_jobs(
        SessionLocal,
        get_settings(),
    )
