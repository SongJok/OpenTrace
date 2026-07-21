"""add messages table, chat_sessions tags/pinned

Revision ID: 20260511_add_messages
Revises: 20260509_add_attachments
Create Date: 2026-05-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260511_add_messages"
down_revision = "20260509_add_attachments"
branch_labels = None
depends_on = None


def _public_tables(inspector: sa.Inspector) -> set[str]:
    try:
        return set(inspector.get_table_names(schema="public"))
    except Exception:
        return set()


def _column_exists(inspector: sa.Inspector, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspector.get_columns(table, schema="public"))
    except Exception:
        return False


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    try:
        return any(
            ix.get("name") == index_name
            for ix in inspector.get_indexes(table, schema="public")
        )
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _public_tables(inspector)

    # ── messages table ──────────────────────────────────────────────────
    if "messages" not in tables:
        op.create_table(
            "messages",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("turn_id", sa.String(length=64), nullable=False),
            sa.Column("role", sa.String(length=20), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("tool_calls", sa.JSON(), nullable=True),
            sa.Column("tool_call_id", sa.String(length=128), nullable=True),
            sa.Column("name", sa.String(length=128), nullable=True),
            sa.Column(
                "content_type", sa.String(length=30), nullable=False, server_default="'text'"
            ),
            sa.Column("content_blocks", sa.JSON(), nullable=True),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("parent_message_id", sa.String(length=36), nullable=True),
            sa.Column("model", sa.String(length=100), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column(
                "status", sa.String(length=20), nullable=False, server_default="'done'"
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["public.chat_sessions.id"], ondelete="CASCADE"
            ),
            schema="public",
        )

    inspector = sa.inspect(bind)

    if not _index_exists(inspector, "messages", "ix_messages_session_id"):
        op.create_index(
            "ix_messages_session_id", "messages", ["session_id"], schema="public",
        )
    if not _index_exists(inspector, "messages", "ix_messages_turn_id"):
        op.create_index(
            "ix_messages_turn_id", "messages", ["turn_id"], schema="public",
        )
    if not _index_exists(inspector, "messages", "ix_messages_session_created"):
        op.create_index(
            "ix_messages_session_created", "messages", ["session_id", "created_at"], schema="public",
        )
    if not _index_exists(inspector, "messages", "ix_messages_parent_message_id"):
        op.create_index(
            "ix_messages_parent_message_id", "messages", ["parent_message_id"], schema="public",
        )

    # ── ChatSession.tags column ─────────────────────────────────────────
    if not _column_exists(inspector, "chat_sessions", "tags"):
        op.add_column(
            "chat_sessions",
            sa.Column(
                "tags",
                sa.ARRAY(sa.String()),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            schema="public",
        )

    # ── ChatSession.pinned column ───────────────────────────────────────
    if not _column_exists(inspector, "chat_sessions", "pinned"):
        op.add_column(
            "chat_sessions",
            sa.Column("pinned", sa.Boolean(), nullable=False, server_default="false"),
            schema="public",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _public_tables(inspector)

    if "messages" in tables:
        op.drop_table("messages", schema="public")

    if _column_exists(inspector, "chat_sessions", "pinned"):
        op.drop_column("chat_sessions", "pinned", schema="public")

    if _column_exists(inspector, "chat_sessions", "tags"):
        op.drop_column("chat_sessions", "tags", schema="public")
