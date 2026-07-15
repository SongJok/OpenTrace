"""Expand schema for the unified Responses agent runtime.

Revision ID: 20260723_unified_agent_runtime
Revises: 20260722_chatgpt_product_loop
"""

from __future__ import annotations

from alembic import op


revision = "20260723_unified_agent_runtime"
down_revision = "20260722_chatgpt_product_loop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for statement in (
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS project_id VARCHAR(36)",
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS assistant_profile_id VARCHAR(36)",
        "ALTER TABLE chat_sessions ADD COLUMN IF NOT EXISTS conversation_instructions TEXT",
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_project_id ON chat_sessions (project_id)",
        "CREATE INDEX IF NOT EXISTS ix_chat_sessions_assistant_profile_id ON chat_sessions (assistant_profile_id)",
        "ALTER TABLE responses ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1",
        "ALTER TABLE responses ADD COLUMN IF NOT EXISTS goal_id VARCHAR(36)",
        "CREATE INDEX IF NOT EXISTS ix_responses_goal_id ON responses (goal_id)",
        "ALTER TABLE response_tool_executions ADD COLUMN IF NOT EXISTS side_effect_level VARCHAR(20) NOT NULL DEFAULT 'read'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS scope_type VARCHAR(20) NOT NULL DEFAULT 'user'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS memory_key VARCHAR(128)",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_memory_key ON user_memories (memory_key)",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS scope_id VARCHAR(64)",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active'",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS salience DOUBLE PRECISION NOT NULL DEFAULT 0.5",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS source_response_id VARCHAR(64)",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS supersedes_id VARCHAR(36)",
        "ALTER TABLE user_memories ADD COLUMN IF NOT EXISTS expires_at TIMESTAMP WITH TIME ZONE",
        "CREATE INDEX IF NOT EXISTS ix_user_memories_scope ON user_memories (user_id, scope_type, scope_id, status)",
        "ALTER TABLE task_definitions ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE task_definitions ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(128) NOT NULL DEFAULT 'default'",
        "ALTER TABLE task_definitions ADD COLUMN IF NOT EXISTS project_id VARCHAR(36)",
        "ALTER TABLE task_definitions ADD COLUMN IF NOT EXISTS conversation_id VARCHAR(36)",
        "ALTER TABLE task_definitions ADD COLUMN IF NOT EXISTS rrule VARCHAR(512)",
        "ALTER TABLE task_definitions ADD COLUMN IF NOT EXISTS timezone VARCHAR(64) NOT NULL DEFAULT 'UTC'",
        "ALTER TABLE task_definitions ADD COLUMN IF NOT EXISTS requires_confirmation BOOLEAN NOT NULL DEFAULT TRUE",
        "ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS scheduled_for TIMESTAMP WITH TIME ZONE",
        "ALTER TABLE task_runs ADD COLUMN IF NOT EXISTS response_id VARCHAR(64)",
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_task_run_schedule ON task_runs (task_id, scheduled_for) WHERE scheduled_for IS NOT NULL",
    ):
        op.execute(statement)

    op.execute("""
        CREATE TABLE IF NOT EXISTS assistant_profiles (
            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default', workspace_id VARCHAR(128) NOT NULL DEFAULT 'default',
            name VARCHAR(100) NOT NULL, personality VARCHAR(20) NOT NULL DEFAULT 'none',
            instructions TEXT NOT NULL DEFAULT '', default_model_profile VARCHAR(20) NOT NULL DEFAULT 'auto',
            tool_policy JSON NOT NULL DEFAULT '{}'::json, memory_policy JSON NOT NULL DEFAULT '{}'::json,
            built_in BOOLEAN NOT NULL DEFAULT FALSE, is_default BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_assistant_profile_name UNIQUE (user_id, tenant_id, name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_assistant_profiles_user_id ON assistant_profiles (user_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default', workspace_id VARCHAR(128) NOT NULL DEFAULT 'default',
            name VARCHAR(255) NOT NULL, description TEXT NOT NULL DEFAULT '', instructions TEXT NOT NULL DEFAULT '',
            assistant_profile_id VARCHAR(36), data_source_ids JSON NOT NULL DEFAULT '[]'::json,
            archived_at TIMESTAMP WITH TIME ZONE,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_projects_owner_scope ON projects (user_id, tenant_id, workspace_id)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS response_approvals (
            id VARCHAR(64) PRIMARY KEY, response_id VARCHAR(64) NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
            call_id VARCHAR(128) NOT NULL, tool_name VARCHAR(128) NOT NULL,
            side_effect_level VARCHAR(20) NOT NULL DEFAULT 'write', arguments JSON NOT NULL DEFAULT '{}'::json,
            status VARCHAR(20) NOT NULL DEFAULT 'pending', reason TEXT, resolved_by VARCHAR(36),
            resolved_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_response_approval_call UNIQUE (response_id, call_id)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_response_approvals_status ON response_approvals (status)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS response_outbox (
            id VARCHAR(64) PRIMARY KEY, event_key VARCHAR(255) NOT NULL UNIQUE,
            aggregate_type VARCHAR(32) NOT NULL DEFAULT 'response', aggregate_id VARCHAR(64) NOT NULL,
            event_type VARCHAR(64) NOT NULL, payload JSON NOT NULL DEFAULT '{}'::json,
            status VARCHAR(20) NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0,
            available_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            published_at TIMESTAMP WITH TIME ZONE, last_error TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_response_outbox_pending ON response_outbox (status, available_at)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS goal_runs (
            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default', workspace_id VARCHAR(128) NOT NULL DEFAULT 'default',
            project_id VARCHAR(36), conversation_id VARCHAR(36), objective TEXT NOT NULL,
            success_criteria TEXT NOT NULL DEFAULT '', status VARCHAR(24) NOT NULL DEFAULT 'queued',
            plan JSON NOT NULL DEFAULT '{}'::json, current_step INTEGER NOT NULL DEFAULT 0,
            response_id VARCHAR(64), created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP WITH TIME ZONE
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_goal_runs_owner_status ON goal_runs (user_id, status)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS goal_checkpoints (
            id VARCHAR(36) PRIMARY KEY, goal_id VARCHAR(36) NOT NULL REFERENCES goal_runs(id) ON DELETE CASCADE,
            step_number INTEGER NOT NULL, status VARCHAR(20) NOT NULL DEFAULT 'completed', summary TEXT NOT NULL DEFAULT '',
            state JSON NOT NULL DEFAULT '{}'::json, created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_goal_checkpoint_step UNIQUE (goal_id, step_number)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS memory_candidates (
            id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(36) NOT NULL,
            tenant_id VARCHAR(128) NOT NULL DEFAULT 'default', workspace_id VARCHAR(128) NOT NULL DEFAULT 'default',
            response_id VARCHAR(64) NOT NULL REFERENCES responses(id) ON DELETE CASCADE,
            scope_type VARCHAR(20) NOT NULL DEFAULT 'user', scope_id VARCHAR(64), kind VARCHAR(30) NOT NULL DEFAULT 'fact',
            memory_key VARCHAR(128),
            content TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL, salience DOUBLE PRECISION NOT NULL DEFAULT 0.5,
            status VARCHAR(20) NOT NULL DEFAULT 'pending', rejection_reason TEXT,
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_memory_candidates_review ON memory_candidates (user_id, status)")
    op.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS memory_key VARCHAR(128)")
    op.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS tenant_id VARCHAR(128) NOT NULL DEFAULT 'default'")
    op.execute("ALTER TABLE memory_candidates ADD COLUMN IF NOT EXISTS workspace_id VARCHAR(128) NOT NULL DEFAULT 'default'")
    op.execute("CREATE INDEX IF NOT EXISTS ix_memory_candidates_memory_key ON memory_candidates (memory_key)")
    op.execute("""
        CREATE TABLE IF NOT EXISTS memory_evidence (
            id VARCHAR(36) PRIMARY KEY, memory_id VARCHAR(36),
            candidate_id VARCHAR(36) REFERENCES memory_candidates(id) ON DELETE CASCADE,
            response_id VARCHAR(64) NOT NULL, item_id VARCHAR(64), excerpt TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def downgrade() -> None:
    for table in (
        "memory_evidence", "memory_candidates", "goal_checkpoints", "goal_runs",
        "response_outbox", "response_approvals", "projects", "assistant_profiles",
    ):
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
