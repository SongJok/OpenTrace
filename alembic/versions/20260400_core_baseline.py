"""core baseline tables

Revision ID: 20260400_core_baseline
Revises:
Create Date: 2026-04-11
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260400_core_baseline"
down_revision = None
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, name: str) -> bool:
    try:
        return name in set(inspector.get_table_names())
    except Exception:
        return False


def _index_exists(inspector: sa.Inspector, table: str, name: str) -> bool:
    try:
        return any(ix.get("name") == name for ix in inspector.get_indexes(table))
    except Exception:
        return False


class _OfflineInspector:
    """Minimal inspector used when Alembic renders offline SQL."""

    def get_table_names(self) -> list[str]:
        return []

    def get_indexes(self, _table: str) -> list[dict[str, str]]:
        return []


def _safe_inspector(bind):
    try:
        return sa.inspect(bind)
    except sa.exc.NoInspectionAvailable:
        return _OfflineInspector()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = _safe_inspector(bind)

    if not _table_exists(inspector, "users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("email", sa.String(length=255), nullable=False),
            sa.Column("hashed_password", sa.String(length=255), nullable=False),
            sa.Column("display_name", sa.String(length=100), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("email", name="uq_users_email"),
        )

    inspector = _safe_inspector(bind)
    if not _index_exists(inspector, "users", "ix_users_email"):
        op.create_index("ix_users_email", "users", ["email"], unique=True)

    inspector = _safe_inspector(bind)
    if not _table_exists(inspector, "chat_sessions"):
        op.create_table(
            "chat_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=True),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_decision_type", sa.String(length=50), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("last_active", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        )

    inspector = _safe_inspector(bind)
    if not _index_exists(inspector, "chat_sessions", "ix_chat_sessions_user_id"):
        op.create_index("ix_chat_sessions_user_id", "chat_sessions", ["user_id"], unique=False)

    inspector = _safe_inspector(bind)
    if not _table_exists(inspector, "trace_logs"):
        op.create_table(
            "trace_logs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("trace_id", sa.String(length=64), nullable=True),
            sa.Column("span_id", sa.String(length=32), nullable=True),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("response", sa.Text(), nullable=True),
            sa.Column("decision_type", sa.String(length=50), nullable=True),
            sa.Column("validation_score", sa.Float(), nullable=True),
            sa.Column("latency_ms", sa.Integer(), nullable=True),
            sa.Column("model", sa.String(length=100), nullable=True),
            sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["session_id"], ["chat_sessions.id"], ondelete="CASCADE"),
        )

    inspector = _safe_inspector(bind)
    if not _index_exists(inspector, "trace_logs", "ix_trace_logs_session_id"):
        op.create_index("ix_trace_logs_session_id", "trace_logs", ["session_id"], unique=False)
    if not _index_exists(inspector, "trace_logs", "ix_trace_logs_trace_id"):
        op.create_index("ix_trace_logs_trace_id", "trace_logs", ["trace_id"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = _safe_inspector(bind)

    if _table_exists(inspector, "trace_logs"):
        if _index_exists(inspector, "trace_logs", "ix_trace_logs_trace_id"):
            op.drop_index("ix_trace_logs_trace_id", table_name="trace_logs")
        if _index_exists(inspector, "trace_logs", "ix_trace_logs_session_id"):
            op.drop_index("ix_trace_logs_session_id", table_name="trace_logs")
        op.drop_table("trace_logs")

    inspector = _safe_inspector(bind)
    if _table_exists(inspector, "chat_sessions"):
        if _index_exists(inspector, "chat_sessions", "ix_chat_sessions_user_id"):
            op.drop_index("ix_chat_sessions_user_id", table_name="chat_sessions")
        op.drop_table("chat_sessions")

    inspector = _safe_inspector(bind)
    if _table_exists(inspector, "users"):
        if _index_exists(inspector, "users", "ix_users_email"):
            op.drop_index("ix_users_email", table_name="users")
        op.drop_table("users")
