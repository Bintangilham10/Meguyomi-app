"""Persist the OCR language for each translation job."""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("translation_jobs", sa.Column("source_language", sa.String(16), nullable=False, server_default="ja"))


def downgrade() -> None:
    op.drop_column("translation_jobs", "source_language")
