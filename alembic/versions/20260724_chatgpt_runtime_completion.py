"""Complete project memory isolation for the ChatGPT-style runtime.

Revision ID: 20260724_chatgpt_runtime_completion
Revises: 20260723_unified_agent_runtime
"""

from __future__ import annotations

from alembic import op


revision = "20260724_chatgpt_runtime_completion"
down_revision = "20260723_unified_agent_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE projects ADD COLUMN IF NOT EXISTS memory_mode "
        "VARCHAR(20) NOT NULL DEFAULT 'default'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS memory_mode")
