"""Add persistent Japanese to Indonesian translation memory."""
from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "translation_memory",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_text", sa.String(1000), nullable=False),
        sa.Column("normalized_text", sa.String(1000), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("translated_text", sa.String(1000), nullable=False),
        sa.Column("source_language", sa.String(16), nullable=False, server_default="ja"),
        sa.Column("target_language", sa.String(16), nullable=False, server_default="id"),
        sa.Column("category", sa.String(16), nullable=False, server_default="machine"),
        sa.Column("model_version", sa.String(64), nullable=True),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_hash", "source_language", "target_language", name="uq_translation_memory_lookup"),
    )


def downgrade() -> None:
    op.drop_table("translation_memory")
