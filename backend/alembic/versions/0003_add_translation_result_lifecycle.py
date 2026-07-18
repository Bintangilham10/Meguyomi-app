"""Add AI translation and result lifecycle."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "translation_jobs",
        sa.Column("translation_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "translation_jobs",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "translation_jobs",
        sa.Column("result_filename", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("translation_jobs", "result_filename")
    op.drop_column("translation_jobs", "completed_at")
    op.drop_column("translation_jobs", "translation_started_at")
