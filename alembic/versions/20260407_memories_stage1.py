"""memories stage1: user memories + settings

Revision ID: 20260407_mem_stage1
Revises: 20260407_fix_chat_cols
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260407_mem_stage1"
down_revision = "20260407_fix_chat_cols"
branch_labels = None
depends_on = None


def _tables(inspector: sa.Inspector) -> set[str]:
    try:
        return set(inspector.get_table_names())
    except Exception:
        return set()


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    try:
        return any(ix.get("name") == index_name for ix in inspector.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = _tables(inspector)

    if "user_memories" not in existing:
        op.create_table(
            "user_memories",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
            sa.Column("memory_type", sa.String(length=20), nullable=False, index=True),  # semantic|episodic|procedural
            sa.Column("kind", sa.String(length=30), nullable=False, server_default="fact"),  # fact|preference|workflow
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("tags_json", sa.Text(), nullable=True),
            sa.Column("metadata_json", sa.Text(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "user_memories", "ix_user_memories_user_type"):
        op.create_index("ix_user_memories_user_type", "user_memories", ["user_id", "memory_type"], unique=False)

    existing = _tables(sa.inspect(bind))
    if "user_memory_settings" not in existing:
        op.create_table(
            "user_memory_settings",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=False, unique=True, index=True),
            sa.Column("memory_learning_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("preference_learning_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = _tables(inspector)

    if "user_memory_settings" in existing:
        op.drop_table("user_memory_settings")

    inspector = sa.inspect(bind)
    existing = _tables(inspector)
    if "user_memories" in existing:
        if _index_exists(inspector, "user_memories", "ix_user_memories_user_type"):
            op.drop_index("ix_user_memories_user_type", table_name="user_memories")
        op.drop_table("user_memories")
