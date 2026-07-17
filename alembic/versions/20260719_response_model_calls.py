"""Persist model invocations for canonical Responses."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260719_response_model_calls"
down_revision = "20260718_custom_instructions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "response_model_calls",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("response_id", sa.String(length=64), nullable=False),
        sa.Column("call_id", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="query"),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="completed"),
        sa.Column("call_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["response_id"], ["responses.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("response_id", "call_id", name="uq_response_model_call"),
    )
    op.create_index("ix_response_model_calls_response_id", "response_model_calls", ["response_id"])


def downgrade() -> None:
    op.drop_table("response_model_calls")
