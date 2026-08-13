"""response evidence closure and immutable data artifacts

Revision ID: r0025_evidence_closure
Revises: r0024_remove_projects
Create Date: 2026-08-13 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0025_evidence_closure"
down_revision = "r0024_remove_projects"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "response_approvals",
        sa.Column(
            "operation_class",
            sa.String(length=32),
            nullable=False,
            server_default="write",
        ),
    )
    op.execute(
        sa.text(
            "UPDATE response_approvals SET operation_class = 'governed_read' "
            "WHERE tool_name = 'execute_sql_draft'"
        )
    )

    op.create_table(
        "data_agent_result_artifacts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("run_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("sql_structure_hash", sa.String(length=64), nullable=False),
        sa.Column("result_signature", sa.String(length=64), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("semantic_version", sa.String(length=128), nullable=True),
        sa.Column("returned_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("truncated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("columns_json", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("validation_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("freshness_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["data_source_id"], ["data_sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["run_id"], ["data_agent_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_data_agent_result_artifact_run",
        "data_agent_result_artifacts",
        ["run_id"],
    )
    op.create_index(
        "ix_data_agent_result_artifact_scope",
        "data_agent_result_artifacts",
        ["user_id", "tenant_id", "workspace_id", "data_source_id"],
    )
    op.create_index(
        "ix_data_agent_result_artifact_schema",
        "data_agent_result_artifacts",
        ["schema_fingerprint"],
    )
    op.create_index(
        "ix_data_agent_result_artifact_sql",
        "data_agent_result_artifacts",
        ["sql_structure_hash"],
    )
    op.create_index(
        "ix_data_agent_result_artifact_expires",
        "data_agent_result_artifacts",
        ["expires_at"],
    )

    op.create_table(
        "data_agent_failure_patterns",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.String(length=128), nullable=False),
        sa.Column("data_source_id", sa.String(length=36), nullable=False),
        sa.Column("pattern_key", sa.String(length=64), nullable=False),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("semantic_version", sa.String(length=128), nullable=False),
        sa.Column("failure_stage", sa.String(length=64), nullable=False),
        sa.Column("error_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("question_examples", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("candidate_sql_hash", sa.String(length=64), nullable=False),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("last_run_id", sa.String(length=64), nullable=True),
        sa.Column(
            "last_failure_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
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
            "pattern_key",
            "schema_fingerprint",
            "semantic_version",
            "failure_stage",
            name="uq_data_agent_failure_pattern_version",
        ),
    )
    op.create_index(
        "ix_data_agent_failure_pattern_scope",
        "data_agent_failure_patterns",
        ["user_id", "tenant_id", "workspace_id", "data_source_id", "failure_stage"],
    )
    op.create_index(
        "ix_data_agent_failure_pattern_key",
        "data_agent_failure_patterns",
        ["pattern_key"],
    )


def downgrade() -> None:
    op.drop_index("ix_data_agent_failure_pattern_key", table_name="data_agent_failure_patterns")
    op.drop_index("ix_data_agent_failure_pattern_scope", table_name="data_agent_failure_patterns")
    op.drop_table("data_agent_failure_patterns")
    op.drop_index("ix_data_agent_result_artifact_expires", table_name="data_agent_result_artifacts")
    op.drop_index("ix_data_agent_result_artifact_sql", table_name="data_agent_result_artifacts")
    op.drop_index("ix_data_agent_result_artifact_schema", table_name="data_agent_result_artifacts")
    op.drop_index("ix_data_agent_result_artifact_scope", table_name="data_agent_result_artifacts")
    op.drop_index("ix_data_agent_result_artifact_run", table_name="data_agent_result_artifacts")
    op.drop_table("data_agent_result_artifacts")
    op.drop_column("response_approvals", "operation_class")
