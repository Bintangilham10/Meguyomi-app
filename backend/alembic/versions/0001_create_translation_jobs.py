"""Create translation jobs table."""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "translation_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_username", sa.String(length=64), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default="QUEUED",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stored_filename"),
    )
    op.create_index(
        op.f("ix_translation_jobs_created_at"),
        "translation_jobs",
        ["created_at"],
    )
    op.create_index(
        op.f("ix_translation_jobs_owner_username"),
        "translation_jobs",
        ["owner_username"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_translation_jobs_owner_username"),
        table_name="translation_jobs",
    )
    op.drop_index(
        op.f("ix_translation_jobs_created_at"),
        table_name="translation_jobs",
    )
    op.drop_table("translation_jobs")
