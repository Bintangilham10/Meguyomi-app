"""Add translation job preparation lifecycle."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "translation_jobs",
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "translation_jobs",
        sa.Column("prepared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "translation_jobs",
        sa.Column("failure_code", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("translation_jobs", "failure_code")
    op.drop_column("translation_jobs", "prepared_at")
    op.drop_column("translation_jobs", "started_at")
