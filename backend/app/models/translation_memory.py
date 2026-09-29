from datetime import datetime, timezone
from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.db.base import Base


class TranslationMemory(Base):
    __tablename__ = "translation_memory"
    __table_args__ = (
        UniqueConstraint("source_hash", "source_language", "target_language", name="uq_translation_memory_lookup"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_text: Mapped[str] = mapped_column(String(1000))
    normalized_text: Mapped[str] = mapped_column(String(1000))
    source_hash: Mapped[str] = mapped_column(String(64))
    translated_text: Mapped[str] = mapped_column(String(1000))
    source_language: Mapped[str] = mapped_column(String(16), default="ja")
    target_language: Mapped[str] = mapped_column(String(16), default="id")
    category: Mapped[str] = mapped_column(String(16), default="machine")
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
