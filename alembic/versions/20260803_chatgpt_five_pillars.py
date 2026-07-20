"""Integrate durable memory graph and native audio/video attachments.

Revision ID: 20260803_chatgpt_five_pillars
Revises: 20260802_chat_constitution
"""

from __future__ import annotations

from alembic import op

revision = "20260803_chatgpt_five_pillars"
down_revision = "20260802_chat_constitution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_memory_relations (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            tenant_id VARCHAR(128) NOT NULL,
            workspace_id VARCHAR(128) NOT NULL,
            source_memory_id VARCHAR(36) NOT NULL REFERENCES user_memories(id) ON DELETE CASCADE,
            target_memory_id VARCHAR(36) NOT NULL REFERENCES user_memories(id) ON DELETE CASCADE,
            relation_type VARCHAR(32) NOT NULL DEFAULT 'related_to',
            weight DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            evidence_response_id VARCHAR(64),
            relation_metadata JSON NOT NULL DEFAULT '{}',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_user_memory_relation_edge UNIQUE (
                user_id, tenant_id, workspace_id,
                source_memory_id, target_memory_id, relation_type
            )
        )
        """
    )
    for column, definition in (
        ("media_base64", "TEXT"),
        ("media_mime", "VARCHAR(100)"),
        ("media_kind", "VARCHAR(20)"),
    ):
        op.execute(f"ALTER TABLE attachments ADD COLUMN IF NOT EXISTS {column} {definition}")
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_user_memory_relations_user_id ON user_memory_relations (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memory_relations_tenant_id ON user_memory_relations (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memory_relations_workspace_id ON user_memory_relations (workspace_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memory_relations_source_memory_id ON user_memory_relations (source_memory_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memory_relations_target_memory_id ON user_memory_relations (target_memory_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_memory_relations_relation_type ON user_memory_relations (relation_type)",
        "CREATE INDEX IF NOT EXISTS ix_user_memory_relations_evidence_response_id ON user_memory_relations (evidence_response_id)",
        "CREATE INDEX IF NOT EXISTS ix_attachments_media_kind ON attachments (media_kind)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_attachments_media_kind")
    for column in ("media_kind", "media_mime", "media_base64"):
        op.execute(f"ALTER TABLE attachments DROP COLUMN IF EXISTS {column}")
    op.execute("DROP TABLE IF EXISTS user_memory_relations")
