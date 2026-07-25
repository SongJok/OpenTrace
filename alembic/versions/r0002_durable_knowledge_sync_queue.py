"""Durable connector snapshot queue for enterprise knowledge ingestion.

Revision ID: r0002_durable_knowledge_sync_queue
Revises: r0001_enterprise_knowledge_base
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0002_durable_knowledge_sync_queue"
down_revision = "r0001_enterprise_knowledge_base"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "knowledge_sync_runs",
        "status",
        existing_type=sa.String(20),
        server_default="pending",
        existing_nullable=False,
    )
    op.create_table(
        "knowledge_sync_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("knowledge_sync_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "connector_id",
            sa.String(36),
            sa.ForeignKey("knowledge_connectors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("external_id", sa.String(512), nullable=False),
        sa.Column("document_id", sa.String(36)),
        sa.Column("source_id", sa.String(36)),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_type", sa.String(20), nullable=False, server_default="text"),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("deleted", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("authority", sa.String(32), nullable=False, server_default="external"),
        sa.Column("classification", sa.String(20)),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column(
            "source_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column("acl_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_by", sa.String(128)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("run_id", "external_id", name="uq_knowledge_sync_item_external"),
    )
    for column in (
        "run_id",
        "connector_id",
        "tenant_id",
        "workspace_id",
        "document_id",
        "source_id",
        "content_hash",
        "status",
        "locked_by",
    ):
        op.create_index(f"ix_knowledge_sync_items_{column}", "knowledge_sync_items", [column])


def downgrade() -> None:
    op.drop_table("knowledge_sync_items")
    op.alter_column(
        "knowledge_sync_runs",
        "status",
        existing_type=sa.String(20),
        server_default="running",
        existing_nullable=False,
    )
