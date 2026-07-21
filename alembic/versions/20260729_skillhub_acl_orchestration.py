"""Add SkillHub catalog, account installations, ACL and project knowledge rules.

Revision ID: 20260729_skillhub_acl
Revises: 20260728_active_alerts
"""

from __future__ import annotations

from alembic import op

revision = "20260729_skillhub_acl"
down_revision = "20260728_active_alerts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE IF EXISTS public.knowledge_rules ADD COLUMN IF NOT EXISTS project_id VARCHAR(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_knowledge_rules_project_id ON public.knowledge_rules (project_id)")
    op.execute("ALTER TABLE IF EXISTS public.data_query_logs ADD COLUMN IF NOT EXISTS feedback_metadata JSON NOT NULL DEFAULT '{}'")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.skill_catalog_entries (
            id VARCHAR(36) PRIMARY KEY, provider VARCHAR(64) NOT NULL DEFAULT 'skillhub',
            external_id VARCHAR(512) NOT NULL UNIQUE, name VARCHAR(255) NOT NULL,
            description TEXT NOT NULL DEFAULT '', github_owner VARCHAR(255) NOT NULL,
            github_repo VARCHAR(255) NOT NULL, skill_path VARCHAR(1024) NOT NULL,
            version VARCHAR(128), license VARCHAR(128), github_stars INTEGER NOT NULL DEFAULT 0,
            download_count INTEGER NOT NULL DEFAULT 0, security_score INTEGER,
            security_status VARCHAR(32) NOT NULL DEFAULT 'unknown', ai_score INTEGER,
            review_status VARCHAR(32) NOT NULL DEFAULT 'unknown', is_verified BOOLEAN NOT NULL DEFAULT FALSE,
            rank_popular INTEGER, rank_recent INTEGER, status VARCHAR(20) NOT NULL DEFAULT 'active',
            source_metadata JSON NOT NULL DEFAULT '{}', synced_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_skill_catalog_popular ON public.skill_catalog_entries (status, rank_popular)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_skill_catalog_recent ON public.skill_catalog_entries (status, rank_recent)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.user_skill_installations (
            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default', workspace_id VARCHAR(128) NOT NULL DEFAULT 'default',
            catalog_skill_id VARCHAR(36) NOT NULL REFERENCES public.skill_catalog_entries(id) ON DELETE CASCADE, installed_skill_id VARCHAR(255) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'installed', install_mode VARCHAR(32) NOT NULL DEFAULT 'instruction_only',
            source_revision VARCHAR(128), manifest_snapshot JSON NOT NULL DEFAULT '{}', error TEXT,
            installed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(), updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_user_skill_installation_scope UNIQUE (user_id, tenant_id, workspace_id, catalog_skill_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_skill_installations_scope ON public.user_skill_installations (user_id, tenant_id, workspace_id, status)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS public.resource_permissions (
            id VARCHAR(36) PRIMARY KEY, tenant_id VARCHAR(128) NOT NULL DEFAULT 'default',
            workspace_id VARCHAR(128) NOT NULL DEFAULT 'default', subject_user_id VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
            resource_type VARCHAR(32) NOT NULL, resource_id VARCHAR(64) NOT NULL,
            permission VARCHAR(20) NOT NULL DEFAULT 'view', granted_by VARCHAR(36) NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
            expires_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT now(),
            CONSTRAINT uq_resource_permission_subject UNIQUE (tenant_id, workspace_id, subject_user_id, resource_type, resource_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_resource_permissions_lookup ON public.resource_permissions (subject_user_id, tenant_id, workspace_id, resource_type, resource_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS public.resource_permissions")
    op.execute("DROP TABLE IF EXISTS public.user_skill_installations")
    op.execute("DROP TABLE IF EXISTS public.skill_catalog_entries")
    op.execute("ALTER TABLE IF EXISTS public.data_query_logs DROP COLUMN IF EXISTS feedback_metadata")
    op.execute("ALTER TABLE IF EXISTS public.knowledge_rules DROP COLUMN IF EXISTS project_id")
