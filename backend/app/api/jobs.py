import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedUser
from app.core.config import get_settings
from app.db.session import get_db
from app.models.translation_job import (
    RETRYABLE_PREPARATION_FAILURE_CODES,
    RETRYABLE_TRANSLATION_FAILURE_CODES,
    TranslationJob,
)
from app.models.job_status import JobStatus
from app.schemas.job import JobListResponse, JobResponse, PaginationResponse
from app.services.job_artifacts import JobArtifactRemovalError, remove_job_artifacts
from app.services.pdf_upload import UploadValidationError, validate_and_store_pdf
from app.tasks.preparation import dispatch_preparation_job
from app.tasks.translation import dispatch_translation_job, dispatch_translation_stop


router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)
JOB_NOT_FOUND_MESSAGE = "Pekerjaan terjemahan tidak ditemukan."
DELETABLE_JOB_STATUSES = frozenset(
    {
        JobStatus.READY_FOR_TRANSLATION,
        JobStatus.TRANSLATION_RETRY_WAIT,
        JobStatus.TRANSLATION_STOPPED,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
    }
)
STOPPABLE_TRANSLATION_STATUSES = frozenset(
    {
        JobStatus.TRANSLATION_QUEUED,
        JobStatus.TRANSLATING,
        JobStatus.TRANSLATION_RETRY_WAIT,
    }
)


def api_error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message}},
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=JobResponse)
async def create_job(
    file: Annotated[UploadFile, File(description="PDF manga berbahasa Jepang")],
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
) -> JobResponse | JSONResponse:
    try:
        stored_pdf = await validate_and_store_pdf(file, get_settings())
    except UploadValidationError as error:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error": {
                    "code": error.code,
                    "message": error.message,
                }
            },
        )

    job = TranslationJob(
        id=str(stored_pdf.id),
        owner_username=username,
        original_filename=stored_pdf.original_filename,
        stored_filename=stored_pdf.stored_filename,
        size_bytes=stored_pdf.size_bytes,
        page_count=stored_pdf.page_count,
        status=JobStatus.QUEUED,
        created_at=stored_pdf.created_at,
    )
    try:
        db.add(job)
        db.commit()
        db.refresh(job)
    except SQLAlchemyError:
        db.rollback()
        stored_pdf.path.unlink(missing_ok=True)
        raise

    try:
        dispatch_preparation_job(job.id)
    except Exception:
        logger.exception(
            json.dumps(
                {
                    "event": "job_dispatch_failed",
                    "jobId": job.id,
                    "failureCode": "QUEUE_UNAVAILABLE",
                }
            )
        )
        job.status = JobStatus.FAILED
        job.failure_code = "QUEUE_UNAVAILABLE"
        db.commit()
        db.refresh(job)

    return JobResponse.model_validate(job)


@router.get("", response_model=JobListResponse)
def list_jobs(
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    page_size: Annotated[int, Query(alias="pageSize", ge=1, le=50)] = 10,
) -> JobListResponse:
    total_items = db.scalar(
        select(func.count())
        .select_from(TranslationJob)
        .where(TranslationJob.owner_username == username)
    ) or 0
    jobs = db.scalars(
        select(TranslationJob)
        .where(TranslationJob.owner_username == username)
        .order_by(TranslationJob.created_at.desc(), TranslationJob.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return JobListResponse(
        data=[JobResponse.model_validate(job) for job in jobs],
        pagination=PaginationResponse(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=(total_items + page_size - 1) // page_size,
        ),
    )


@router.delete(
    "/{job_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
def delete_job(
    job_id: UUID,
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
) -> Response | JSONResponse:
    normalized_job_id = str(job_id)
    job = db.scalar(
        select(TranslationJob)
        .where(
            TranslationJob.id == normalized_job_id,
            TranslationJob.owner_username == username,
        )
        .with_for_update()
    )
    if job is None:
        return api_error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            JOB_NOT_FOUND_MESSAGE,
        )
    if job.status not in DELETABLE_JOB_STATUSES:
        return api_error(
            status.HTTP_409_CONFLICT,
            "JOB_ACTIVE",
            "Pekerjaan yang sedang diproses belum dapat dihapus.",
        )

    try:
        remove_job_artifacts(get_settings(), job.id)
    except JobArtifactRemovalError:
        db.rollback()
        logger.exception(
            json.dumps(
                {
                    "event": "job_artifact_removal_failed",
                    "jobId": job.id,
                }
            )
        )
        return api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "JOB_DELETE_FAILED",
            "Pekerjaan belum dapat dihapus dari penyimpanan.",
        )

    db.delete(job)
    db.commit()
    logger.info(
        json.dumps(
            {
                "event": "job_deleted",
                "jobId": normalized_job_id,
            }
        )
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{job_id}/preparation",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
def retry_preparation(
    job_id: UUID,
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
) -> JobResponse | JSONResponse:
    normalized_job_id = str(job_id)
    claimed = db.execute(
        update(TranslationJob)
        .where(
            TranslationJob.id == normalized_job_id,
            TranslationJob.owner_username == username,
            TranslationJob.status == JobStatus.FAILED,
            TranslationJob.prepared_at.is_(None),
            TranslationJob.failure_code.in_(RETRYABLE_PREPARATION_FAILURE_CODES),
        )
        .values(
            status=JobStatus.QUEUED,
            started_at=None,
            failure_code=None,
        )
    )
    if claimed.rowcount != 1:
        db.rollback()
        existing = db.scalar(
            select(TranslationJob).where(
                TranslationJob.id == normalized_job_id,
                TranslationJob.owner_username == username,
            )
        )
        if existing is None:
            return api_error(
                status.HTTP_404_NOT_FOUND,
                "JOB_NOT_FOUND",
                JOB_NOT_FOUND_MESSAGE,
            )
        return api_error(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_RETRYABLE",
            "Persiapan pekerjaan ini tidak dapat diulang.",
        )

    db.commit()
    job = db.get(TranslationJob, normalized_job_id)
    if job is None:
        raise RuntimeError("Claimed preparation job could not be loaded.")

    try:
        dispatch_preparation_job(job.id)
    except Exception:
        logger.exception(
            json.dumps(
                {
                    "event": "job_dispatch_failed",
                    "jobId": job.id,
                    "failureCode": "QUEUE_UNAVAILABLE",
                }
            )
        )
        db.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == normalized_job_id,
                TranslationJob.status == JobStatus.QUEUED,
            )
            .values(status=JobStatus.FAILED, failure_code="QUEUE_UNAVAILABLE")
        )
        db.commit()
        db.refresh(job)

    return JobResponse.model_validate(job)


@router.post(
    "/{job_id}/translation",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
def start_translation(
    job_id: UUID,
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
) -> JobResponse | JSONResponse:
    settings = get_settings()
    if not settings.gemini_api_key:
        return api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "AI_NOT_CONFIGURED",
            "GEMINI_API_KEY belum dikonfigurasi pada server.",
        )

    normalized_job_id = str(job_id)
    job = db.scalar(
        select(TranslationJob)
        .where(
            TranslationJob.id == normalized_job_id,
            TranslationJob.owner_username == username,
        )
        .with_for_update()
    )
    if job is None:
        return api_error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            JOB_NOT_FOUND_MESSAGE,
        )
    can_start = (
        job.status == JobStatus.READY_FOR_TRANSLATION
        or job.status == JobStatus.TRANSLATION_STOPPED
        or (
            job.status == JobStatus.FAILED
            and job.prepared_at is not None
            and job.failure_code in RETRYABLE_TRANSLATION_FAILURE_CODES
        )
    )
    if not can_start:
        return api_error(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_READY",
            "Pekerjaan belum siap atau kegagalannya tidak dapat dicoba ulang.",
        )

    was_stopped = job.status == JobStatus.TRANSLATION_STOPPED
    previous_result_filename = job.result_filename
    previous_failure_code = job.failure_code
    previous_translation_started_at = job.translation_started_at
    job.status = JobStatus.TRANSLATION_QUEUED
    job.translation_started_at = None
    job.completed_at = None
    job.result_filename = None
    job.failure_code = None
    job.translation_retry_attempt = 0
    job.translation_next_retry_at = None
    job.translation_wait_reason = None
    job.translation_heartbeat_at = None
    db.commit()
    db.refresh(job)

    try:
        dispatch_translation_job(job.id)
    except Exception:
        logger.exception(
            json.dumps(
                {
                    "event": "translation_dispatch_failed",
                    "jobId": job.id,
                    "failureCode": "QUEUE_UNAVAILABLE",
                }
            )
        )
        if was_stopped:
            restored = db.execute(
                update(TranslationJob)
                .where(
                    TranslationJob.id == normalized_job_id,
                    TranslationJob.status == JobStatus.TRANSLATION_QUEUED,
                )
                .values(
                    status=JobStatus.TRANSLATION_STOPPED,
                    result_filename=previous_result_filename,
                    failure_code=previous_failure_code,
                    translation_started_at=previous_translation_started_at,
                )
                .execution_options(synchronize_session=False)
            )
        else:
            restored = db.execute(
                update(TranslationJob)
                .where(
                    TranslationJob.id == normalized_job_id,
                    TranslationJob.status == JobStatus.TRANSLATION_QUEUED,
                )
                .values(
                    status=JobStatus.FAILED,
                    failure_code="QUEUE_UNAVAILABLE",
                )
                .execution_options(synchronize_session=False)
            )
        db.commit()
        db.expire_all()
        current_job = db.get(TranslationJob, normalized_job_id)
        if current_job is None:
            raise RuntimeError("Dispatched translation job could not be loaded.")
        if was_stopped and restored.rowcount == 1:
            return api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "QUEUE_UNAVAILABLE",
                "Terjemahan belum dapat dilanjutkan karena antrean tidak tersedia.",
            )
        return JobResponse.model_validate(current_job)

    return JobResponse.model_validate(job)


@router.post(
    "/{job_id}/translation/stop",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=JobResponse,
)
def stop_translation(
    job_id: UUID,
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
) -> JobResponse | JSONResponse:
    normalized_job_id = str(job_id)
    job = db.scalar(
        select(TranslationJob)
        .where(
            TranslationJob.id == normalized_job_id,
            TranslationJob.owner_username == username,
        )
        .with_for_update()
    )
    if job is None:
        return api_error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            JOB_NOT_FOUND_MESSAGE,
        )
    if job.status == JobStatus.TRANSLATION_STOPPING:
        db.commit()
        try:
            dispatch_translation_stop(job.id)
        except Exception:
            logger.exception(
                json.dumps(
                    {
                        "event": "translation_stop_redispatch_failed",
                        "jobId": job.id,
                    }
                )
            )
        return JobResponse.model_validate(job)
    if job.status not in STOPPABLE_TRANSLATION_STATUSES:
        return api_error(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_TRANSLATING",
            "Tidak ada proses terjemahan aktif yang dapat dihentikan.",
        )

    previous_status = job.status
    previous_retry_attempt = job.translation_retry_attempt
    previous_next_retry_at = job.translation_next_retry_at
    previous_wait_reason = job.translation_wait_reason
    previous_heartbeat_at = job.translation_heartbeat_at
    previous_failure_code = job.failure_code
    previous_completed_at = job.completed_at
    previous_result_filename = job.result_filename
    job.status = JobStatus.TRANSLATION_STOPPING
    job.completed_at = None
    job.result_filename = None
    job.failure_code = None
    job.translation_next_retry_at = None
    job.translation_wait_reason = None
    job.translation_heartbeat_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(job)

    try:
        dispatch_translation_stop(job.id)
    except Exception:
        logger.exception(
            json.dumps(
                {
                    "event": "translation_stop_dispatch_failed",
                    "jobId": job.id,
                    "failureCode": "QUEUE_UNAVAILABLE",
                }
            )
        )
        if previous_status == JobStatus.TRANSLATING:
            # The active worker can observe STOPPING even when publishing the
            # dedicated finalizer task failed. Keep the stop request durable;
            # maintenance will redispatch it if the worker does not finish it.
            db.expire_all()
            current_job = db.get(TranslationJob, normalized_job_id)
            if current_job is None:
                raise RuntimeError("Stopping translation job could not be loaded.")
            return JobResponse.model_validate(current_job)

        restored = db.execute(
            update(TranslationJob)
            .where(
                TranslationJob.id == normalized_job_id,
                TranslationJob.status == JobStatus.TRANSLATION_STOPPING,
            )
            .values(
                status=previous_status,
                translation_retry_attempt=previous_retry_attempt,
                translation_next_retry_at=previous_next_retry_at,
                translation_wait_reason=previous_wait_reason,
                translation_heartbeat_at=previous_heartbeat_at,
                failure_code=previous_failure_code,
                completed_at=previous_completed_at,
                result_filename=previous_result_filename,
            )
            .execution_options(synchronize_session=False)
        )
        db.commit()
        if restored.rowcount == 1:
            return api_error(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "QUEUE_UNAVAILABLE",
                "Permintaan berhenti belum dapat dikirim ke worker.",
            )
        db.expire_all()
        current_job = db.get(TranslationJob, normalized_job_id)
        if current_job is None:
            raise RuntimeError("Stopping translation job could not be loaded.")
        return JobResponse.model_validate(current_job)

    return JobResponse.model_validate(job)


@router.get("/{job_id}/result", response_class=FileResponse, response_model=None)
def download_result(
    job_id: UUID,
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
    disposition: Annotated[
        Literal["attachment", "inline"],
        Query(),
    ] = "attachment",
) -> FileResponse | JSONResponse:
    job = db.scalar(
        select(TranslationJob).where(
            TranslationJob.id == str(job_id),
            TranslationJob.owner_username == username,
        )
    )
    if job is None:
        return api_error(
            status.HTTP_404_NOT_FOUND,
            "JOB_NOT_FOUND",
            JOB_NOT_FOUND_MESSAGE,
        )
    if job.status not in {
        JobStatus.COMPLETED,
        JobStatus.TRANSLATION_STOPPED,
    } or not job.result_filename:
        return api_error(
            status.HTTP_409_CONFLICT,
            "RESULT_NOT_READY",
            "PDF hasil belum tersedia.",
        )

    expected_filename = f"{job.id}.pdf"
    if job.result_filename != expected_filename:
        logger.error(
            json.dumps(
                {
                    "event": "invalid_result_filename",
                    "jobId": job.id,
                }
            )
        )
        return api_error(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            "RESULT_UNAVAILABLE",
            "PDF hasil tidak dapat diakses.",
        )

    settings = get_settings()
    results_root = (settings.storage_root / "results").resolve()
    result_path = (results_root / expected_filename).resolve()
    if result_path.parent != results_root or not result_path.is_file():
        return api_error(
            status.HTTP_410_GONE,
            "RESULT_MISSING",
            "PDF hasil tidak ditemukan pada penyimpanan.",
        )

    original_stem = Path(job.original_filename).stem[:180] or "manga"
    return FileResponse(
        result_path,
        media_type="application/pdf",
        filename=f"{original_stem}-indonesia.pdf",
        content_disposition_type=disposition,
        headers={"Cache-Control": "private, no-store"},
    )
