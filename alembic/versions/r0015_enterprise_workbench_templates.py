"""enterprise organization workbench templates

Revision ID: r0015_enterprise_workbench_templates
Revises: r0014_enterprise_reports
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0015_enterprise_workbench_templates"
down_revision = "r0014_enterprise_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "enterprise_workbench_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("audience_type", sa.String(20), nullable=False, server_default="principals"),
        sa.Column("scenario_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("status", sa.String(20), nullable=False, server_default="inactive"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "updated_by",
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
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "audience_type",
        "priority",
        "status",
        "created_by",
        "updated_by",
    ):
        op.create_index(
            f"ix_enterprise_workbench_templates_{column}",
            "enterprise_workbench_templates",
            [column],
        )
    op.create_index(
        "ix_enterprise_workbench_templates_scope_status",
        "enterprise_workbench_templates",
        ["tenant_id", "workspace_id", "status"],
    )

    op.create_table(
        "enterprise_workbench_template_targets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("enterprise_workbench_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "principal_id",
            sa.String(36),
            sa.ForeignKey("enterprise_directory_principals.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "template_id", "principal_id", name="uq_enterprise_workbench_template_target"
        ),
    )
    for column in ("template_id", "principal_id", "tenant_id", "workspace_id"):
        op.create_index(
            f"ix_enterprise_workbench_template_targets_{column}",
            "enterprise_workbench_template_targets",
            [column],
        )
    op.create_index(
        "ix_enterprise_workbench_template_targets_scope",
        "enterprise_workbench_template_targets",
        ["tenant_id", "workspace_id"],
    )


def downgrade() -> None:
    op.drop_table("enterprise_workbench_template_targets")
    op.drop_table("enterprise_workbench_templates")
