"""Add durable Responses API state, items, and semantic event replay."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260717_response_runtime"
down_revision = "20260716_chat_knowledge_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "responses",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("conversation_id", sa.String(length=36), sa.ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("workspace_id", sa.String(length=128), nullable=False, server_default="default"),
        sa.Column("parent_response_id", sa.String(length=64), nullable=True),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="sync"),
        sa.Column("model", sa.String(length=128), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("response_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "idempotency_key", name="uq_responses_tenant_idempotency"),
    )
    op.create_index("ix_responses_conversation_id", "responses", ["conversation_id"])
    op.create_index("ix_responses_user_id", "responses", ["user_id"])
    op.create_index("ix_responses_tenant_id", "responses", ["tenant_id"])
    op.create_index("ix_responses_parent_response_id", "responses", ["parent_response_id"])
    op.create_index("ix_responses_request_id", "responses", ["request_id"])
    op.create_index("ix_responses_status", "responses", ["status"])
    op.create_table(
        "response_items",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("response_id", sa.String(length=64), sa.ForeignKey("responses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("item_type", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=True),
        sa.Column("content", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("response_id", "sequence_number", name="uq_response_items_sequence"),
    )
    op.create_index("ix_response_items_response_id", "response_items", ["response_id"])
    op.create_table(
        "response_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("response_id", sa.String(length=64), sa.ForeignKey("responses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.UniqueConstraint("response_id", "sequence_number", name="uq_response_events_sequence"),
    )
    op.create_index("ix_response_events_response_id", "response_events", ["response_id"])
    op.create_index("ix_response_events_event_type", "response_events", ["event_type"])


def downgrade() -> None:
    op.drop_table("response_events")
    op.drop_table("response_items")
    op.drop_table("responses")
