"""Add versioned memory constitution, decision audits and reinforcement fields.

Revision ID: 20260731_memory_constitution
Revises: 20260730_ds_schema_embedding
"""

from __future__ import annotations

from alembic import op


revision = "20260731_memory_constitution"
down_revision = "20260730_ds_schema_embedding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_constitutions (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL,
            workspace_id VARCHAR(128) NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            rules_json TEXT NOT NULL DEFAULT '{}',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_by VARCHAR(36) NOT NULL,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_memory_constitution_scope_version
                UNIQUE (tenant_id, workspace_id, version)
        )
        """
    )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_memory_constitutions_tenant_id ON memory_constitutions (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_memory_constitutions_workspace_id ON memory_constitutions (workspace_id)",
        "CREATE INDEX IF NOT EXISTS ix_memory_constitutions_is_active ON memory_constitutions (is_active)",
        "CREATE INDEX IF NOT EXISTS ix_memory_constitutions_created_by ON memory_constitutions (created_by)",
    ):
        op.execute(statement)

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS memory_constitution_audits (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(128) NOT NULL,
            workspace_id VARCHAR(128) NOT NULL,
            actor_user_id VARCHAR(36),
            subject_user_id VARCHAR(36),
            response_id VARCHAR(64),
            memory_id VARCHAR(36),
            candidate_id VARCHAR(36),
            constitution_version INTEGER NOT NULL DEFAULT 0,
            decision VARCHAR(20) NOT NULL,
            reason_code VARCHAR(64) NOT NULL,
            categories_json TEXT NOT NULL DEFAULT '[]',
            content_hash VARCHAR(64) NOT NULL,
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
        "response_id",
        "memory_id",
        "candidate_id",
        "decision",
        "reason_code",
        "source",
    ):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_memory_constitution_audits_{column} "
            f"ON memory_constitution_audits ({column})"
        )

    op.execute(
        "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS "
        "observations INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS "
        "learning_mode VARCHAR(20) NOT NULL DEFAULT 'model'"
    )
    op.execute(
        "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS "
        "constitution_version INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS "
        "last_observed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP"
    )


def downgrade() -> None:
    for column in (
        "last_observed_at",
        "constitution_version",
        "learning_mode",
        "observations",
    ):
        op.execute(f"ALTER TABLE memory_candidates DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS memory_constitution_audits")
    op.execute("DROP TABLE IF EXISTS memory_constitutions")
