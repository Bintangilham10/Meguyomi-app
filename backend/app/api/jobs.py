import json
import logging
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedUser
from app.core.config import get_settings
from app.db.session import get_db
from app.models.translation_job import (
    RETRYABLE_TRANSLATION_FAILURE_CODES,
    TranslationJob,
)
from app.models.job_status import JobStatus
from app.schemas.job import JobListResponse, JobResponse, PaginationResponse
from app.services.job_artifacts import JobArtifactRemovalError, remove_job_artifacts
from app.services.pdf_upload import UploadValidationError, validate_and_store_pdf
from app.tasks.preparation import dispatch_preparation_job
from app.tasks.translation import dispatch_translation_job


router = APIRouter(prefix="/jobs", tags=["jobs"])
logger = logging.getLogger(__name__)
DELETABLE_JOB_STATUSES = frozenset(
    {
        JobStatus.READY_FOR_TRANSLATION,
        JobStatus.COMPLETED,
        JobStatus.FAILED,
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
            "Pekerjaan terjemahan tidak ditemukan.",
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
    claimed = db.execute(
        update(TranslationJob)
        .where(
            TranslationJob.id == normalized_job_id,
            TranslationJob.owner_username == username,
            or_(
                TranslationJob.status == JobStatus.READY_FOR_TRANSLATION,
                and_(
                    TranslationJob.status == JobStatus.FAILED,
                    TranslationJob.prepared_at.is_not(None),
                    TranslationJob.failure_code.in_(
                        RETRYABLE_TRANSLATION_FAILURE_CODES
                    ),
                ),
            ),
        )
        .values(
            status=JobStatus.TRANSLATION_QUEUED,
            translation_started_at=None,
            completed_at=None,
            result_filename=None,
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
                "Pekerjaan terjemahan tidak ditemukan.",
            )
        return api_error(
            status.HTTP_409_CONFLICT,
            "JOB_NOT_READY",
            "Pekerjaan belum siap atau kegagalannya tidak dapat dicoba ulang.",
        )

    db.commit()
    job = db.get(TranslationJob, normalized_job_id)
    if job is None:
        raise RuntimeError("Claimed translation job could not be loaded.")

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
        job.status = JobStatus.FAILED
        job.failure_code = "QUEUE_UNAVAILABLE"
        db.commit()
        db.refresh(job)

    return JobResponse.model_validate(job)


@router.get("/{job_id}/result", response_class=FileResponse, response_model=None)
def download_result(
    job_id: UUID,
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
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
            "Pekerjaan terjemahan tidak ditemukan.",
        )
    if job.status != JobStatus.COMPLETED or not job.result_filename:
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
        headers={"Cache-Control": "private, no-store"},
    )
