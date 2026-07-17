"""Add temporary chats, safe share snapshots and expanded UI preferences."""

from __future__ import annotations

from alembic import op


revision = "20260722_chatgpt_product_loop"
down_revision = "20260721_conversation_response_lineage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS is_temporary BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_sessions_is_temporary ON chat_sessions (is_temporary)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_sessions_expires_at ON chat_sessions (expires_at)")
    for column, definition in (
        ("dag_default_expanded", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("execution_graph_default_expanded", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("decision_trace_default_expanded", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("flow_cards_default_expanded", "BOOLEAN NOT NULL DEFAULT TRUE"),
        ("theme_mode", "VARCHAR(20) NOT NULL DEFAULT 'system'"),
        ("theme_accent", "VARCHAR(32) NOT NULL DEFAULT 'blue'"),
    ):
        op.execute(f"ALTER TABLE user_ui_settings ADD COLUMN IF NOT EXISTS {column} {definition}")
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversation_shares (
            id VARCHAR(36) PRIMARY KEY,
            conversation_id VARCHAR(36) NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            public_id VARCHAR(64) NOT NULL UNIQUE,
            token_hash VARCHAR(128) NOT NULL,
            snapshot JSON NOT NULL DEFAULT '{}'::json,
            revoked_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_shares_conversation_id ON conversation_shares (conversation_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_shares_user_id ON conversation_shares (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_conversation_shares_revoked_at ON conversation_shares (revoked_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS conversation_shares")
    for column in ("theme_accent", "theme_mode", "flow_cards_default_expanded", "decision_trace_default_expanded", "execution_graph_default_expanded", "dag_default_expanded"):
        op.execute(f"ALTER TABLE user_ui_settings DROP COLUMN IF EXISTS {column}")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_is_temporary")
    op.execute("ALTER TABLE chat_sessions DROP COLUMN IF EXISTS expires_at")
    op.execute("ALTER TABLE chat_sessions DROP COLUMN IF EXISTS is_temporary")
