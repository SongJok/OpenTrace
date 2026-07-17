"""ensure chat_sessions stage1 columns exist

Revision ID: 20260407_fix_chat_cols
Revises: 20260407_p2_learning_tables
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260407_fix_chat_cols"
down_revision = "20260407_p2_learning_tables"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {c.get("name") for c in inspector.get_columns(table)}
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

    cols = _column_names(inspector, "chat_sessions")
    if "display_title" not in cols:
        op.add_column("chat_sessions", sa.Column("display_title", sa.String(length=255), nullable=True))
    if "archived_at" not in cols:
        op.add_column("chat_sessions", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "chat_sessions", "ix_chat_sessions_archived_at"):
        op.create_index("ix_chat_sessions_archived_at", "chat_sessions", ["archived_at"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = _column_names(inspector, "chat_sessions")

    if _index_exists(inspector, "chat_sessions", "ix_chat_sessions_archived_at"):
        op.drop_index("ix_chat_sessions_archived_at", table_name="chat_sessions")

    if "archived_at" in cols:
        op.drop_column("chat_sessions", "archived_at")
    if "display_title" in cols:
        op.drop_column("chat_sessions", "display_title")
