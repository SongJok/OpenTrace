"""remove Project scope and add governed database access mode

Revision ID: r0024_remove_projects
Revises: r0023_enterprise_data_answer_loop
Create Date: 2026-08-11 18:30:00
"""

from __future__ import annotations

from alembic import op

revision = "r0024_remove_projects"
down_revision = "r0023_enterprise_data_answer_loop"
branch_labels = None
depends_on = None


PROJECT_COLUMNS = (
    "chat_sessions",
    "documents",
    "knowledge_sources",
    "knowledge_compilation_jobs",
    "knowledge_rules",
    "goal_runs",
    "task_definitions",
    "alert_rules",
    "sql_asset_sources",
    "sql_assets",
    "sql_query_drafts",
    "data_agent_runs",
    "data_agent_semantic_assets",
    "data_agent_learning_patterns",
)


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.data_sources ADD COLUMN IF NOT EXISTS "
        "access_mode VARCHAR(20) NOT NULL DEFAULT 'workspace'"
    )
    op.execute(
        "UPDATE public.knowledge_spaces SET space_type = 'workspace' "
        "WHERE space_type = 'project'"
    )
    op.execute(
        "UPDATE public.user_memories SET scope_type = 'user', scope_id = user_id "
        "WHERE scope_type = 'project'"
    )
    op.execute(
        "UPDATE public.memory_candidates SET scope_type = 'user', scope_id = user_id "
        "WHERE scope_type = 'project'"
    )
    op.execute(
        "DELETE FROM public.data_agent_learning_patterns WHERE project_id IS NOT NULL"
    )
    op.execute(
        "DELETE FROM public.resource_permissions WHERE resource_type = 'project'"
    )
    op.execute(
        "DELETE FROM public.knowledge_space_members WHERE subject_type = 'project'"
    )
    op.execute(
        "DELETE FROM public.knowledge_principal_memberships WHERE principal_type = 'project'"
    )

    for index_name in (
        "uq_sql_asset_source_global_hash",
        "uq_sql_asset_global_hash",
        "ix_alert_rules_scope",
    ):
        op.execute(f"DROP INDEX IF EXISTS public.{index_name}")
    for table, constraint in (
        ("sql_asset_sources", "uq_sql_asset_source_scope_hash"),
        ("sql_assets", "uq_sql_asset_scope_hash"),
    ):
        op.execute(
            f"ALTER TABLE public.{table} DROP CONSTRAINT IF EXISTS {constraint}"
        )

    for table in PROJECT_COLUMNS:
        op.execute(f"DROP INDEX IF EXISTS public.ix_{table}_project_id")
        op.execute(
            f"ALTER TABLE IF EXISTS public.{table} DROP COLUMN IF EXISTS project_id"
        )

    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_alert_rules_scope "
        "ON public.alert_rules (user_id, tenant_id, workspace_id)"
    )
    op.execute("DROP TABLE IF EXISTS public.knowledge_space_projects")
    op.execute("DROP TABLE IF EXISTS public.projects")


def downgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS public.projects ("
        "id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL, "
        "tenant_id VARCHAR(128) NOT NULL DEFAULT 'default', "
        "workspace_id VARCHAR(128) NOT NULL DEFAULT 'default', "
        "name VARCHAR(255) NOT NULL, description TEXT NOT NULL DEFAULT '', "
        "instructions TEXT NOT NULL DEFAULT '', memory_mode VARCHAR(20) NOT NULL DEFAULT 'default', "
        "assistant_profile_id VARCHAR(36), data_source_ids JSONB NOT NULL DEFAULT '[]'::jsonb, "
        "archived_at TIMESTAMPTZ, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
        "updated_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS public.knowledge_space_projects ("
        "id VARCHAR(36) PRIMARY KEY, space_id VARCHAR(36) NOT NULL, "
        "project_id VARCHAR(36) NOT NULL, tenant_id VARCHAR(128) NOT NULL DEFAULT 'default', "
        "workspace_id VARCHAR(128) NOT NULL DEFAULT 'default', attached_by VARCHAR(36) NOT NULL, "
        "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    for table in PROJECT_COLUMNS:
        op.execute(
            f"ALTER TABLE IF EXISTS public.{table} "
            "ADD COLUMN IF NOT EXISTS project_id VARCHAR(36)"
        )
    op.execute("DROP INDEX IF EXISTS public.ix_alert_rules_scope")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_alert_rules_scope "
        "ON public.alert_rules (user_id, tenant_id, workspace_id, project_id)"
    )
    op.execute("ALTER TABLE public.data_sources DROP COLUMN IF EXISTS access_mode")
