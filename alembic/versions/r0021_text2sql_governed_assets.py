"""text2sql governed semantic assets, evaluation cases and feedback

Revision ID: r0021_text2sql_governed_assets
Revises: r0020_text2sql_platform
Create Date: 2026-08-10 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0021_text2sql_governed_assets"
down_revision = "r0020_text2sql_platform"
branch_labels = None
depends_on = None


def _json(value: str) -> sa.TextClause:
    return sa.text(value)


def upgrade() -> None:
    op.create_table(
        "text2sql_semantic_assets",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column(
            "data_source_id",
            sa.String(length=36),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_type", sa.String(length=32), nullable=False),
        sa.Column("asset_key", sa.String(length=255), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("authority", sa.String(length=32), nullable=False, server_default="contextual"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("definition_json", sa.JSON(), nullable=False, server_default=_json("'{}'")),
        sa.Column("source_refs", sa.JSON(), nullable=False, server_default=_json("'[]'")),
        sa.Column("approved_by", sa.String(length=36), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "asset_type",
            "asset_key",
            "version",
            name="uq_text2sql_semantic_asset_version",
        ),
    )
    for name, columns in {
        "ix_text2sql_semantic_assets_user_id": ["user_id"],
        "ix_text2sql_semantic_assets_tenant_id": ["tenant_id"],
        "ix_text2sql_semantic_assets_workspace_id": ["workspace_id"],
        "ix_text2sql_semantic_assets_project_id": ["project_id"],
        "ix_text2sql_semantic_assets_data_source_id": ["data_source_id"],
        "ix_text2sql_semantic_assets_asset_type": ["asset_type"],
        "ix_text2sql_semantic_assets_status": ["status"],
    }.items():
        op.create_index(name, "text2sql_semantic_assets", columns, unique=False)

    op.create_table(
        "text2sql_evaluation_cases",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column(
            "data_source_id",
            sa.String(length=36),
            sa.ForeignKey("data_sources.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expected_sql", sa.Text(), nullable=True),
        sa.Column("expected_plan", sa.JSON(), nullable=False, server_default=_json("'{}'")),
        sa.Column("expected_result", sa.JSON(), nullable=False, server_default=_json("'[]'")),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("tags", sa.JSON(), nullable=False, server_default=_json("'[]'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for name, columns in {
        "ix_text2sql_evaluation_cases_user_id": ["user_id"],
        "ix_text2sql_evaluation_cases_tenant_id": ["tenant_id"],
        "ix_text2sql_evaluation_cases_workspace_id": ["workspace_id"],
        "ix_text2sql_evaluation_cases_data_source_id": ["data_source_id"],
        "ix_text2sql_evaluation_cases_status": ["status"],
        "ix_text2sql_eval_scope": ["tenant_id", "workspace_id", "data_source_id"],
    }.items():
        op.create_index(name, "text2sql_evaluation_cases", columns, unique=False)

    op.create_table(
        "text2sql_feedback",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("text2sql_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("verdict", sa.String(length=20), nullable=False),
        sa.Column("candidate_id", sa.String(length=64), nullable=True),
        sa.Column("corrected_sql", sa.Text(), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=_json("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    for name, columns in {
        "ix_text2sql_feedback_run_id": ["run_id"],
        "ix_text2sql_feedback_user_id": ["user_id"],
        "ix_text2sql_feedback_tenant_id": ["tenant_id"],
        "ix_text2sql_feedback_workspace_id": ["workspace_id"],
    }.items():
        op.create_index(name, "text2sql_feedback", columns, unique=False)


def downgrade() -> None:
    for name in (
        "ix_text2sql_feedback_workspace_id",
        "ix_text2sql_feedback_tenant_id",
        "ix_text2sql_feedback_user_id",
        "ix_text2sql_feedback_run_id",
    ):
        op.drop_index(name, table_name="text2sql_feedback")
    op.drop_table("text2sql_feedback")
    for name in (
        "ix_text2sql_eval_scope",
        "ix_text2sql_evaluation_cases_status",
        "ix_text2sql_evaluation_cases_data_source_id",
        "ix_text2sql_evaluation_cases_workspace_id",
        "ix_text2sql_evaluation_cases_tenant_id",
        "ix_text2sql_evaluation_cases_user_id",
    ):
        op.drop_index(name, table_name="text2sql_evaluation_cases")
    op.drop_table("text2sql_evaluation_cases")
    for name in (
        "ix_text2sql_semantic_assets_status",
        "ix_text2sql_semantic_assets_asset_type",
        "ix_text2sql_semantic_assets_data_source_id",
        "ix_text2sql_semantic_assets_project_id",
        "ix_text2sql_semantic_assets_workspace_id",
        "ix_text2sql_semantic_assets_tenant_id",
        "ix_text2sql_semantic_assets_user_id",
    ):
        op.drop_index(name, table_name="text2sql_semantic_assets")
    op.drop_table("text2sql_semantic_assets")
