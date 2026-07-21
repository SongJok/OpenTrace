"""add active_attachment_ids to conversation_states

Revision ID: 20260509_add_attachment_state
Revises: 20260509_add_attachments
Create Date: 2026-05-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260509_add_attachment_state"
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
        cols = {c["name"] for c in inspector.get_columns(table, schema="public")}
        return column in cols
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "conversation_states" not in _public_tables(inspector):
        return

    if not _column_exists(inspector, "conversation_states", "active_attachment_ids"):
        op.add_column(
            "conversation_states",
            sa.Column(
                "active_attachment_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            schema="public",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "conversation_states" not in _public_tables(inspector):
        return

    if _column_exists(inspector, "conversation_states", "active_attachment_ids"):
        op.drop_column("conversation_states", "active_attachment_ids", schema="public")
