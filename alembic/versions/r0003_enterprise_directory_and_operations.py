"""Enterprise directory and organization membership facts.

Revision ID: r0003_enterprise_directory_and_operations
Revises: r0002_durable_knowledge_sync_queue
Create Date: 2026-07-27
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0003_enterprise_directory_and_operations"
down_revision = "r0002_durable_knowledge_sync_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_directory_principals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("principal_type", sa.String(20), nullable=False),
        sa.Column("external_id", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("parent_external_id", sa.String(128)),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("last_synced_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "principal_type",
            "external_id",
            name="uq_enterprise_directory_principal",
        ),
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "principal_type",
        "external_id",
        "parent_external_id",
        "source",
        "status",
        "last_synced_at",
    ):
        op.create_index(
            f"ix_enterprise_directory_principals_{column}",
            "enterprise_directory_principals",
            [column],
        )

    op.create_table(
        "enterprise_directory_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column(
            "user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "principal_id",
            sa.String(36),
            sa.ForeignKey("enterprise_directory_principals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column(
            "membership_metadata",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'::json"),
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "user_id",
            "principal_id",
            name="uq_enterprise_directory_membership",
        ),
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "user_id",
        "principal_id",
        "source",
        "status",
    ):
        op.create_index(
            f"ix_enterprise_directory_memberships_{column}",
            "enterprise_directory_memberships",
            [column],
        )

    op.create_table(
        "enterprise_directory_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("cursor", sa.String(512)),
        sa.Column("authoritative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stats", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "requested_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("error", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    for column in ("tenant_id", "workspace_id", "provider", "status", "requested_by"):
        op.create_index(
            f"ix_enterprise_directory_sync_runs_{column}",
            "enterprise_directory_sync_runs",
            [column],
        )


def downgrade() -> None:
    op.drop_table("enterprise_directory_sync_runs")
    op.drop_table("enterprise_directory_memberships")
    op.drop_table("enterprise_directory_principals")
