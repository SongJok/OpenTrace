"""add p2 learning tables: reasoning_traces tool_stats feedback

Revision ID: 20260407_p2_learning_tables
Revises: 20260406_chat_session_stage1
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260407_p2_learning_tables"
down_revision = "20260406_chat_session_stage1"
branch_labels = None
depends_on = None


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    try:
        return any(ix.get("name") == index_name for ix in inspector.get_indexes(table))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing_tables = set(inspector.get_table_names())

    if "reasoning_traces" not in existing_tables:
        op.create_table(
            "reasoning_traces",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("trace_id", sa.String(length=64), nullable=True),
            sa.Column("phase", sa.String(length=50), nullable=False),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("iteration", sa.Integer(), nullable=True),
            sa.Column("phase_metadata", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    if not _index_exists(inspector, "reasoning_traces", "ix_reasoning_traces_session_id"):
        op.create_index("ix_reasoning_traces_session_id", "reasoning_traces", ["session_id"], unique=False)
    if not _index_exists(inspector, "reasoning_traces", "ix_reasoning_traces_trace_id"):
        op.create_index("ix_reasoning_traces_trace_id", "reasoning_traces", ["trace_id"], unique=False)
    if not _index_exists(inspector, "reasoning_traces", "ix_reasoning_traces_phase"):
        op.create_index("ix_reasoning_traces_phase", "reasoning_traces", ["phase"], unique=False)

    existing_tables = set(sa.inspect(bind).get_table_names())
    if "tool_stats" not in existing_tables:
        op.create_table(
            "tool_stats",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("tool_name", sa.String(length=100), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=True),
            sa.Column("success_count", sa.Integer(), nullable=True),
            sa.Column("failure_count", sa.Integer(), nullable=True),
            sa.Column("avg_latency_ms", sa.Float(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "tool_stats", "ix_tool_stats_tool_name"):
        op.create_index("ix_tool_stats_tool_name", "tool_stats", ["tool_name"], unique=False)
    if not _index_exists(inspector, "tool_stats", "ix_tool_stats_session_id"):
        op.create_index("ix_tool_stats_session_id", "tool_stats", ["session_id"], unique=False)

    existing_tables = set(sa.inspect(bind).get_table_names())
    if "feedback" not in existing_tables:
        op.create_table(
            "feedback",
            sa.Column("id", sa.String(length=36), nullable=False),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("query", sa.Text(), nullable=False),
            sa.Column("response", sa.Text(), nullable=True),
            sa.Column("feedback_type", sa.String(length=30), nullable=False),
            sa.Column("score", sa.Float(), nullable=True),
            sa.Column("correction", sa.Text(), nullable=True),
            sa.Column("feedback_metadata", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=True),
            sa.PrimaryKeyConstraint("id"),
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "feedback", "ix_feedback_session_id"):
        op.create_index("ix_feedback_session_id", "feedback", ["session_id"], unique=False)
    if not _index_exists(inspector, "feedback", "ix_feedback_feedback_type"):
        op.create_index("ix_feedback_feedback_type", "feedback", ["feedback_type"], unique=False)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "feedback" in tables:
        if _index_exists(inspector, "feedback", "ix_feedback_feedback_type"):
            op.drop_index("ix_feedback_feedback_type", table_name="feedback")
        if _index_exists(inspector, "feedback", "ix_feedback_session_id"):
            op.drop_index("ix_feedback_session_id", table_name="feedback")
        op.drop_table("feedback")

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "tool_stats" in tables:
        if _index_exists(inspector, "tool_stats", "ix_tool_stats_session_id"):
            op.drop_index("ix_tool_stats_session_id", table_name="tool_stats")
        if _index_exists(inspector, "tool_stats", "ix_tool_stats_tool_name"):
            op.drop_index("ix_tool_stats_tool_name", table_name="tool_stats")
        op.drop_table("tool_stats")

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "reasoning_traces" in tables:
        if _index_exists(inspector, "reasoning_traces", "ix_reasoning_traces_phase"):
            op.drop_index("ix_reasoning_traces_phase", table_name="reasoning_traces")
        if _index_exists(inspector, "reasoning_traces", "ix_reasoning_traces_trace_id"):
            op.drop_index("ix_reasoning_traces_trace_id", table_name="reasoning_traces")
        if _index_exists(inspector, "reasoning_traces", "ix_reasoning_traces_session_id"):
            op.drop_index("ix_reasoning_traces_session_id", table_name="reasoning_traces")
        op.drop_table("reasoning_traces")
