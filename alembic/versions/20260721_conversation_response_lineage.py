"""Track active response and branch root for ChatGPT-style continuation."""

from __future__ import annotations

from alembic import op


revision = "20260721_conversation_response_lineage"
down_revision = "20260720_response_leases"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The development startup guard may have created these columns before
    # Alembic runs. PostgreSQL's IF NOT EXISTS keeps both paths idempotent.
    op.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS active_response_id VARCHAR(64)")
    op.execute("ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS branch_root_response_id VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_sessions_active_response_id ON chat_sessions (active_response_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chat_sessions_branch_root_response_id ON chat_sessions (branch_root_response_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_branch_root_response_id")
    op.execute("DROP INDEX IF EXISTS ix_chat_sessions_active_response_id")
    op.execute("ALTER TABLE chat_sessions DROP COLUMN IF EXISTS branch_root_response_id")
    op.execute("ALTER TABLE chat_sessions DROP COLUMN IF EXISTS active_response_id")
