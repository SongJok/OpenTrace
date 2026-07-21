"""add conversation_states table

Revision ID: 20260508_add_conversation_state
Revises: 20260423_add_chunk_strategy
Create Date: 2026-05-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260508_add_conversation_state"
down_revision = "20260423_add_chunk_strategy"
branch_labels = None
depends_on = None


def _public_tables(inspector: sa.Inspector) -> set[str]:
    try:
        return set(inspector.get_table_names(schema="public"))
    except Exception:
        return set()


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

    if "conversation_states" not in tables:
        op.create_table(
            "conversation_states",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("active_topic", sa.String(length=255), nullable=True),
            sa.Column("active_intent", sa.String(length=64), nullable=True),
            sa.Column("active_domain", sa.String(length=64), nullable=True),
            sa.Column("active_entities", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("active_constraints", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("active_mode", sa.String(length=64), nullable=True),
            sa.Column("active_data_source_id", sa.String(length=36), nullable=True),
            sa.Column("active_document_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("last_user_goal", sa.Text(), nullable=True),
            sa.Column("last_assistant_summary", sa.Text(), nullable=True),
            sa.Column("last_plan", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("last_results", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("pending_clarification", sa.JSON(), nullable=True),
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["public.chat_sessions.id"], ondelete="CASCADE"
            ),
            sa.UniqueConstraint("session_id", name="uq_conversation_states_session_id"),
            schema="public",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(
        inspector, "conversation_states", "ix_conversation_states_session_id"
    ):
        op.create_index(
            "ix_conversation_states_session_id",
            "conversation_states",
            ["session_id"],
            unique=True,
            schema="public",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _public_tables(inspector)
    if "conversation_states" in tables:
        op.drop_table("conversation_states", schema="public")
