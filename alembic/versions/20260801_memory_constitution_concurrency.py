"""Serialize active memory constitution versions at the database boundary.

Revision ID: 20260801_memory_constitution_concurrency
Revises: 20260731_memory_constitution
"""

from __future__ import annotations

from alembic import op

revision = "20260801_memory_constitution_concurrency"
down_revision = "20260731_memory_constitution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 历史版本保持不变；若旧版本曾因并发留下多个活动行，仅保留版本号最大的一个。
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY tenant_id, workspace_id
                       ORDER BY version DESC, created_at DESC, id DESC
                   ) AS position
            FROM memory_constitutions
            WHERE is_active = TRUE
        )
        UPDATE memory_constitutions AS constitution
        SET is_active = FALSE
        FROM ranked
        WHERE constitution.id = ranked.id AND ranked.position > 1
        """)
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_constitution_active_scope
        ON memory_constitutions (tenant_id, workspace_id)
        WHERE is_active = TRUE
        """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_memory_constitution_active_scope")
