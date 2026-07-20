import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from shutil import rmtree

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.tasks.celery_app import celery_app
from app.tasks.preparation import normalize_job_id
from app.tasks.translation import checkpoint_is_expired, resolve_checkpoint_directory


SessionFactory = Callable[[], Session]
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
    counts = {"expired": 0, "completed": 0, "orphaned": 0}
    temporary_root = (settings.storage_root / "temporary").resolve()
    temporary_root.mkdir(parents=True, exist_ok=True)

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

    logger.info(
        json.dumps(
            {
                "event": "translation_checkpoint_cleanup_completed",
                "expiredJobs": counts["expired"],
                "completedJobs": counts["completed"],
                "orphanedCheckpoints": counts["orphaned"],
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
