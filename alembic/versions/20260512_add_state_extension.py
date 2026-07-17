"""add state_extension JSON column to conversation_states

Revision ID: 20260512_add_state_extension
Revises: 20260511_add_messages
Create Date: 2026-05-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260512_add_state_extension"
down_revision = "20260511_add_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("conversation_states")}
    if "state_extension" not in existing:
        op.add_column(
            "conversation_states",
            sa.Column(
                "state_extension",
                postgresql.JSON(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = {c["name"] for c in inspector.get_columns("conversation_states")}
    if "state_extension" in existing:
        op.drop_column("conversation_states", "state_extension")
