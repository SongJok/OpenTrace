"""Enterprise knowledge spaces, ACL, connectors and review governance.

Revision ID: r0001_enterprise_knowledge_base
Revises: 20260803_chatgpt_five_pillars
Create Date: 2026-07-25
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0001_enterprise_knowledge_base"
down_revision = "20260803_chatgpt_five_pillars"
branch_labels = None
depends_on = None


def _scope_columns() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
        sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
    )


def upgrade() -> None:
    op.create_table(
        "knowledge_spaces",
        sa.Column("id", sa.String(36), primary_key=True),
        *_scope_columns(),
        sa.Column(
            "owner_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("space_type", sa.String(32), nullable=False, server_default="project"),
        sa.Column("visibility", sa.String(20), nullable=False, server_default="members"),
        sa.Column(
            "default_classification", sa.String(20), nullable=False, server_default="internal"
        ),
        sa.Column("publish_policy", sa.String(20), nullable=False, server_default="review"),
        sa.Column("review_cycle_days", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "space_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("tenant_id", "workspace_id", "slug", name="uq_knowledge_space_slug"),
    )
    op.create_table(
        "knowledge_space_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column("subject_type", sa.String(20), nullable=False, server_default="user"),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="viewer"),
        sa.Column("granted_by", sa.String(36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "space_id", "subject_type", "subject_id", name="uq_knowledge_space_member_subject"
        ),
    )
    op.create_table(
        "knowledge_principal_memberships",
        sa.Column("id", sa.String(36), primary_key=True),
        *_scope_columns(),
        sa.Column(
            "user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("principal_type", sa.String(20), nullable=False),
        sa.Column("principal_id", sa.String(128), nullable=False),
        sa.Column("source", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("effective_from", sa.DateTime(timezone=True)),
        sa.Column("effective_to", sa.DateTime(timezone=True)),
        sa.Column(
            "membership_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
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
            "principal_type",
            "principal_id",
            name="uq_knowledge_principal_membership",
        ),
    )
    op.create_table(
        "knowledge_space_projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column("attached_by", sa.String(36), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("space_id", "project_id", name="uq_knowledge_space_project"),
    )
    op.create_table(
        "knowledge_connectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "space_id",
            sa.String(36),
            sa.ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("connector_type", sa.String(32), nullable=False, server_default="push"),
        sa.Column("base_url", sa.String(1024)),
        sa.Column("credential_ref", sa.String(255)),
        sa.Column("sync_cursor", sa.Text()),
        sa.Column("sync_interval_seconds", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column(
            "connector_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")
        ),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("space_id", "name", name="uq_knowledge_connector_name"),
    )
    op.create_table(
        "knowledge_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "connector_id",
            sa.String(36),
            sa.ForeignKey("knowledge_connectors.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("cursor_before", sa.Text()),
        sa.Column("cursor_after", sa.Text()),
        sa.Column("stats", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("error", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )

    for name, type_ in (
        ("space_id", sa.String(36)),
        ("connector_id", sa.String(36)),
        ("steward_id", sa.String(36)),
        ("classification", sa.String(20)),
        ("source_system", sa.String(64)),
        ("sync_status", sa.String(20)),
        ("effective_from", sa.DateTime(timezone=True)),
        ("effective_to", sa.DateTime(timezone=True)),
        ("review_due_at", sa.DateTime(timezone=True)),
        ("deleted_at", sa.DateTime(timezone=True)),
    ):
        kwargs = {"nullable": True}
        if name == "classification":
            kwargs.update(nullable=False, server_default="internal")
        elif name == "sync_status":
            kwargs.update(nullable=False, server_default="current")
        op.add_column("knowledge_sources", sa.Column(name, type_, **kwargs))
    op.create_foreign_key(
        "fk_knowledge_sources_space",
        "knowledge_sources",
        "knowledge_spaces",
        ["space_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_knowledge_sources_connector",
        "knowledge_sources",
        "knowledge_connectors",
        ["connector_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_unique_constraint(
        "uq_knowledge_source_connector_ref",
        "knowledge_sources",
        ["tenant_id", "workspace_id", "connector_id", "external_ref"],
    )

    op.create_table(
        "knowledge_source_permissions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_id",
            sa.String(36),
            sa.ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        *_scope_columns(),
        sa.Column("subject_type", sa.String(20), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("permission", sa.String(20), nullable=False, server_default="view"),
        sa.Column("inherited", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("external_ref", sa.String(512)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "source_id", "subject_type", "subject_id", name="uq_knowledge_source_permission"
        ),
    )
    op.create_table(
        "knowledge_review_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_version_id",
            sa.String(36),
            sa.ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "space_id", sa.String(36), sa.ForeignKey("knowledge_spaces.id", ondelete="SET NULL")
        ),
        *_scope_columns(),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("required_role", sa.String(20), nullable=False, server_default="publisher"),
        sa.Column("requested_by", sa.String(36)),
        sa.Column("assigned_to", sa.String(36)),
        sa.Column("decided_by", sa.String(36)),
        sa.Column("decision_comment", sa.Text()),
        sa.Column("diff_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_version_id", name="uq_knowledge_review_source_version"),
    )

    for table, columns in {
        "knowledge_spaces": ("tenant_id", "workspace_id", "owner_id", "space_type", "status"),
        "knowledge_space_members": ("space_id", "subject_type", "subject_id", "role"),
        "knowledge_principal_memberships": ("user_id", "principal_type", "principal_id", "status"),
        "knowledge_space_projects": ("space_id", "project_id"),
        "knowledge_connectors": ("space_id", "owner_id", "connector_type", "status"),
        "knowledge_sync_runs": ("connector_id", "status"),
        "knowledge_sources": (
            "space_id",
            "connector_id",
            "steward_id",
            "classification",
            "source_system",
            "sync_status",
            "effective_to",
            "review_due_at",
            "deleted_at",
        ),
        "knowledge_source_permissions": ("source_id", "subject_type", "subject_id"),
        "knowledge_review_tasks": ("source_version_id", "space_id", "status", "assigned_to"),
    }.items():
        for column in columns:
            op.create_index(f"ix_{table}_{column}", table, [column])


def downgrade() -> None:
    op.drop_table("knowledge_review_tasks")
    op.drop_table("knowledge_source_permissions")
    op.drop_constraint("fk_knowledge_sources_connector", "knowledge_sources", type_="foreignkey")
    op.drop_constraint("fk_knowledge_sources_space", "knowledge_sources", type_="foreignkey")
    for name in (
        "deleted_at",
        "review_due_at",
        "effective_to",
        "effective_from",
        "sync_status",
        "source_system",
        "classification",
        "steward_id",
        "connector_id",
        "space_id",
    ):
        op.drop_column("knowledge_sources", name)
    op.drop_table("knowledge_sync_runs")
    op.drop_table("knowledge_connectors")
    op.drop_table("knowledge_space_projects")
    op.drop_table("knowledge_principal_memberships")
    op.drop_table("knowledge_space_members")
    op.drop_table("knowledge_spaces")
