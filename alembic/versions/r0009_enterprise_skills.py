"""Add tenant-scoped enterprise skills distilled from governed files.

Revision ID: r0009_enterprise_skills
Revises: r0008_memory_quality_cleanup
Create Date: 2026-07-30
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0009_enterprise_skills"
down_revision = "r0008_memory_quality_cleanup"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_skills",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("runtime_id", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("value_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("source_files", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("use_cases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("classification", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("status", sa.String(20), nullable=False, server_default="published"),
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
            nullable=False,
        ),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
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
            "source_digest",
            name="uq_enterprise_skill_scope_source_digest",
        ),
        sa.UniqueConstraint("runtime_id", name="uq_enterprise_skill_runtime_id"),
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "runtime_id",
        "name",
        "source_digest",
        "classification",
        "status",
        "created_by",
        "published_by",
        "published_at",
    ):
        op.create_index(f"ix_enterprise_skills_{column}", "enterprise_skills", [column])


def downgrade() -> None:
    op.drop_table("enterprise_skills")
