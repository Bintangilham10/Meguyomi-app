from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import UploadFile, status
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.config import Settings


PDF_CONTENT_TYPE = "application/pdf"
PDF_SIGNATURE = b"%PDF-"


@dataclass(frozen=True)
class StoredPdf:
    id: UUID
    original_filename: str
    stored_filename: str
    size_bytes: int
    page_count: int
    created_at: datetime
    path: Path


class UploadValidationError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


async def validate_and_store_pdf(file: UploadFile, settings: Settings) -> StoredPdf:
    original_filename = safe_display_filename(file.filename)
    if file.content_type != PDF_CONTENT_TYPE or not original_filename.lower().endswith(
        ".pdf"
    ):
        raise UploadValidationError(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "INVALID_FILE_TYPE",
            "File harus berupa PDF.",
        )

    job_id = uuid4()
    temporary_dir = settings.storage_root / "temporary"
    originals_dir = settings.storage_root / "originals"
    temporary_dir.mkdir(parents=True, exist_ok=True)
    originals_dir.mkdir(parents=True, exist_ok=True)
    temporary_path = temporary_dir / f"{job_id}.upload"
    stored_filename = f"{job_id}.pdf"
    final_path = originals_dir / stored_filename

    try:
        size_bytes = await stream_upload(file, temporary_path, settings)
        page_count = inspect_pdf(temporary_path, settings.max_pdf_pages)
        temporary_path.replace(final_path)
        return StoredPdf(
            id=job_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            size_bytes=size_bytes,
            page_count=page_count,
            created_at=datetime.now(timezone.utc),
            path=final_path,
        )
    except Exception:
        temporary_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


async def stream_upload(
    file: UploadFile, destination: Path, settings: Settings
) -> int:
    total_bytes = 0
    signature_buffer = b""
    with destination.open("xb") as output:
        while chunk := await file.read(settings.upload_chunk_bytes):
            total_bytes += len(chunk)
            if total_bytes > settings.max_upload_bytes:
                raise UploadValidationError(
                    status.HTTP_413_CONTENT_TOO_LARGE,
                    "FILE_TOO_LARGE",
                    "Ukuran PDF melebihi batas 50 MB.",
                )
            if len(signature_buffer) < 1024:
                signature_buffer += chunk[: 1024 - len(signature_buffer)]
            output.write(chunk)

    if total_bytes == 0 or PDF_SIGNATURE not in signature_buffer:
        raise UploadValidationError(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_PDF",
            "Isi file bukan PDF yang valid.",
        )
    return total_bytes


def inspect_pdf(path: Path, max_pages: int) -> int:
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise UploadValidationError(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "ENCRYPTED_PDF",
                "PDF terenkripsi tidak dapat diproses.",
            )
        page_count = len(reader.pages)
    except UploadValidationError:
        raise
    except (PdfReadError, OSError, ValueError) as error:
        raise UploadValidationError(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_PDF",
            "Isi file bukan PDF yang valid.",
        ) from error

    if page_count < 1:
        raise UploadValidationError(
            status.HTTP_400_BAD_REQUEST,
            "INVALID_PDF",
            "PDF tidak memiliki halaman.",
        )
    if page_count > max_pages:
        raise UploadValidationError(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "TOO_MANY_PAGES",
            f"PDF maksimal {max_pages} halaman.",
        )
    return page_count


def safe_display_filename(filename: str | None) -> str:
    if not filename:
        return "upload.pdf"
    basename = filename.replace("\\", "/").split("/")[-1].strip()
    return basename[:255] or "upload.pdf"
