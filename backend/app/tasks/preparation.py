import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from shutil import rmtree
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.services.pdf_preview import PreviewRenderError, render_pdf_previews
from app.tasks.celery_app import celery_app


SessionFactory = Callable[[], Session]
logger = logging.getLogger(__name__)


def normalize_job_id(job_id: str) -> str | None:
    try:
        return str(UUID(job_id))
    except (TypeError, ValueError, AttributeError):
        return None


def resolve_source_path(settings: Settings, stored_filename: str) -> Path:
    filename = Path(stored_filename)
    if filename.name != stored_filename or filename.suffix.lower() != ".pdf":
        raise PreviewRenderError("Stored PDF path is invalid.")

    originals_root = (settings.storage_root / "originals").resolve()
    source = (originals_root / filename).resolve()
    if source.parent != originals_root:
        raise PreviewRenderError("Stored PDF path is invalid.")
    if not source.is_file():
        raise FileNotFoundError(source)
    return source


def claim_job(job_id: str, session_factory: SessionFactory) -> TranslationJob | None:
    with session_factory() as session:
        result = session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.QUEUED,
            )
            .values(
                status=JobStatus.PROCESSING,
                started_at=datetime.now(timezone.utc),
                prepared_at=None,
                failure_code=None,
            )
        )
        session.commit()
        if result.rowcount != 1:
            return None
        return session.get(TranslationJob, job_id)


def mark_ready(job_id: str, session_factory: SessionFactory) -> None:
    with session_factory() as session:
        session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.PROCESSING,
            )
            .values(
                status=JobStatus.READY_FOR_TRANSLATION,
                prepared_at=datetime.now(timezone.utc),
                failure_code=None,
            )
        )
        session.commit()


def mark_failed(
    job_id: str,
    session_factory: SessionFactory,
    failure_code: str,
) -> None:
    with session_factory() as session:
        session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.PROCESSING,
            )
            .values(status=JobStatus.FAILED, failure_code=failure_code)
        )
        session.commit()


def prepare_translation_job(
    job_id: str,
    session_factory: SessionFactory,
    settings: Settings,
) -> str:
    normalized_job_id = normalize_job_id(job_id)
    if normalized_job_id is None:
        return "INVALID_JOB_ID"

    job = claim_job(normalized_job_id, session_factory)
    if job is None:
        with session_factory() as session:
            existing = session.get(TranslationJob, normalized_job_id)
            return existing.status if existing is not None else "JOB_NOT_FOUND"

    temporary = settings.storage_root / "temporary" / f"{normalized_job_id}.preview"
    destination = settings.storage_root / "previews" / normalized_job_id
    rmtree(temporary, ignore_errors=True)

    try:
        source = resolve_source_path(settings, job.stored_filename)
        if destination.exists():
            raise PreviewRenderError("Preview destination already exists.")
        rendered_pages = render_pdf_previews(
            source,
            temporary,
            scale=settings.preview_render_scale,
            max_pixels=settings.max_preview_pixels,
            max_bytes=settings.max_preview_bytes,
        )
        if rendered_pages != job.page_count:
            raise PreviewRenderError("Rendered page count does not match the job.")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary.replace(destination)
    except FileNotFoundError:
        rmtree(temporary, ignore_errors=True)
        mark_failed(normalized_job_id, session_factory, "SOURCE_NOT_FOUND")
        logger.warning(
            json.dumps(
                {
                    "event": "job_preparation_failed",
                    "jobId": normalized_job_id,
                    "failureCode": "SOURCE_NOT_FOUND",
                }
            )
        )
        return JobStatus.FAILED
    except Exception:
        rmtree(temporary, ignore_errors=True)
        mark_failed(normalized_job_id, session_factory, "PREPARATION_FAILED")
        logger.exception(
            json.dumps(
                {
                    "event": "job_preparation_failed",
                    "jobId": normalized_job_id,
                    "failureCode": "PREPARATION_FAILED",
                }
            )
        )
        return JobStatus.FAILED

    mark_ready(normalized_job_id, session_factory)
    logger.info(
        json.dumps(
            {
                "event": "job_preparation_completed",
                "jobId": normalized_job_id,
                "pageCount": job.page_count,
            }
        )
    )
    return JobStatus.READY_FOR_TRANSLATION


@celery_app.task(
    name="meguyomi.prepare_translation_job",
    acks_late=True,
    reject_on_worker_lost=True,
)
def prepare_translation_job_task(job_id: str) -> str:
    return prepare_translation_job(job_id, SessionLocal, get_settings())


def dispatch_preparation_job(job_id: str) -> None:
    prepare_translation_job_task.delay(job_id)
