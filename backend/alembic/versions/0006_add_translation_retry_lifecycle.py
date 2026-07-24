"""Add translation retry and worker recovery lifecycle."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "translation_jobs",
        sa.Column(
            "translation_retry_attempt",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "translation_jobs",
        sa.Column(
            "translation_next_retry_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "translation_jobs",
        sa.Column(
            "translation_wait_reason",
            sa.String(length=32),
            nullable=True,
        ),
    )
    op.add_column(
        "translation_jobs",
        sa.Column(
            "translation_heartbeat_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_translation_jobs_retry_due",
        "translation_jobs",
        ["status", "translation_next_retry_at"],
        unique=False,
    )
    op.execute(
        """
        UPDATE translation_jobs
        SET translation_heartbeat_at = COALESCE(
            checkpoint_updated_at,
            translation_started_at,
            CURRENT_TIMESTAMP
        )
        WHERE status = 'TRANSLATING'
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_translation_jobs_retry_due",
        table_name="translation_jobs",
    )
    op.drop_column("translation_jobs", "translation_heartbeat_at")
    op.drop_column("translation_jobs", "translation_wait_reason")
    op.drop_column("translation_jobs", "translation_next_retry_at")
    op.drop_column("translation_jobs", "translation_retry_attempt")
