"""text2sql platform runs and audit events

Revision ID: r0020_text2sql_platform
Revises: r0019_sql_asset_corpus_and_query_plans
Create Date: 2026-08-10 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0020_text2sql_platform"
down_revision = "r0019_sql_asset_corpus_and_query_plans"
branch_labels = None
depends_on = None


def _json_default(value: str) -> sa.TextClause:
    return sa.text(value)


def upgrade() -> None:
    op.create_table(
        "text2sql_runs",
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
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False, server_default="sql_only"),
        sa.Column("state", sa.String(length=32), nullable=False, server_default="researching"),
        sa.Column("request_json", sa.JSON(), nullable=False, server_default=_json_default("'{}'")),
        sa.Column(
            "research_plan_json", sa.JSON(), nullable=False, server_default=_json_default("'{}'")
        ),
        sa.Column("evidence_json", sa.JSON(), nullable=False, server_default=_json_default("'{}'")),
        sa.Column(
            "logical_plan_json", sa.JSON(), nullable=False, server_default=_json_default("'{}'")
        ),
        sa.Column(
            "candidates_json", sa.JSON(), nullable=False, server_default=_json_default("'[]'")
        ),
        sa.Column("selected_candidate_id", sa.String(length=64), nullable=True),
        sa.Column("policy_json", sa.JSON(), nullable=False, server_default=_json_default("'{}'")),
        sa.Column("result_json", sa.JSON(), nullable=False, server_default=_json_default("'{}'")),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.JSON(), nullable=False, server_default=_json_default("'[]'")),
        sa.Column("trace_json", sa.JSON(), nullable=False, server_default=_json_default("'[]'")),
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("semantic_version", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name, columns in {
        "ix_text2sql_runs_user_id": ["user_id"],
        "ix_text2sql_runs_tenant_id": ["tenant_id"],
        "ix_text2sql_runs_workspace_id": ["workspace_id"],
        "ix_text2sql_runs_project_id": ["project_id"],
        "ix_text2sql_runs_data_source_id": ["data_source_id"],
        "ix_text2sql_runs_state": ["state"],
        "ix_text2sql_runs_schema_fingerprint": ["schema_fingerprint"],
        "ix_text2sql_runs_created_at": ["created_at"],
        "ix_text2sql_runs_scope_created": [
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "created_at",
        ],
    }.items():
        op.create_index(name, "text2sql_runs", columns, unique=False)
    op.create_table(
        "text2sql_run_events",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(length=64),
            sa.ForeignKey("text2sql_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=_json_default("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "sequence_number", name="uq_text2sql_run_event_sequence"),
    )
    op.create_index(
        "ix_text2sql_run_events_run_id", "text2sql_run_events", ["run_id"], unique=False
    )
    op.create_index(
        "ix_text2sql_run_events_event_type", "text2sql_run_events", ["event_type"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_text2sql_run_events_event_type", table_name="text2sql_run_events")
    op.drop_index("ix_text2sql_run_events_run_id", table_name="text2sql_run_events")
    op.drop_table("text2sql_run_events")
    for name in (
        "ix_text2sql_runs_scope_created",
        "ix_text2sql_runs_created_at",
        "ix_text2sql_runs_schema_fingerprint",
        "ix_text2sql_runs_state",
        "ix_text2sql_runs_data_source_id",
        "ix_text2sql_runs_project_id",
        "ix_text2sql_runs_workspace_id",
        "ix_text2sql_runs_tenant_id",
        "ix_text2sql_runs_user_id",
    ):
        op.drop_index(name, table_name="text2sql_runs")
    op.drop_table("text2sql_runs")
