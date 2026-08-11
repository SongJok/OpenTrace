"""enterprise data answer and learning loop

Revision ID: r0023_enterprise_data_answer_loop
Revises: r0022_unify_data_agent_platform
Create Date: 2026-08-11 17:20:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0023_enterprise_data_answer_loop"
down_revision = "r0022_unify_data_agent_platform"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for name, default in (
        ("source_decision_json", "'{}'"),
        ("answer_metadata_json", "'{}'"),
        ("learning_json", "'{}'"),
    ):
        op.add_column(
            "data_agent_runs",
            sa.Column(name, sa.JSON(), nullable=False, server_default=sa.text(default)),
        )
    op.add_column(
        "data_agent_runs",
        sa.Column(
            "answer_citations_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'"),
        ),
    )

    op.add_column(
        "metric_definitions",
        sa.Column(
            "certification_level",
            sa.String(length=20),
            nullable=False,
            server_default="draft",
        ),
    )
    op.add_column(
        "metric_definitions",
        sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column(
        "metric_definitions",
        sa.Column("quality_contract", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index(
        "ix_metric_definitions_certification_level",
        "metric_definitions",
        ["certification_level"],
        unique=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE metric_definitions
            SET certification_level = CASE
                WHEN status = 'published'
                     AND approved_by IS NOT NULL
                     AND owner IS NOT NULL
                     AND business_definition IS NOT NULL
                THEN 'verified'
                WHEN status = 'deprecated' THEN 'deprecated'
                ELSE 'draft'
            END
            """
        )
    )

    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column(
            "last_evaluation_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column("last_run_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column("pass_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "data_agent_evaluation_cases",
        sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_foreign_key(
        "data_agent_evaluation_cases_last_run_id_fkey",
        "data_agent_evaluation_cases",
        "data_agent_runs",
        ["last_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_data_agent_evaluation_cases_last_run_id",
        "data_agent_evaluation_cases",
        ["last_run_id"],
        unique=False,
    )

    op.create_table(
        "data_agent_learning_patterns",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("scope_key", sa.String(length=128), nullable=False, server_default="__global__"),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("pattern_key", sa.String(length=64), nullable=False),
        sa.Column("question_examples", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("logical_plan_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("selected_sql", sa.Text(), nullable=False),
        sa.Column("sql_structure_hash", sa.String(length=64), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("semantic_version", sa.String(length=128), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("validation_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("observation_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="observed"),
        sa.Column("last_run_id", sa.String(length=64), nullable=True),
        sa.Column("last_result_signature", sa.String(length=64), nullable=True),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["last_run_id"], ["data_agent_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "scope_key",
            "pattern_key",
            "schema_fingerprint",
            "semantic_version",
            name="uq_data_agent_learning_pattern_version",
        ),
    )
    for name, columns in (
        ("ix_data_agent_learning_patterns_user_id", ["user_id"]),
        ("ix_data_agent_learning_patterns_tenant_id", ["tenant_id"]),
        ("ix_data_agent_learning_patterns_workspace_id", ["workspace_id"]),
        ("ix_data_agent_learning_patterns_project_id", ["project_id"]),
        ("ix_data_agent_learning_patterns_data_source_id", ["data_source_id"]),
        ("ix_data_agent_learning_patterns_pattern_key", ["pattern_key"]),
        ("ix_data_agent_learning_patterns_sql_structure_hash", ["sql_structure_hash"]),
        ("ix_data_agent_learning_patterns_schema_fingerprint", ["schema_fingerprint"]),
        ("ix_data_agent_learning_patterns_semantic_version", ["semantic_version"]),
        ("ix_data_agent_learning_patterns_status", ["status"]),
        ("ix_data_agent_learning_patterns_last_run_id", ["last_run_id"]),
        (
            "ix_data_agent_learning_scope_status",
            ["user_id", "tenant_id", "workspace_id", "data_source_id", "status"],
        ),
    ):
        op.create_index(name, "data_agent_learning_patterns", columns, unique=False)


def downgrade() -> None:
    op.drop_table("data_agent_learning_patterns")

    op.drop_index(
        "ix_data_agent_evaluation_cases_last_run_id",
        table_name="data_agent_evaluation_cases",
    )
    op.drop_constraint(
        "data_agent_evaluation_cases_last_run_id_fkey",
        "data_agent_evaluation_cases",
        type_="foreignkey",
    )
    for name in (
        "last_evaluated_at",
        "failure_count",
        "pass_count",
        "last_run_id",
        "last_evaluation_json",
    ):
        op.drop_column("data_agent_evaluation_cases", name)

    op.drop_index(
        "ix_metric_definitions_certification_level",
        table_name="metric_definitions",
    )
    for name in ("quality_contract", "evidence_refs", "certification_level"):
        op.drop_column("metric_definitions", name)

    for name in (
        "answer_citations_json",
        "learning_json",
        "answer_metadata_json",
        "source_decision_json",
    ):
        op.drop_column("data_agent_runs", name)
