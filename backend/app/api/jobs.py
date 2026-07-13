from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedUser
from app.core.config import get_settings
from app.db.session import get_db
from app.models.translation_job import TranslationJob
from app.schemas.job import JobListResponse, JobResponse
from app.services.pdf_upload import UploadValidationError, validate_and_store_pdf


router = APIRouter(prefix="/jobs", tags=["jobs"])


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
        status="QUEUED",
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

    return JobResponse.model_validate(job)


@router.get("", response_model=JobListResponse)
def list_jobs(
    username: AuthenticatedUser,
    db: Annotated[Session, Depends(get_db)],
) -> JobListResponse:
    jobs = db.scalars(
        select(TranslationJob)
        .where(TranslationJob.owner_username == username)
        .order_by(TranslationJob.created_at.desc())
    ).all()
    return JobListResponse(data=[JobResponse.model_validate(job) for job in jobs])
