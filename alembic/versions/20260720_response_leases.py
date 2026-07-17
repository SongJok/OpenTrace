"""Add durable Response worker leases and tool idempotency ledger."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260720_response_leases"
down_revision = "20260719_response_model_calls"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Development startup performs a best-effort schema repair before the
    # migration runner.  Keep this revision safe when those columns/indexes
    # already exist (and when an interrupted migration is resumed).
    op.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS request_payload JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS lease_owner VARCHAR(128)")
    op.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS lease_expires_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMP WITH TIME ZONE")
    op.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE responses ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 3")
    op.execute("CREATE INDEX IF NOT EXISTS ix_responses_lease_owner ON responses (lease_owner)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_responses_lease_expires_at ON responses (lease_expires_at)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS response_tool_executions (
            id VARCHAR(64) PRIMARY KEY,
            response_id VARCHAR(64) NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
            call_id VARCHAR(128) NOT NULL,
            idempotency_key VARCHAR(255) NOT NULL,
            tool_name VARCHAR(128) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            arguments JSON NOT NULL DEFAULT '{}'::json,
            result JSON NOT NULL DEFAULT '{}'::json,
            error_message TEXT,
            side_effect BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP WITH TIME ZONE,
            CONSTRAINT uq_response_tool_execution_call UNIQUE (response_id, call_id),
            CONSTRAINT uq_response_tool_execution_idempotency UNIQUE (idempotency_key)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_response_tool_executions_response_id ON response_tool_executions (response_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_response_tool_executions_status ON response_tool_executions (status)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_response_tool_executions_status")
    op.execute("DROP INDEX IF EXISTS ix_response_tool_executions_response_id")
    op.execute("DROP TABLE IF EXISTS response_tool_executions")
    op.execute("DROP INDEX IF EXISTS ix_responses_lease_expires_at")
    op.execute("DROP INDEX IF EXISTS ix_responses_lease_owner")
    op.execute("ALTER TABLE responses DROP COLUMN IF EXISTS max_attempts")
    op.execute("ALTER TABLE responses DROP COLUMN IF EXISTS attempt_count")
    op.execute("ALTER TABLE responses DROP COLUMN IF EXISTS heartbeat_at")
    op.execute("ALTER TABLE responses DROP COLUMN IF EXISTS lease_expires_at")
    op.execute("ALTER TABLE responses DROP COLUMN IF EXISTS lease_owner")
    op.execute("ALTER TABLE responses DROP COLUMN IF EXISTS request_payload")
