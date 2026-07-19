import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from shutil import rmtree
from typing import Protocol

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
                TranslationJob.status == JobStatus.TRANSLATION_QUEUED,
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

    temporary = settings.storage_root / "temporary" / f"{normalized_job_id}.translation"
    result_filename = f"{normalized_job_id}.pdf"
    result_path = settings.storage_root / "results" / result_filename
    rmtree(temporary, ignore_errors=True)

    failure_code = "TRANSLATION_FAILED"
    try:
        preview_pages = resolve_preview_pages(
            settings,
            normalized_job_id,
            job.page_count,
        )
        if result_path.exists():
            raise ResultBuildError("Result PDF already exists.")
        translated_pages_directory = temporary / "pages"
        translated_pages_directory.mkdir(parents=True, exist_ok=False)
        translated_pages: list[Path] = []
        for preview_page in preview_pages:
            translation = translator.translate_page(preview_page)
            translated_page = translated_pages_directory / preview_page.name
            render_translated_page(preview_page, translated_page, translation)
            translated_pages.append(translated_page)

        temporary_result = temporary / result_filename
        build_result_pdf(translated_pages, temporary_result)
        result_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_result.replace(result_path)
    except FileNotFoundError:
        failure_code = "PREVIEW_NOT_FOUND"
    except GeminiTranslationError:
        failure_code = "AI_TRANSLATION_FAILED"
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
    finally:
        rmtree(temporary, ignore_errors=True)

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
        return "AI_NOT_CONFIGURED"
    translator = GeminiPageTranslator(
        api_key=settings.gemini_api_key,
        model=settings.gemini_model,
        timeout_seconds=settings.gemini_timeout_seconds,
        max_image_bytes=settings.gemini_max_image_bytes,
        max_response_bytes=settings.gemini_max_response_bytes,
        max_output_tokens=settings.gemini_max_output_tokens,
    )
    return translate_job(job_id, SessionLocal, settings, translator)


def dispatch_translation_job(job_id: str) -> None:
    translate_job_task.delay(job_id)
