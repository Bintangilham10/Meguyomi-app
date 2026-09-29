import hashlib
import re
import unicodedata
from collections.abc import Callable
from datetime import datetime, timezone
from difflib import SequenceMatcher

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models.translation_memory import TranslationMemory
from app.core.languages import MODEL_VERSIONS
from app.services.indonesian_style import naturalize_indonesian

SessionFactory = Callable[[], Session]
MODEL_VERSION = MODEL_VERSIONS["ja"]


def normalize_source_text(value: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value)).strip()


def source_hash(value: str) -> str:
    return hashlib.sha256(normalize_source_text(value).encode("utf-8")).hexdigest()


def save_entry(session: Session, source_text: str, translated_text: str, *, category="verified", model_version=None, source_language="ja", target_language="id") -> TranslationMemory:
    if source_language not in MODEL_VERSIONS or target_language != "id":
        raise ValueError("Unsupported language pair.")
    source_text, translated_text = source_text.strip(), translated_text.strip()
    normalized = normalize_source_text(source_text)
    if not normalized or not translated_text or max(len(source_text), len(normalized), len(translated_text)) > 1000:
        raise ValueError("Text must contain between 1 and 1000 characters.")
    if category not in {"machine", "verified", "glossary"}:
        raise ValueError("Invalid memory category.")
    now = datetime.now(timezone.utc)
    values = dict(
        source_text=source_text, normalized_text=normalized, source_hash=source_hash(source_text),
        translated_text=translated_text, source_language=source_language, target_language=target_language,
        category=category, model_version=model_version, usage_count=0, created_at=now, updated_at=now,
    )
    insert = pg_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(TranslationMemory).values(**values)
    changes = {key: values[key] for key in ("source_text", "normalized_text", "translated_text", "category", "model_version", "updated_at")}
    # Concurrent workers must not overwrite a correction with machine output.
    statement = statement.on_conflict_do_update(
        index_elements=["source_hash", "source_language", "target_language"],
        set_=changes,
        where=TranslationMemory.category == "machine" if category == "machine" else None,
    )
    session.execute(statement)
    session.flush()
    entry = session.scalar(select(TranslationMemory).where(
        TranslationMemory.source_hash == values["source_hash"],
        TranslationMemory.source_language == source_language, TranslationMemory.target_language == target_language,
    ).execution_options(populate_existing=True))
    if entry is None or entry.normalized_text != normalized:
        raise ValueError("Translation memory lookup collision.")
    return entry


class TranslationMemoryStore:
    def __init__(self, session_factory: SessionFactory | None, *, source_language="ja", model_version=None):
        if source_language not in MODEL_VERSIONS:
            raise ValueError("Unsupported source language.")
        self.session_factory = session_factory
        self.source_language = source_language
        self.model_version = model_version or MODEL_VERSIONS[source_language]

    def resolve(self, source_text: str, *, region_type: str = "dialogue") -> str | None:
        if self.session_factory is None:
            return None
        with self.session_factory() as session:
            entry = session.scalar(select(TranslationMemory).where(
                TranslationMemory.source_hash == source_hash(source_text),
                TranslationMemory.source_language == self.source_language, TranslationMemory.target_language == "id",
            ))
            if entry is None or entry.normalized_text != normalize_source_text(source_text):
                return None
            if entry.category == "machine" and entry.model_version != self.model_version:
                return None
            result = (
                naturalize_indonesian(
                    entry.translated_text,
                    region_type=region_type,
                )
                if entry.category == "machine"
                else entry.translated_text
            )
            session.execute(update(TranslationMemory).where(TranslationMemory.id == entry.id).values(
                usage_count=TranslationMemory.usage_count + 1,
            ))
            session.commit()
            return result

    def remember(
        self,
        source_text: str,
        translated_text: str,
        *,
        region_type: str = "dialogue",
    ) -> str:
        translated_text = translated_text.strip()
        if self.session_factory is None:
            return naturalize_indonesian(translated_text, region_type=region_type)
        with self.session_factory() as session:
            # Keep raw model output so a dialogue cannot change a later title
            # with the same source text. Manual entries always bypass styling.
            entry = save_entry(session, source_text, translated_text, category="machine", model_version=self.model_version, source_language=self.source_language)
            result = naturalize_indonesian(
                entry.translated_text,
                region_type=region_type,
            ) if entry.category == "machine" else entry.translated_text
            session.commit()
            return result


def suggest_entries(session: Session, source: str, limit=5, *, source_language="ja") -> list[dict]:
    normalized = normalize_source_text(source)
    if len(normalized) < 3:
        return []
    candidates = session.scalars(select(TranslationMemory).where(
        TranslationMemory.source_language == source_language,
        TranslationMemory.target_language == "id",
        TranslationMemory.category.in_(("verified", "glossary")),
        func.length(TranslationMemory.normalized_text).between(max(1, len(normalized)-10), len(normalized)+10),
    ).order_by(TranslationMemory.usage_count.desc(), TranslationMemory.id).limit(500)).all()
    ranked = sorted(
        ((SequenceMatcher(None, normalized, row.normalized_text, autojunk=False).ratio(), row) for row in candidates),
        key=lambda item: (-item[0], item[1].id),
    )
    return [dict(id=row.id, source_text=row.source_text, translated_text=row.translated_text, source_language=row.source_language, similarity=round(score, 3))
            for score, row in ranked[:limit] if score >= 0.6]
