"""Add governed company and department cognitive profiles.

Revision ID: r0007_enterprise_cognition
Revises: r0006_calendar_events
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0007_enterprise_cognition"
down_revision = "r0006_calendar_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_cognitive_entities",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_key", sa.String(128), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column(
            "directory_principal_id",
            sa.String(36),
            sa.ForeignKey("enterprise_directory_principals.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "knowledge_space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "entity_type IN ('company', 'department')",
            name="ck_enterprise_cognitive_entity_type",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_enterprise_cognitive_entity_status",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "entity_type",
            "entity_key",
            name="uq_enterprise_cognitive_entity_scope_key",
        ),
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "entity_type",
        "entity_key",
        "directory_principal_id",
        "knowledge_space_id",
        "status",
        "created_by",
    ):
        op.create_index(
            f"ix_enterprise_cognitive_entities_{column}",
            "enterprise_cognitive_entities",
            [column],
        )

    op.create_table(
        "enterprise_cognitive_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "entity_id",
            sa.String(36),
            sa.ForeignKey("enterprise_cognitive_entities.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("classification", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("mission", sa.Text(), nullable=False, server_default=""),
        sa.Column("vision", sa.Text(), nullable=False, server_default=""),
        sa.Column("values", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("responsibilities", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("products_services", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "operating_principles", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("terminology", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("key_contacts", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("context_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column("review_due_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "published_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'published', 'archived')",
            name="ck_enterprise_cognitive_version_status",
        ),
        sa.CheckConstraint(
            "classification IN ('public', 'internal', 'confidential', 'restricted')",
            name="ck_enterprise_cognitive_version_classification",
        ),
        sa.UniqueConstraint("entity_id", "version", name="uq_enterprise_cognitive_entity_version"),
    )
    for column in (
        "entity_id",
        "tenant_id",
        "workspace_id",
        "status",
        "classification",
        "effective_from",
        "effective_to",
        "review_due_at",
        "created_by",
        "published_by",
        "published_at",
    ):
        op.create_index(
            f"ix_enterprise_cognitive_versions_{column}",
            "enterprise_cognitive_versions",
            [column],
        )
    op.create_index(
        "uq_enterprise_cognitive_published_entity",
        "enterprise_cognitive_versions",
        ["entity_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
    )


def downgrade() -> None:
    op.drop_table("enterprise_cognitive_versions")
    op.drop_table("enterprise_cognitive_entities")
