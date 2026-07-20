import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree
from typing import Protocol

from PIL import Image
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.session import SessionLocal
from app.models.job_status import JobStatus
from app.models.translation_job import TranslationJob
from app.services.manga_translation import (
    GeminiPageTranslator,
    GeminiTranslationError,
    PageTranslation,
)
from app.services.translated_pdf import (
    ResultBuildError,
    build_result_pdf,
    render_translated_page,
)
from app.tasks.celery_app import celery_app
from app.tasks.preparation import normalize_job_id


SessionFactory = Callable[[], Session]
logger = logging.getLogger(__name__)


class PageTranslator(Protocol):
    def translate_page(self, page_path: Path) -> PageTranslation: ...


def claim_translation_job(
    job_id: str,
    session_factory: SessionFactory,
) -> TranslationJob | None:
    with session_factory() as session:
        result = session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status.in_(
                    (
                        JobStatus.TRANSLATION_QUEUED,
                        JobStatus.TRANSLATING,
                    )
                ),
            )
            .values(
                status=JobStatus.TRANSLATING,
                translation_started_at=datetime.now(timezone.utc),
                completed_at=None,
                result_filename=None,
                failure_code=None,
            )
        )
        session.commit()
        if result.rowcount != 1:
            return None
        return session.get(TranslationJob, job_id)


def fail_queued_translation_job(
    job_id: str,
    session_factory: SessionFactory,
    failure_code: str,
) -> str:
    normalized_job_id = normalize_job_id(job_id)
    if normalized_job_id is None:
        return "INVALID_JOB_ID"

    with session_factory() as session:
        result = session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == normalized_job_id,
                TranslationJob.status == JobStatus.TRANSLATION_QUEUED,
            )
            .values(status=JobStatus.FAILED, failure_code=failure_code)
        )
        session.commit()
        if result.rowcount == 1:
            return JobStatus.FAILED
        existing = session.get(TranslationJob, normalized_job_id)
        return existing.status if existing is not None else "JOB_NOT_FOUND"


def record_translation_progress(
    job_id: str,
    session_factory: SessionFactory,
    translated_page_count: int,
) -> None:
    with session_factory() as session:
        session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .values(
                translated_page_count=translated_page_count,
                checkpoint_updated_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def synchronize_translation_progress(
    job_id: str,
    session_factory: SessionFactory,
    translated_page_count: int,
    checkpoint_updated_at: datetime | None,
) -> None:
    with session_factory() as session:
        session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .values(
                translated_page_count=translated_page_count,
                checkpoint_updated_at=checkpoint_updated_at,
            )
        )
        session.commit()


def mark_translation_failed(
    job_id: str,
    session_factory: SessionFactory,
    failure_code: str,
) -> None:
    with session_factory() as session:
        session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .values(
                status=JobStatus.FAILED,
                completed_at=None,
                result_filename=None,
                failure_code=failure_code,
            )
        )
        session.commit()


def mark_translation_completed(
    job_id: str,
    session_factory: SessionFactory,
    result_filename: str,
) -> None:
    with session_factory() as session:
        session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .values(
                status=JobStatus.COMPLETED,
                completed_at=datetime.now(timezone.utc),
                result_filename=result_filename,
                failure_code=None,
                checkpoint_updated_at=None,
            )
        )
        session.commit()


def resolve_preview_pages(
    settings: Settings,
    job_id: str,
    page_count: int,
) -> list[Path]:
    previews_root = (settings.storage_root / "previews").resolve()
    job_directory = (previews_root / job_id).resolve()
    if job_directory.parent != previews_root or not job_directory.is_dir():
        raise FileNotFoundError(job_directory)

    pages: list[Path] = []
    for page_number in range(1, page_count + 1):
        page = (job_directory / f"page-{page_number:04d}.png").resolve()
        if page.parent != job_directory or not page.is_file():
            raise FileNotFoundError(page)
        pages.append(page)
    return pages


def resolve_checkpoint_directory(settings: Settings, job_id: str) -> Path:
    temporary_root = (settings.storage_root / "temporary").resolve()
    checkpoint = (temporary_root / f"{job_id}.translation").resolve()
    if checkpoint.parent != temporary_root:
        raise ResultBuildError("Translation checkpoint path is invalid.")
    return checkpoint


def checkpoint_page_is_valid(checkpoint: Path, preview: Path) -> bool:
    try:
        with Image.open(preview) as preview_image:
            expected_size = preview_image.size
        with Image.open(checkpoint) as checkpoint_image:
            if checkpoint_image.format != "PNG":
                return False
            if checkpoint_image.size != expected_size:
                return False
            checkpoint_image.verify()
    except (OSError, ValueError):
        return False
    return True


def reconcile_translation_checkpoints(
    job_id: str,
    session_factory: SessionFactory,
    checkpoint_pages: Path,
    preview_pages: list[Path],
) -> list[Path]:
    checkpoint_pages.mkdir(parents=True, exist_ok=True)
    for partial in checkpoint_pages.glob("*.part"):
        partial.unlink(missing_ok=True)

    translated_pages: list[Path] = []
    for preview_page in preview_pages:
        checkpoint_page = checkpoint_pages / preview_page.name
        if not checkpoint_page.is_file() or not checkpoint_page_is_valid(
            checkpoint_page,
            preview_page,
        ):
            break
        translated_pages.append(checkpoint_page)

    valid_names = {path.name for path in translated_pages}
    for preview_page in preview_pages:
        if preview_page.name not in valid_names:
            (checkpoint_pages / preview_page.name).unlink(missing_ok=True)

    checkpoint_updated_at = None
    if translated_pages:
        checkpoint_updated_at = datetime.fromtimestamp(
            max(path.stat().st_mtime for path in translated_pages),
            timezone.utc,
        )
    synchronize_translation_progress(
        job_id,
        session_factory,
        len(translated_pages),
        checkpoint_updated_at,
    )
    return translated_pages


def checkpoint_is_expired(
    checkpoint_updated_at: datetime | None,
    retention_days: int,
    *,
    now: datetime | None = None,
) -> bool:
    if checkpoint_updated_at is None:
        return False
    if checkpoint_updated_at.tzinfo is None:
        checkpoint_updated_at = checkpoint_updated_at.replace(tzinfo=timezone.utc)
    reference_time = now or datetime.now(timezone.utc)
    return checkpoint_updated_at <= reference_time - timedelta(days=retention_days)


def translate_job(
    job_id: str,
    session_factory: SessionFactory,
    settings: Settings,
    translator: PageTranslator,
) -> str:
    normalized_job_id = normalize_job_id(job_id)
    if normalized_job_id is None:
        return "INVALID_JOB_ID"

    job = claim_translation_job(normalized_job_id, session_factory)
    if job is None:
        with session_factory() as session:
            existing = session.get(TranslationJob, normalized_job_id)
            return existing.status if existing is not None else "JOB_NOT_FOUND"

    checkpoint = resolve_checkpoint_directory(settings, normalized_job_id)
    result_filename = f"{normalized_job_id}.pdf"
    result_path = settings.storage_root / "results" / result_filename

    failure_code = "TRANSLATION_FAILED"
    try:
        preview_pages = resolve_preview_pages(
            settings,
            normalized_job_id,
            job.page_count,
        )
        if result_path.exists():
            raise ResultBuildError("Result PDF already exists.")
        if checkpoint_is_expired(
            job.checkpoint_updated_at,
            settings.translation_checkpoint_retention_days,
        ):
            try:
                if checkpoint.exists():
                    rmtree(checkpoint)
            except OSError as error:
                raise ResultBuildError(
                    "Expired translation checkpoint could not be removed."
                ) from error
            synchronize_translation_progress(
                normalized_job_id,
                session_factory,
                0,
                None,
            )
            logger.info(
                json.dumps(
                    {
                        "event": "translation_checkpoint_expired",
                        "jobId": normalized_job_id,
                    }
                )
            )
        translated_pages_directory = checkpoint / "pages"
        translated_pages = reconcile_translation_checkpoints(
            normalized_job_id,
            session_factory,
            translated_pages_directory,
            preview_pages,
        )
        for page_number in range(len(translated_pages) + 1, job.page_count + 1):
            preview_page = preview_pages[page_number - 1]
            translation = translator.translate_page(preview_page)
            translated_page = translated_pages_directory / preview_page.name
            partial_page = translated_pages_directory / f"{preview_page.name}.part"
            partial_page.unlink(missing_ok=True)
            render_translated_page(preview_page, partial_page, translation)
            partial_page.replace(translated_page)
            translated_pages.append(translated_page)
            record_translation_progress(
                normalized_job_id,
                session_factory,
                page_number,
            )

        temporary_result = checkpoint / result_filename
        temporary_result.unlink(missing_ok=True)
        build_result_pdf(translated_pages, temporary_result)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_result.replace(result_path)
    except FileNotFoundError:
        failure_code = "PREVIEW_NOT_FOUND"
    except GeminiTranslationError as error:
        failure_code = (
            "AI_RATE_LIMITED"
            if error.http_status == 429
            else "AI_TRANSLATION_FAILED"
        )
    except ResultBuildError:
        failure_code = "RESULT_BUILD_FAILED"
    except Exception:
        failure_code = "TRANSLATION_FAILED"
        logger.exception(
            json.dumps(
                {
                    "event": "job_translation_unexpected_error",
                    "jobId": normalized_job_id,
                }
            )
        )
    else:
        mark_translation_completed(
            normalized_job_id,
            session_factory,
            result_filename,
        )
        rmtree(checkpoint, ignore_errors=True)
        logger.info(
            json.dumps(
                {
                    "event": "job_translation_completed",
                    "jobId": normalized_job_id,
                    "pageCount": job.page_count,
                }
            )
        )
        return JobStatus.COMPLETED
    result_path.unlink(missing_ok=True)
    mark_translation_failed(normalized_job_id, session_factory, failure_code)
    logger.warning(
        json.dumps(
            {
                "event": "job_translation_failed",
                "jobId": normalized_job_id,
                "failureCode": failure_code,
            }
        )
    )
    return JobStatus.FAILED


@celery_app.task(
    name="meguyomi.translate_job",
    acks_late=True,
    reject_on_worker_lost=True,
)
def translate_job_task(job_id: str) -> str:
    settings = get_settings()
    if not settings.gemini_api_key:
        result = fail_queued_translation_job(
            job_id,
            SessionLocal,
            "AI_NOT_CONFIGURED",
        )
        logger.warning(
            json.dumps(
                {
                    "event": "job_translation_configuration_missing",
                    "jobId": job_id,
                }
            )
        )
        return result
    translator = GeminiPageTranslator(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        max_image_bytes=settings.gemini_max_image_bytes,
        max_response_bytes=settings.gemini_max_response_bytes,
        max_output_tokens=settings.gemini_max_output_tokens,
        min_request_interval_seconds=(
            settings.gemini_min_request_interval_seconds
        ),
        max_retries=settings.gemini_max_retries,
        retry_base_delay_seconds=settings.gemini_retry_base_delay_seconds,
        retry_max_delay_seconds=settings.gemini_retry_max_delay_seconds,
    )
    return translate_job(job_id, SessionLocal, settings, translator)


def dispatch_translation_job(job_id: str) -> None:
    translate_job_task.delay(job_id)
