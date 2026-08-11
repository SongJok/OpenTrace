"""unify_data_agent_platform

Revision ID: r0022_unify_data_agent_platform
Revises: r0021_text2sql_governed_assets
Create Date: 2026-08-11 15:24:43.831408
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0022_unify_data_agent_platform"
down_revision = "r0021_text2sql_governed_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.rename_table("text2sql_runs", "data_agent_runs")
    op.rename_table("text2sql_run_events", "data_agent_run_events")
    op.rename_table("text2sql_semantic_assets", "data_agent_semantic_assets")
    op.rename_table("text2sql_evaluation_cases", "data_agent_evaluation_cases")
    op.rename_table("text2sql_feedback", "data_agent_feedback")

    index_renames = {
        "ix_text2sql_runs_user_id": "ix_data_agent_runs_user_id",
        "ix_text2sql_runs_tenant_id": "ix_data_agent_runs_tenant_id",
        "ix_text2sql_runs_workspace_id": "ix_data_agent_runs_workspace_id",
        "ix_text2sql_runs_project_id": "ix_data_agent_runs_project_id",
        "ix_text2sql_runs_data_source_id": "ix_data_agent_runs_data_source_id",
        "ix_text2sql_runs_state": "ix_data_agent_runs_state",
        "ix_text2sql_runs_schema_fingerprint": "ix_data_agent_runs_schema_fingerprint",
        "ix_text2sql_runs_created_at": "ix_data_agent_runs_created_at",
        "ix_text2sql_runs_scope_created": "ix_data_agent_runs_scope_created",
        "ix_text2sql_run_events_run_id": "ix_data_agent_run_events_run_id",
        "ix_text2sql_run_events_event_type": "ix_data_agent_run_events_event_type",
        "ix_text2sql_semantic_assets_user_id": "ix_data_agent_semantic_assets_user_id",
        "ix_text2sql_semantic_assets_tenant_id": "ix_data_agent_semantic_assets_tenant_id",
        "ix_text2sql_semantic_assets_workspace_id": "ix_data_agent_semantic_assets_workspace_id",
        "ix_text2sql_semantic_assets_project_id": "ix_data_agent_semantic_assets_project_id",
        "ix_text2sql_semantic_assets_data_source_id": "ix_data_agent_semantic_assets_data_source_id",
        "ix_text2sql_semantic_assets_asset_type": "ix_data_agent_semantic_assets_asset_type",
        "ix_text2sql_semantic_assets_status": "ix_data_agent_semantic_assets_status",
        "ix_text2sql_evaluation_cases_user_id": "ix_data_agent_evaluation_cases_user_id",
        "ix_text2sql_evaluation_cases_tenant_id": "ix_data_agent_evaluation_cases_tenant_id",
        "ix_text2sql_evaluation_cases_workspace_id": "ix_data_agent_evaluation_cases_workspace_id",
        "ix_text2sql_evaluation_cases_data_source_id": "ix_data_agent_evaluation_cases_data_source_id",
        "ix_text2sql_evaluation_cases_status": "ix_data_agent_evaluation_cases_status",
        "ix_text2sql_eval_scope": "ix_data_agent_eval_scope",
        "ix_text2sql_feedback_run_id": "ix_data_agent_feedback_run_id",
        "ix_text2sql_feedback_user_id": "ix_data_agent_feedback_user_id",
        "ix_text2sql_feedback_tenant_id": "ix_data_agent_feedback_tenant_id",
        "ix_text2sql_feedback_workspace_id": "ix_data_agent_feedback_workspace_id",
    }
    for old_name, new_name in index_renames.items():
        op.execute(sa.text(f'ALTER INDEX IF EXISTS "{old_name}" RENAME TO "{new_name}"'))

    constraint_renames = {
        "data_agent_runs": {
            "text2sql_runs_pkey": "data_agent_runs_pkey",
            "text2sql_runs_user_id_fkey": "data_agent_runs_user_id_fkey",
            "text2sql_runs_data_source_id_fkey": "data_agent_runs_data_source_id_fkey",
        },
        "data_agent_run_events": {
            "text2sql_run_events_pkey": "data_agent_run_events_pkey",
            "text2sql_run_events_run_id_fkey": "data_agent_run_events_run_id_fkey",
            "uq_text2sql_run_event_sequence": "uq_data_agent_run_event_sequence",
        },
        "data_agent_semantic_assets": {
            "text2sql_semantic_assets_pkey": "data_agent_semantic_assets_pkey",
            "text2sql_semantic_assets_user_id_fkey": "data_agent_semantic_assets_user_id_fkey",
            "text2sql_semantic_assets_data_source_id_fkey": (
                "data_agent_semantic_assets_data_source_id_fkey"
            ),
            "uq_text2sql_semantic_asset_version": "uq_data_agent_semantic_asset_version",
        },
        "data_agent_evaluation_cases": {
            "text2sql_evaluation_cases_pkey": "data_agent_evaluation_cases_pkey",
            "text2sql_evaluation_cases_user_id_fkey": ("data_agent_evaluation_cases_user_id_fkey"),
            "text2sql_evaluation_cases_data_source_id_fkey": (
                "data_agent_evaluation_cases_data_source_id_fkey"
            ),
        },
        "data_agent_feedback": {
            "text2sql_feedback_pkey": "data_agent_feedback_pkey",
            "text2sql_feedback_run_id_fkey": "data_agent_feedback_run_id_fkey",
            "text2sql_feedback_user_id_fkey": "data_agent_feedback_user_id_fkey",
        },
    }
    for table_name, names in constraint_renames.items():
        for old_name, new_name in names.items():
            op.execute(
                sa.text(
                    f'ALTER TABLE "{table_name}" RENAME CONSTRAINT "{old_name}" TO "{new_name}"'
                )
            )

    op.add_column(
        "data_agent_runs",
        sa.Column("preflight_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "data_agent_runs",
        sa.Column(
            "result_validation_json",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    for name, column in (
        ("business_domain", sa.Column("business_domain", sa.String(length=128), nullable=True)),
        ("owner", sa.Column("owner", sa.String(length=255), nullable=True)),
        ("valid_from", sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True)),
        ("valid_to", sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True)),
    ):
        op.add_column("data_agent_semantic_assets", column)
        if name == "business_domain":
            op.create_index(
                "ix_data_agent_semantic_assets_business_domain",
                "data_agent_semantic_assets",
                ["business_domain"],
                unique=False,
            )

    metric_columns = (
        sa.Column("required_filters", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("time_field", sa.String(length=255), nullable=True),
        sa.Column("grain", sa.String(length=50), nullable=True),
        sa.Column("owner", sa.String(length=255), nullable=True),
        sa.Column("business_domain", sa.String(length=128), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=True),
    )
    for column in metric_columns:
        op.add_column("metric_definitions", column)

    op.create_table(
        "data_agent_profiles",
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
        sa.Column("schema_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("table_name", sa.String(length=255), nullable=False),
        sa.Column("column_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("profile_type", sa.String(length=20), nullable=False, server_default="column"),
        sa.Column(
            "sampling_method", sa.String(length=64), nullable=False, server_default="bounded_head"
        ),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="current"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("profiled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    for name, columns in {
        "ix_data_agent_profiles_user_id": ["user_id"],
        "ix_data_agent_profiles_tenant_id": ["tenant_id"],
        "ix_data_agent_profiles_workspace_id": ["workspace_id"],
        "ix_data_agent_profiles_data_source_id": ["data_source_id"],
        "ix_data_agent_profiles_schema_fingerprint": ["schema_fingerprint"],
        "ix_data_agent_profiles_status": ["status"],
        "ix_data_agent_profiles_profiled_at": ["profiled_at"],
        "ix_data_agent_profile_snapshot": [
            "data_source_id",
            "schema_fingerprint",
            "table_name",
            "column_name",
        ],
        "ix_data_agent_profiles_scope": [
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "status",
        ],
    }.items():
        op.create_index(name, "data_agent_profiles", columns, unique=False)

    op.add_column(
        "sql_query_drafts",
        sa.Column("data_agent_run_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_sql_query_drafts_data_agent_run_id",
        "sql_query_drafts",
        ["data_agent_run_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_sql_query_drafts_data_agent_run_id",
        "sql_query_drafts",
        "data_agent_runs",
        ["data_agent_run_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_sql_query_drafts_data_agent_run_id", "sql_query_drafts", type_="foreignkey"
    )
    op.drop_index("ix_sql_query_drafts_data_agent_run_id", table_name="sql_query_drafts")
    op.drop_column("sql_query_drafts", "data_agent_run_id")

    for name in (
        "ix_data_agent_profiles_scope",
        "ix_data_agent_profile_snapshot",
        "ix_data_agent_profiles_profiled_at",
        "ix_data_agent_profiles_status",
        "ix_data_agent_profiles_schema_fingerprint",
        "ix_data_agent_profiles_data_source_id",
        "ix_data_agent_profiles_workspace_id",
        "ix_data_agent_profiles_tenant_id",
        "ix_data_agent_profiles_user_id",
    ):
        op.drop_index(name, table_name="data_agent_profiles")
    op.drop_table("data_agent_profiles")

    for name in (
        "valid_to",
        "valid_from",
        "business_domain",
        "owner",
        "grain",
        "time_field",
        "required_filters",
    ):
        op.drop_column("metric_definitions", name)

    op.drop_index(
        "ix_data_agent_semantic_assets_business_domain",
        table_name="data_agent_semantic_assets",
    )
    for name in ("valid_to", "valid_from", "owner", "business_domain"):
        op.drop_column("data_agent_semantic_assets", name)
    op.drop_column("data_agent_runs", "result_validation_json")
    op.drop_column("data_agent_runs", "preflight_json")

    constraint_renames = {
        "data_agent_runs": {
            "data_agent_runs_pkey": "text2sql_runs_pkey",
            "data_agent_runs_user_id_fkey": "text2sql_runs_user_id_fkey",
            "data_agent_runs_data_source_id_fkey": "text2sql_runs_data_source_id_fkey",
        },
        "data_agent_run_events": {
            "data_agent_run_events_pkey": "text2sql_run_events_pkey",
            "data_agent_run_events_run_id_fkey": "text2sql_run_events_run_id_fkey",
            "uq_data_agent_run_event_sequence": "uq_text2sql_run_event_sequence",
        },
        "data_agent_semantic_assets": {
            "data_agent_semantic_assets_pkey": "text2sql_semantic_assets_pkey",
            "data_agent_semantic_assets_user_id_fkey": "text2sql_semantic_assets_user_id_fkey",
            "data_agent_semantic_assets_data_source_id_fkey": (
                "text2sql_semantic_assets_data_source_id_fkey"
            ),
            "uq_data_agent_semantic_asset_version": "uq_text2sql_semantic_asset_version",
        },
        "data_agent_evaluation_cases": {
            "data_agent_evaluation_cases_pkey": "text2sql_evaluation_cases_pkey",
            "data_agent_evaluation_cases_user_id_fkey": ("text2sql_evaluation_cases_user_id_fkey"),
            "data_agent_evaluation_cases_data_source_id_fkey": (
                "text2sql_evaluation_cases_data_source_id_fkey"
            ),
        },
        "data_agent_feedback": {
            "data_agent_feedback_pkey": "text2sql_feedback_pkey",
            "data_agent_feedback_run_id_fkey": "text2sql_feedback_run_id_fkey",
            "data_agent_feedback_user_id_fkey": "text2sql_feedback_user_id_fkey",
        },
    }
    for table_name, names in constraint_renames.items():
        for old_name, new_name in names.items():
            op.execute(
                sa.text(
                    f'ALTER TABLE "{table_name}" RENAME CONSTRAINT "{old_name}" TO "{new_name}"'
                )
            )
    index_renames = {
        "ix_data_agent_runs_user_id": "ix_text2sql_runs_user_id",
        "ix_data_agent_runs_tenant_id": "ix_text2sql_runs_tenant_id",
        "ix_data_agent_runs_workspace_id": "ix_text2sql_runs_workspace_id",
        "ix_data_agent_runs_project_id": "ix_text2sql_runs_project_id",
        "ix_data_agent_runs_data_source_id": "ix_text2sql_runs_data_source_id",
        "ix_data_agent_runs_state": "ix_text2sql_runs_state",
        "ix_data_agent_runs_schema_fingerprint": "ix_text2sql_runs_schema_fingerprint",
        "ix_data_agent_runs_created_at": "ix_text2sql_runs_created_at",
        "ix_data_agent_runs_scope_created": "ix_text2sql_runs_scope_created",
        "ix_data_agent_run_events_run_id": "ix_text2sql_run_events_run_id",
        "ix_data_agent_run_events_event_type": "ix_text2sql_run_events_event_type",
        "ix_data_agent_semantic_assets_user_id": "ix_text2sql_semantic_assets_user_id",
        "ix_data_agent_semantic_assets_tenant_id": "ix_text2sql_semantic_assets_tenant_id",
        "ix_data_agent_semantic_assets_workspace_id": "ix_text2sql_semantic_assets_workspace_id",
        "ix_data_agent_semantic_assets_project_id": "ix_text2sql_semantic_assets_project_id",
        "ix_data_agent_semantic_assets_data_source_id": "ix_text2sql_semantic_assets_data_source_id",
        "ix_data_agent_semantic_assets_asset_type": "ix_text2sql_semantic_assets_asset_type",
        "ix_data_agent_semantic_assets_status": "ix_text2sql_semantic_assets_status",
        "ix_data_agent_evaluation_cases_user_id": "ix_text2sql_evaluation_cases_user_id",
        "ix_data_agent_evaluation_cases_tenant_id": "ix_text2sql_evaluation_cases_tenant_id",
        "ix_data_agent_evaluation_cases_workspace_id": "ix_text2sql_evaluation_cases_workspace_id",
        "ix_data_agent_evaluation_cases_data_source_id": "ix_text2sql_evaluation_cases_data_source_id",
        "ix_data_agent_evaluation_cases_status": "ix_text2sql_evaluation_cases_status",
        "ix_data_agent_eval_scope": "ix_text2sql_eval_scope",
        "ix_data_agent_feedback_run_id": "ix_text2sql_feedback_run_id",
        "ix_data_agent_feedback_user_id": "ix_text2sql_feedback_user_id",
        "ix_data_agent_feedback_tenant_id": "ix_text2sql_feedback_tenant_id",
        "ix_data_agent_feedback_workspace_id": "ix_text2sql_feedback_workspace_id",
    }
    for old_name, new_name in index_renames.items():
        op.execute(sa.text(f'ALTER INDEX IF EXISTS "{old_name}" RENAME TO "{new_name}"'))

    op.rename_table("data_agent_feedback", "text2sql_feedback")
    op.rename_table("data_agent_evaluation_cases", "text2sql_evaluation_cases")
    op.rename_table("data_agent_semantic_assets", "text2sql_semantic_assets")
    op.rename_table("data_agent_run_events", "text2sql_run_events")
    op.rename_table("data_agent_runs", "text2sql_runs")
