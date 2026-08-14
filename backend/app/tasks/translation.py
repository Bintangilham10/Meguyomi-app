import json
import logging
import random
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from shutil import rmtree
from typing import Protocol
from uuid import uuid4

from PIL import Image
from sqlalchemy import case, func, select, update
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
    TranslationQualityError,
    build_result_pdf,
    render_translated_page,
)
from app.tasks.celery_app import celery_app
from app.tasks.preparation import normalize_job_id


SessionFactory = Callable[[], Session]
RetryJitter = Callable[[float, float], float]
logger = logging.getLogger(__name__)
TRANSLATION_RENDER_VERSION = "6"


class PageTranslator(Protocol):
    def translate_page(
        self,
        page_path: Path,
        *,
        quality_reason: str | None = None,
        tile_cache_directory: Path | None = None,
    ) -> PageTranslation: ...


class TranslationClaimLost(Exception):
    pass


_QUALITY_FAILURE_CODES = {
    "placement_overlap": "RESULT_PLACEMENT_OVERLAP",
    "source_mask_failure": "RESULT_SOURCE_MASK_FAILED",
    "text_does_not_fit": "RESULT_TEXT_FIT_FAILED",
}


def quality_failure_code(error: TranslationQualityError) -> str:
    return _QUALITY_FAILURE_CODES.get(error.reason, "RESULT_QUALITY_FAILED")


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
                translation_retry_attempt=case(
                    (
                        TranslationJob.translated_page_count
                        < translated_page_count,
                        0,
                    ),
                    else_=TranslationJob.translation_retry_attempt,
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


def clear_previous_translation_result(
    job_id: str,
    session_factory: SessionFactory,
    result_path: Path,
) -> bool:
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
        try:
            result_path.unlink(missing_ok=True)
        except OSError as error:
            raise ResultBuildError("Previous result PDF could not be removed.") from error
        session.commit()
        return True


def publish_translation_result(
    job_id: str,
    session_factory: SessionFactory,
    temporary_result: Path,
    result_path: Path,
    result_filename: str,
) -> bool:
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
        try:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            temporary_result.replace(result_path)
        except OSError as error:
            raise ResultBuildError("Result PDF could not be published.") from error
        job.status = JobStatus.COMPLETED
        job.completed_at = utc_now()
        job.result_filename = result_filename
        job.failure_code = None
        job.checkpoint_updated_at = None
        job.translation_retry_attempt = 0
        job.translation_next_retry_at = None
        job.translation_wait_reason = None
        job.translation_heartbeat_at = None
        session.commit()
        return True


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
        payload = json.loads(record_path.read_text(encoding="utf-8"))
        translation = PageTranslation.model_validate(payload)
    except (OSError, ValueError):
        return False
    return all(
        isinstance(region, dict) and "source_language" in region
        for region in payload.get("regions", [])
    ) and len(translation.regions) == len(payload.get("regions", []))


def ensure_checkpoint_render_version(
    checkpoint_pages: Path,
    records_directory: Path,
) -> None:
    checkpoint_root = checkpoint_pages.parent
    version_path = checkpoint_root / ".render-version"
    try:
        current_version = version_path.read_text(encoding="ascii").strip()
    except OSError:
        current_version = ""
    if current_version == TRANSLATION_RENDER_VERSION:
        return

    if checkpoint_pages.exists():
        rmtree(checkpoint_pages)
    checkpoint_pages.mkdir(parents=True, exist_ok=True)
    records_directory.mkdir(parents=True, exist_ok=True)
    partial_version = checkpoint_root / ".render-version.part"
    partial_version.write_text(
        TRANSLATION_RENDER_VERSION,
        encoding="ascii",
    )
    partial_version.replace(version_path)


def reconcile_translation_checkpoints(
    job_id: str,
    session_factory: SessionFactory,
    checkpoint_pages: Path,
    preview_pages: list[Path],
    records_directory: Path,
) -> list[Path]:
    ensure_checkpoint_render_version(
        checkpoint_pages,
        records_directory,
    )
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
            record_path = records_directory / f"{preview_page.stem}.json"
            if not checkpoint_record_is_valid(record_path):
                record_path.unlink(missing_ok=True)

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


def collect_stopped_checkpoint_pages(
    settings: Settings,
    job_id: str,
    translated_page_count: int,
) -> list[Path]:
    if translated_page_count <= 0:
        return []

    checkpoint = resolve_checkpoint_directory(settings, job_id)
    checkpoint_pages = checkpoint / "pages"
    records_directory = resolve_translation_records_directory(settings, job_id)
    version_path = checkpoint / ".render-version"
    try:
        render_version = version_path.read_text(encoding="ascii").strip()
    except OSError:
        return []
    if render_version != TRANSLATION_RENDER_VERSION:
        return []

    preview_pages = resolve_preview_pages(
        settings,
        job_id,
        translated_page_count,
    )
    stopped_pages: list[Path] = []
    for preview_page in preview_pages:
        checkpoint_page = checkpoint_pages / preview_page.name
        record_path = records_directory / f"{preview_page.stem}.json"
        if (
            not checkpoint_page.is_file()
            or not checkpoint_page_is_valid(checkpoint_page, preview_page)
            or not checkpoint_record_is_valid(record_path)
        ):
            break
        stopped_pages.append(checkpoint_page)
    return stopped_pages


def publish_stopped_translation(
    job_id: str,
    session_factory: SessionFactory,
    temporary_result: Path | None,
    result_path: Path,
    result_filename: str,
    translated_page_count: int,
    failure_code: str | None,
) -> str:
    with session_factory() as session:
        job = session.scalar(
            select(TranslationJob)
            .where(TranslationJob.id == job_id)
            .with_for_update()
        )
        if job is None:
            if temporary_result is not None:
                temporary_result.unlink(missing_ok=True)
            return "JOB_NOT_FOUND"
        if job.status != JobStatus.TRANSLATION_STOPPING:
            if temporary_result is not None:
                temporary_result.unlink(missing_ok=True)
            return job.status

        has_result = False
        if temporary_result is not None:
            try:
                result_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_result.replace(result_path)
                has_result = True
            except OSError:
                logger.exception(
                    json.dumps(
                        {
                            "event": "translation_stop_result_publish_failed",
                            "jobId": job_id,
                        }
                    )
                )
                temporary_result.unlink(missing_ok=True)
                failure_code = "PARTIAL_RESULT_BUILD_FAILED"
        if not has_result:
            try:
                result_path.unlink(missing_ok=True)
            except OSError:
                logger.exception(
                    json.dumps(
                        {
                            "event": "stale_translation_result_removal_failed",
                            "jobId": job_id,
                        }
                    )
                )

        job.status = JobStatus.TRANSLATION_STOPPED
        job.translated_page_count = translated_page_count
        job.completed_at = None
        job.result_filename = result_filename if has_result else None
        job.failure_code = failure_code
        job.translation_retry_attempt = 0
        job.translation_next_retry_at = None
        job.translation_wait_reason = None
        job.translation_heartbeat_at = None
        session.commit()
        return JobStatus.TRANSLATION_STOPPED


def finalize_stopped_translation(
    job_id: str,
    session_factory: SessionFactory,
    settings: Settings,
) -> str:
    normalized_job_id = normalize_job_id(job_id)
    if normalized_job_id is None:
        return "INVALID_JOB_ID"

    with session_factory() as session:
        job = session.scalar(
            select(TranslationJob)
            .where(TranslationJob.id == normalized_job_id)
            .with_for_update()
        )
        if job is None:
            return "JOB_NOT_FOUND"
        if job.status != JobStatus.TRANSLATION_STOPPING:
            return job.status
        requested_page_count = min(job.translated_page_count, job.page_count)
        job.translation_heartbeat_at = utc_now()
        session.commit()

    checkpoint = resolve_checkpoint_directory(settings, normalized_job_id)
    result_filename = f"{normalized_job_id}.pdf"
    result_path = settings.storage_root / "results" / result_filename
    temporary_result: Path | None = None
    failure_code: str | None = None
    stopped_pages: list[Path] = []
    try:
        stopped_pages = collect_stopped_checkpoint_pages(
            settings,
            normalized_job_id,
            requested_page_count,
        )
        if len(stopped_pages) < requested_page_count:
            failure_code = "PARTIAL_RESULT_BUILD_FAILED"
        if stopped_pages:
            checkpoint.mkdir(parents=True, exist_ok=True)
            temporary_result = checkpoint / (
                f"{normalized_job_id}.{uuid4().hex}.stopped.pdf"
            )
            temporary_result.unlink(missing_ok=True)
            build_result_pdf(stopped_pages, temporary_result)
    except (FileNotFoundError, ResultBuildError, OSError, ValueError):
        failure_code = "PARTIAL_RESULT_BUILD_FAILED"
        if temporary_result is not None:
            temporary_result.unlink(missing_ok=True)
            temporary_result = None
        logger.exception(
            json.dumps(
                {
                    "event": "translation_stop_result_build_failed",
                    "jobId": normalized_job_id,
                }
            )
        )

    result = publish_stopped_translation(
        normalized_job_id,
        session_factory,
        temporary_result,
        result_path,
        result_filename,
        len(stopped_pages),
        failure_code,
    )
    if result == JobStatus.TRANSLATION_STOPPED:
        logger.info(
            json.dumps(
                {
                    "event": "job_translation_stopped",
                    "jobId": normalized_job_id,
                    "translatedPageCount": len(stopped_pages),
                    "resultAvailable": result_path.is_file(),
                }
            )
        )
    return result


def settle_translation_interruption(
    job_id: str,
    session_factory: SessionFactory,
    settings: Settings,
) -> str:
    current_status = get_translation_job_status(job_id, session_factory)
    if current_status == JobStatus.TRANSLATION_STOPPING:
        return finalize_stopped_translation(job_id, session_factory, settings)
    return current_status


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
        return settle_translation_interruption(
            normalized_job_id,
            session_factory,
            settings,
        )

    checkpoint = resolve_checkpoint_directory(settings, normalized_job_id)
    result_filename = f"{normalized_job_id}.pdf"
    result_path = settings.storage_root / "results" / result_filename
    temporary_result: Path | None = None

    failure_code = "TRANSLATION_FAILED"
    try:
        if not clear_previous_translation_result(
            normalized_job_id,
            session_factory,
            result_path,
        ):
            raise TranslationClaimLost
        preview_pages = resolve_preview_pages(
            settings,
            normalized_job_id,
            job.page_count,
        )
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
            translation_record = records_directory / f"{preview_page.stem}.json"
            tile_cache_directory = records_directory / (
                f"{preview_page.stem}.tiles"
            )
            translated_page = translated_pages_directory / preview_page.name
            partial_page = translated_pages_directory / f"{preview_page.name}.part"
            partial_page.unlink(missing_ok=True)
            quality_reason: str | None = None
            for quality_attempt in range(
                settings.translation_quality_rescan_attempts + 1
            ):
                if not touch_translation_heartbeat(
                    normalized_job_id,
                    session_factory,
                ):
                    raise TranslationClaimLost
                if (
                    quality_attempt == 0
                    and checkpoint_record_is_valid(translation_record)
                ):
                    translation = PageTranslation.model_validate_json(
                        translation_record.read_text(encoding="utf-8")
                    )
                else:
                    translation = translator.translate_page(
                        preview_page,
                        quality_reason=quality_reason,
                        tile_cache_directory=tile_cache_directory,
                    )
                    partial_record = (
                        records_directory / f"{preview_page.stem}.json.part"
                    )
                    partial_record.write_text(
                        translation.model_dump_json(),
                        encoding="utf-8",
                    )
                    partial_record.replace(translation_record)
                try:
                    render_translated_page(
                        preview_page,
                        partial_page,
                        translation,
                    )
                except TranslationQualityError as error:
                    translation_record.unlink(missing_ok=True)
                    partial_page.unlink(missing_ok=True)
                    will_rescan = (
                        quality_attempt
                        < settings.translation_quality_rescan_attempts
                    )
                    logger.warning(
                        json.dumps(
                            {
                                "event": "translation_layout_rejected",
                                "jobId": normalized_job_id,
                                "pageNumber": page_number,
                                "qualityAttempt": quality_attempt + 1,
                                "qualityReason": error.reason,
                                "qualityDetails": error.details,
                                "willRescan": will_rescan,
                            }
                        )
                    )
                    if not will_rescan:
                        raise
                    quality_reason = error.reason
                    continue
                break
            rmtree(tile_cache_directory, ignore_errors=True)
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
        if not publish_translation_result(
            normalized_job_id,
            session_factory,
            temporary_result,
            result_path,
            result_filename,
        ):
            raise TranslationClaimLost
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
        if temporary_result is not None:
            temporary_result.unlink(missing_ok=True)
        return settle_translation_interruption(
            normalized_job_id,
            session_factory,
            settings,
        )
    except TranslationQualityError as error:
        failure_code = quality_failure_code(error)
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
    if temporary_result is not None:
        temporary_result.unlink(missing_ok=True)
    if not mark_translation_failed(
        normalized_job_id,
        session_factory,
        failure_code,
    ):
        return settle_translation_interruption(
            normalized_job_id,
            session_factory,
            settings,
        )
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
        max_tile_aspect_ratio=settings.gemini_max_tile_aspect_ratio,
        tile_overlap_ratio=settings.gemini_tile_overlap_ratio,
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


@celery_app.task(
    name="meguyomi.finalize_translation_stop",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=30,
    retry_kwargs={"max_retries": 3},
)
def finalize_translation_stop_task(job_id: str) -> str:
    return finalize_stopped_translation(job_id, SessionLocal, get_settings())


def dispatch_translation_job(job_id: str) -> None:
    translate_job_task.delay(job_id)


def dispatch_translation_stop(job_id: str) -> None:
    finalize_translation_stop_task.delay(job_id)
