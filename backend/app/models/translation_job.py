from datetime import datetime, timezone

from sqlalchemy import BigInteger, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.job_status import JobStatus


RETRYABLE_TRANSLATION_FAILURE_CODES = frozenset(
    {
        "AI_NOT_CONFIGURED",
        "AI_RATE_LIMITED",
        "AI_SERVICE_UNAVAILABLE",
        "AI_TRANSLATION_FAILED",
        "QUEUE_UNAVAILABLE",
        "RESULT_BUILD_FAILED",
        "TRANSLATION_FAILED",
    }
)

RETRYABLE_PREPARATION_FAILURE_CODES = frozenset(
    {
        "PREPARATION_FAILED",
        "QUEUE_UNAVAILABLE",
    }
)


class TranslationJob(Base):
    __tablename__ = "translation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_username: Mapped[str] = mapped_column(String(64), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    stored_filename: Mapped[str] = mapped_column(String(255), unique=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    page_count: Mapped[int] = mapped_column(Integer)
    translated_page_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default=JobStatus.QUEUED)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    prepared_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    translation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    checkpoint_updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    translation_retry_attempt: Mapped[int] = mapped_column(Integer, default=0)
    translation_next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    translation_wait_reason: Mapped[str | None] = mapped_column(
        String(32),
        nullable=True,
    )
    translation_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    result_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)

    @property
    def result_available(self) -> bool:
        return self.status == JobStatus.COMPLETED and bool(self.result_filename)

    @property
    def can_retry_translation(self) -> bool:
        return (
            self.status == JobStatus.FAILED
            and self.prepared_at is not None
            and self.failure_code in RETRYABLE_TRANSLATION_FAILURE_CODES
        )

    @property
    def can_retry_preparation(self) -> bool:
        return (
            self.status == JobStatus.FAILED
            and self.prepared_at is None
            and self.failure_code in RETRYABLE_PREPARATION_FAILURE_CODES
        )
