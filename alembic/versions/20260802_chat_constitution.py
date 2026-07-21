"""Add versioned chat constitution and privacy-preserving decision audits.

Revision ID: 20260802_chat_constitution
Revises: 20260801_memory_constitution_concurrency
"""

from __future__ import annotations

from alembic import op

revision = "20260802_chat_constitution"
down_revision = "20260801_memory_constitution_concurrency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_constitutions (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL,
            workspace_id VARCHAR(128) NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            rules_json TEXT NOT NULL DEFAULT '{}',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by VARCHAR(36) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_chat_constitution_scope_version
                UNIQUE (tenant_id, workspace_id, version)
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_chat_constitutions_tenant_id ON chat_constitutions (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_chat_constitutions_workspace_id ON chat_constitutions (workspace_id)",
        "CREATE INDEX IF NOT EXISTS ix_chat_constitutions_is_active ON chat_constitutions (is_active)",
        "CREATE INDEX IF NOT EXISTS ix_chat_constitutions_created_by ON chat_constitutions (created_by)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_chat_constitution_active_scope ON chat_constitutions (tenant_id, workspace_id) WHERE is_active = TRUE",
    ):
        op.execute(statement)

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_constitution_audits (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL,
            workspace_id VARCHAR(128) NOT NULL,
            actor_user_id VARCHAR(36),
            subject_user_id VARCHAR(36),
            request_id VARCHAR(64),
            constitution_version INTEGER NOT NULL DEFAULT 0,
            decision VARCHAR(20) NOT NULL,
            reason_code VARCHAR(64) NOT NULL,
            categories_json TEXT NOT NULL DEFAULT '[]',
            content_hash VARCHAR(64) NOT NULL,
            content_length INTEGER NOT NULL DEFAULT 0,
            source VARCHAR(32) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "actor_user_id",
        "subject_user_id",
        "request_id",
        "decision",
        "reason_code",
        "source",
    ):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_chat_constitution_audits_{column} "
            f"ON chat_constitution_audits ({column})"
        )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_constitution_audits")
    op.execute("DROP TABLE IF EXISTS chat_constitutions")
