import json
from datetime import datetime
from typing import Annotated, Literal
from urllib.request import urlopen

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.api.dependencies import AuthenticatedUser
from app.core.config import get_settings
from app.core.languages import SourceLanguage
from app.db.session import get_db
from app.models.translation_memory import TranslationMemory
from app.services.translation_memory import normalize_source_text, save_entry, suggest_entries

router = APIRouter(prefix="/memory", tags=["translation-memory"])
Database = Annotated[Session, Depends(get_db)]


class MemoryWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_text: str = Field(min_length=1, max_length=1000)
    translated_text: str = Field(min_length=1, max_length=1000)
    category: Literal["verified", "glossary"] = "verified"
    source_language: SourceLanguage = "ja"
    target_language: Literal["id"] = "id"

    @field_validator("source_text", "translated_text")
    @classmethod
    def nonblank(cls, value):
        normalized = normalize_source_text(value)
        if not normalized:
            raise ValueError("Text must not be blank.")
        if len(normalized) > 1000:
            raise ValueError("Normalized text must not exceed 1000 characters.")
        return value.strip()


class MemoryImportEntry(MemoryWrite):
    category: Literal["machine", "verified", "glossary"] = "verified"
    model_version: str | None = Field(default=None, max_length=64)


class MemoryResponse(MemoryImportEntry):
    model_config = ConfigDict(from_attributes=True)
    id: int
    usage_count: int
    updated_at: datetime


@router.get("")
def list_memory(
    username: AuthenticatedUser, db: Database,
    page: Annotated[int, Query(ge=1, le=100000)] = 1,
    q: Annotated[str, Query(max_length=1000)] = "",
    source_language: SourceLanguage | None = None,
):
    statement = select(TranslationMemory)
    if source_language:
        statement = statement.where(TranslationMemory.source_language == source_language)
    if q.strip():
        statement = statement.where(or_(
            TranslationMemory.normalized_text.contains(normalize_source_text(q), autoescape=True),
            TranslationMemory.translated_text.contains(q.strip(), autoescape=True),
        ))
    total = db.scalar(select(func.count()).select_from(statement.subquery())) or 0
    entries = db.scalars(statement.order_by(TranslationMemory.updated_at.desc(), TranslationMemory.id.desc()).offset((page-1)*20).limit(20)).all()
    return {"data": [MemoryResponse.model_validate(row) for row in entries], "total": total, "page": page, "page_size": 20}


@router.get("/status")
def local_status(username: AuthenticatedUser):
    try:
        with urlopen(get_settings().local_ai_url.rstrip("/") + "/health", timeout=5) as response:
            result = json.loads(response.read(8193))
        return {"ready": result.get("ready") is True, "installed": result.get("modelsInstalled") is True,
                "languages": result.get("languages", {})}
    except (OSError, ValueError, AttributeError):
        return {"ready": False, "installed": False}


@router.get("/suggestions")
def suggestions(username: AuthenticatedUser, db: Database, q: Annotated[str, Query(min_length=1, max_length=1000)], source_language: SourceLanguage = "ja"):
    return {"data": suggest_entries(db, q, source_language=source_language)}


@router.get("/export")
def export_memory(username: AuthenticatedUser, db: Database, source_language: SourceLanguage | None = None):
    def rows():
        statement = select(TranslationMemory).order_by(TranslationMemory.id)
        if source_language:
            statement = statement.where(TranslationMemory.source_language == source_language)
        entries = db.scalars(
            statement.execution_options(yield_per=100)
        )
        yield "["
        separator = ""
        for row in entries:
            payload = MemoryImportEntry.model_validate({
                "source_text": row.source_text, "translated_text": row.translated_text,
                "category": row.category, "model_version": row.model_version,
                "source_language": row.source_language, "target_language": row.target_language,
            })
            yield separator + payload.model_dump_json()
            separator = ",\n"
        yield "]"
    return StreamingResponse(rows(), media_type="application/json", headers={
        "Content-Disposition": 'attachment; filename="meguyomi-bank.json"', "Cache-Control": "no-store",
    })


@router.post("/import")
def import_memory(username: AuthenticatedUser, db: Database, entries: Annotated[list[MemoryImportEntry], Body(min_length=1, max_length=500)]):
    for entry in entries:
        save_entry(db, **entry.model_dump())
    db.commit()
    return {"imported": len(entries)}


@router.post("", response_model=MemoryResponse)
def write_memory(username: AuthenticatedUser, db: Database, entry: MemoryWrite):
    row = save_entry(db, **entry.model_dump())
    db.commit()
    return MemoryResponse.model_validate(row)


@router.delete("/{entry_id}", status_code=204)
def delete_memory(entry_id: int, username: AuthenticatedUser, db: Database):
    deleted = db.execute(delete(TranslationMemory).where(TranslationMemory.id == entry_id))
    if deleted.rowcount != 1:
        raise HTTPException(404, "Entri bank tidak ditemukan.")
    db.commit()
    return Response(status_code=204)
