"""data_agent_operational_governance

Revision ID: r0026_data_agent_operational_governance
Revises: r0025_evidence_closure
Create Date: 2026-08-13 10:51:03.365887
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0026_data_agent_operational_governance"
down_revision = "r0025_evidence_closure"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_agent_result_artifacts",
        sa.Column("details_purged_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint(
        "uq_data_agent_failure_pattern_version",
        "data_agent_failure_patterns",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_data_agent_failure_pattern_structure_version",
        "data_agent_failure_patterns",
        [
            "user_id",
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "pattern_key",
            "schema_fingerprint",
            "semantic_version",
            "candidate_sql_hash",
            "failure_stage",
        ],
    )

    for table in ("data_agent_failure_patterns", "data_agent_feedback"):
        op.add_column(
            table,
            sa.Column("status", sa.String(length=20), nullable=False, server_default="open"),
        )
        op.add_column(table, sa.Column("resolution_note", sa.Text(), nullable=True))
        op.add_column(table, sa.Column("resolved_by", sa.String(length=36), nullable=True))
        op.add_column(table, sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_resolved_by_users",
            table,
            "users",
            ["resolved_by"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_status", table, ["status"])

    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column("business_domain", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column("published_by", sa.String(length=36), nullable=True),
    )
    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_data_agent_evaluation_cases_published_by_users",
        "data_agent_evaluation_cases",
        "users",
        ["published_by"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_data_agent_evaluation_cases_business_domain",
        "data_agent_evaluation_cases",
        ["business_domain"],
    )

    op.create_table(
        "data_agent_evaluation_suite_runs",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False, server_default="发布门禁"),
        sa.Column("execute", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("tags_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("business_domain", sa.String(length=128), nullable=True),
        sa.Column("minimum_pass_rate", sa.Float(), nullable=False, server_default="1"),
        sa.Column("case_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pass_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("results_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_agent_eval_suite_scope",
        "data_agent_evaluation_suite_runs",
        ["tenant_id", "workspace_id", "data_source_id", "started_at"],
    )
    op.create_index(
        "ix_data_agent_evaluation_suite_runs_user_id",
        "data_agent_evaluation_suite_runs",
        ["user_id"],
    )
    op.create_index(
        "ix_data_agent_evaluation_suite_runs_tenant_id",
        "data_agent_evaluation_suite_runs",
        ["tenant_id"],
    )
    op.create_index(
        "ix_data_agent_evaluation_suite_runs_workspace_id",
        "data_agent_evaluation_suite_runs",
        ["workspace_id"],
    )
    op.create_index(
        "ix_data_agent_evaluation_suite_runs_data_source_id",
        "data_agent_evaluation_suite_runs",
        ["data_source_id"],
    )
    op.create_index(
        "ix_data_agent_evaluation_suite_runs_business_domain",
        "data_agent_evaluation_suite_runs",
        ["business_domain"],
    )
    op.create_index(
        "ix_data_agent_evaluation_suite_runs_status",
        "data_agent_evaluation_suite_runs",
        ["status"],
    )


def downgrade() -> None:
    for index in (
        "ix_data_agent_evaluation_suite_runs_status",
        "ix_data_agent_evaluation_suite_runs_business_domain",
        "ix_data_agent_evaluation_suite_runs_data_source_id",
        "ix_data_agent_evaluation_suite_runs_workspace_id",
        "ix_data_agent_evaluation_suite_runs_tenant_id",
        "ix_data_agent_evaluation_suite_runs_user_id",
        "ix_data_agent_eval_suite_scope",
    ):
        op.drop_index(index, table_name="data_agent_evaluation_suite_runs")
    op.drop_table("data_agent_evaluation_suite_runs")

    op.drop_index(
        "ix_data_agent_evaluation_cases_business_domain",
        table_name="data_agent_evaluation_cases",
    )
    op.drop_constraint(
        "fk_data_agent_evaluation_cases_published_by_users",
        "data_agent_evaluation_cases",
        type_="foreignkey",
    )
    op.drop_column("data_agent_evaluation_cases", "published_at")
    op.drop_column("data_agent_evaluation_cases", "published_by")
    op.drop_column("data_agent_evaluation_cases", "business_domain")

    for table in ("data_agent_feedback", "data_agent_failure_patterns"):
        op.drop_index(f"ix_{table}_status", table_name=table)
        op.drop_constraint(f"fk_{table}_resolved_by_users", table, type_="foreignkey")
        op.drop_column(table, "resolved_at")
        op.drop_column(table, "resolved_by")
        op.drop_column(table, "resolution_note")
        op.drop_column(table, "status")

    op.drop_column("data_agent_result_artifacts", "details_purged_at")
    op.drop_constraint(
        "uq_data_agent_failure_pattern_structure_version",
        "data_agent_failure_patterns",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_data_agent_failure_pattern_version",
        "data_agent_failure_patterns",
        [
            "user_id",
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "pattern_key",
            "schema_fingerprint",
            "semantic_version",
            "failure_stage",
        ],
    )
