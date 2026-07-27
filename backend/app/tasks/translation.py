import json
import logging
import random
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree
from typing import Protocol

from PIL import Image
from sqlalchemy import func, select, update
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
RetryJitter = Callable[[float, float], float]
logger = logging.getLogger(__name__)


class PageTranslator(Protocol):
    def translate_page(self, page_path: Path) -> PageTranslation: ...


class TranslationClaimLost(Exception):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def get_translation_job_status(
    job_id: str,
    session_factory: SessionFactory,
) -> str:
    with session_factory() as session:
        job = session.get(TranslationJob, job_id)
        return job.status if job is not None else "JOB_NOT_FOUND"


def claim_translation_job(
    job_id: str,
    session_factory: SessionFactory,
) -> TranslationJob | None:
    claimed_at = utc_now()
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
                translation_started_at=func.coalesce(
                    TranslationJob.translation_started_at,
                    claimed_at,
                ),
                translation_heartbeat_at=claimed_at,
                translation_next_retry_at=None,
                translation_wait_reason=None,
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
            .values(
                status=JobStatus.FAILED,
                failure_code=failure_code,
                translation_next_retry_at=None,
                translation_wait_reason=None,
                translation_heartbeat_at=None,
            )
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
) -> bool:
    recorded_at = utc_now()
    with session_factory() as session:
        result = session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .values(
                translated_page_count=translated_page_count,
                checkpoint_updated_at=recorded_at,
                translation_retry_attempt=0,
                translation_next_retry_at=None,
                translation_wait_reason=None,
                translation_heartbeat_at=recorded_at,
            )
        )
        session.commit()
        return result.rowcount == 1


def synchronize_translation_progress(
    job_id: str,
    session_factory: SessionFactory,
    translated_page_count: int,
    checkpoint_updated_at: datetime | None,
) -> bool:
    with session_factory() as session:
        result = session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .values(
                translated_page_count=translated_page_count,
                checkpoint_updated_at=checkpoint_updated_at,
                translation_retry_attempt=0 if translated_page_count else (
                    TranslationJob.translation_retry_attempt
                ),
                translation_next_retry_at=None,
                translation_wait_reason=None,
                translation_heartbeat_at=utc_now(),
            )
        )
        session.commit()
        return result.rowcount == 1


def touch_translation_heartbeat(
    job_id: str,
    session_factory: SessionFactory,
) -> bool:
    with session_factory() as session:
        result = session.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .values(translation_heartbeat_at=utc_now())
        )
        session.commit()
        return result.rowcount == 1


def mark_translation_failed(
    job_id: str,
    session_factory: SessionFactory,
    failure_code: str,
) -> bool:
    with session_factory() as session:
        result = session.execute(
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
                translation_next_retry_at=None,
                translation_wait_reason=None,
                translation_heartbeat_at=None,
            )
        )
        session.commit()
        return result.rowcount == 1


def mark_translation_completed(
    job_id: str,
    session_factory: SessionFactory,
    result_filename: str,
) -> bool:
    with session_factory() as session:
        result = session.execute(
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
                translation_retry_attempt=0,
                translation_next_retry_at=None,
                translation_wait_reason=None,
                translation_heartbeat_at=None,
            )
        )
        session.commit()
        return result.rowcount == 1


def is_deferred_gemini_error(error: GeminiTranslationError) -> bool:
    if error.http_status in {408, 429}:
        return True
    if error.http_status is not None:
        return 500 <= error.http_status < 600
    return error.retryable


def defer_translation_retry(
    job_id: str,
    session_factory: SessionFactory,
    settings: Settings,
    error: GeminiTranslationError,
    *,
    now: datetime | None = None,
    jitter: RetryJitter = random.uniform,
) -> bool:
    reference_time = now or utc_now()
    wait_reason = (
        "rate_limited" if error.http_status == 429 else "service_unavailable"
    )
    schedule = (
        settings.gemini_rate_limit_retry_delays_seconds
        if error.http_status == 429
        else settings.gemini_service_retry_delays_seconds
    )

    with session_factory() as session:
        job = session.scalar(
            select(TranslationJob)
            .where(
                TranslationJob.id == job_id,
                TranslationJob.status == JobStatus.TRANSLATING,
            )
            .with_for_update()
        )
        if job is None:
            return False

        attempt = job.translation_retry_attempt + 1
        if attempt > len(schedule):
            return False

        scheduled_delay = float(schedule[attempt - 1])
        provider_delay = min(
            max(0.0, error.retry_after_seconds or 0.0),
            float(settings.gemini_retry_hint_max_seconds),
        )
        base_delay = max(scheduled_delay, provider_delay)
        jitter_limit = min(
            settings.gemini_deferred_retry_jitter_max_seconds,
            base_delay * settings.gemini_deferred_retry_jitter_ratio,
        )
        jitter_seconds = min(
            jitter_limit,
            max(0.0, jitter(0.0, jitter_limit)),
        )
        effective_delay = base_delay + jitter_seconds
        next_retry_at = reference_time + timedelta(seconds=effective_delay)

        job.status = JobStatus.TRANSLATION_RETRY_WAIT
        job.translation_retry_attempt = attempt
        job.translation_next_retry_at = next_retry_at
        job.translation_wait_reason = wait_reason
        job.translation_heartbeat_at = None
        job.failure_code = None
        session.commit()

    logger.warning(
        json.dumps(
            {
                "event": "job_translation_retry_deferred",
                "jobId": job_id,
                "httpStatus": error.http_status,
                "waitReason": wait_reason,
                "retryAttempt": attempt,
                "delaySeconds": round(effective_delay, 3),
                "nextRetryAt": next_retry_at.isoformat(),
            }
        )
    )
    return True


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


def resolve_translation_records_directory(settings: Settings, job_id: str) -> Path:
    translations_root = (settings.storage_root / "translations").resolve()
    records = (translations_root / job_id).resolve()
    if records.parent != translations_root:
        raise ResultBuildError("Translation records path is invalid.")
    return records


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


def checkpoint_record_is_valid(record_path: Path) -> bool:
    try:
        json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return True


def reconcile_translation_checkpoints(
    job_id: str,
    session_factory: SessionFactory,
    checkpoint_pages: Path,
    preview_pages: list[Path],
    records_directory: Path,
) -> list[Path]:
    checkpoint_pages.mkdir(parents=True, exist_ok=True)
    for partial in checkpoint_pages.glob("*.part"):
        partial.unlink(missing_ok=True)
    records_directory.mkdir(parents=True, exist_ok=True)
    for partial in records_directory.glob("*.json.part"):
        partial.unlink(missing_ok=True)

    translated_pages: list[Path] = []
    for preview_page in preview_pages:
        checkpoint_page = checkpoint_pages / preview_page.name
        if (
            not checkpoint_page.is_file()
            or not checkpoint_page_is_valid(checkpoint_page, preview_page)
            or not checkpoint_record_is_valid(
                records_directory / f"{preview_page.stem}.json"
            )
        ):
            break
        translated_pages.append(checkpoint_page)

    valid_names = {path.name for path in translated_pages}
    for preview_page in preview_pages:
        if preview_page.name not in valid_names:
            (checkpoint_pages / preview_page.name).unlink(missing_ok=True)
            (records_directory / f"{preview_page.stem}.json").unlink(
                missing_ok=True
            )

    checkpoint_updated_at = None
    if translated_pages:
        checkpoint_updated_at = datetime.fromtimestamp(
            max(path.stat().st_mtime for path in translated_pages),
            timezone.utc,
        )
    if not synchronize_translation_progress(
        job_id,
        session_factory,
        len(translated_pages),
        checkpoint_updated_at,
    ):
        raise TranslationClaimLost
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
    *,
    retry_jitter: RetryJitter = random.uniform,
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
        records_directory = resolve_translation_records_directory(
            settings,
            normalized_job_id,
        )
        translated_pages = reconcile_translation_checkpoints(
            normalized_job_id,
            session_factory,
            translated_pages_directory,
            preview_pages,
            records_directory,
        )
        for page_number in range(len(translated_pages) + 1, job.page_count + 1):
            preview_page = preview_pages[page_number - 1]
            if not touch_translation_heartbeat(
                normalized_job_id,
                session_factory,
            ):
                raise TranslationClaimLost
            translation = translator.translate_page(preview_page)
            translation_record = records_directory / f"{preview_page.stem}.json"
            partial_record = (
                records_directory / f"{preview_page.stem}.json.part"
            )
            partial_record.write_text(
                translation.model_dump_json(),
                encoding="utf-8",
            )
            partial_record.replace(translation_record)
            translated_page = translated_pages_directory / preview_page.name
            partial_page = translated_pages_directory / f"{preview_page.name}.part"
            partial_page.unlink(missing_ok=True)
            render_translated_page(preview_page, partial_page, translation)
            partial_page.replace(translated_page)
            translated_pages.append(translated_page)
            if not record_translation_progress(
                normalized_job_id,
                session_factory,
                page_number,
            ):
                raise TranslationClaimLost

        if not touch_translation_heartbeat(
            normalized_job_id,
            session_factory,
        ):
            raise TranslationClaimLost
        temporary_result = checkpoint / result_filename
        temporary_result.unlink(missing_ok=True)
        build_result_pdf(translated_pages, temporary_result)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_result.replace(result_path)
    except FileNotFoundError:
        failure_code = "PREVIEW_NOT_FOUND"
    except GeminiTranslationError as error:
        if is_deferred_gemini_error(error) and defer_translation_retry(
            normalized_job_id,
            session_factory,
            settings,
            error,
            jitter=retry_jitter,
        ):
            return JobStatus.TRANSLATION_RETRY_WAIT
        if error.http_status == 429:
            failure_code = "AI_RATE_LIMITED"
        elif is_deferred_gemini_error(error):
            failure_code = "AI_SERVICE_UNAVAILABLE"
        else:
            failure_code = "AI_TRANSLATION_FAILED"
    except TranslationClaimLost:
        result_path.unlink(missing_ok=True)
        return get_translation_job_status(normalized_job_id, session_factory)
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
        if not mark_translation_completed(
            normalized_job_id,
            session_factory,
            result_filename,
        ):
            result_path.unlink(missing_ok=True)
            return get_translation_job_status(
                normalized_job_id,
                session_factory,
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
    if not mark_translation_failed(
        normalized_job_id,
        session_factory,
        failure_code,
    ):
        return get_translation_job_status(normalized_job_id, session_factory)
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
        inline_retry_max_delay_seconds=(
            settings.gemini_inline_retry_max_delay_seconds
        ),
    )
    return translate_job(job_id, SessionLocal, settings, translator)


def dispatch_translation_job(job_id: str) -> None:
    translate_job_task.delay(job_id)
