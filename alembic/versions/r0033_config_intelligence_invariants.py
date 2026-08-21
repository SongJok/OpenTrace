"""配置策略与当前快照唯一事实约束

Revision ID: r0033_config_intelligence_invariants
Revises: r0032_four_eye_production_approvals
Create Date: 2026-08-20 19:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0033_config_intelligence_invariants"
down_revision = "r0032_four_eye_production_approvals"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY tenant_id, workspace_id, asset_id
                       ORDER BY version DESC, created_at DESC, id DESC
                   ) AS position
            FROM production_config_policies
            WHERE status = 'published'
        )
        UPDATE production_config_policies
           SET status = 'retired'
         WHERE id IN (SELECT id FROM ranked WHERE position > 1)
        """)
    op.execute("""
        WITH ranked AS (
            SELECT id,
                   ROW_NUMBER() OVER (
                       PARTITION BY tenant_id, workspace_id, asset_id, environment
                       ORDER BY observed_at DESC, created_at DESC, id DESC
                   ) AS position
            FROM production_config_snapshots
            WHERE status = 'current'
        )
        UPDATE production_config_snapshots
           SET status = 'historical'
         WHERE id IN (SELECT id FROM ranked WHERE position > 1)
        """)
    op.create_index(
        "uq_production_config_policy_published_asset",
        "production_config_policies",
        ["tenant_id", "workspace_id", "asset_id"],
        unique=True,
        postgresql_where=sa.text("status = 'published'"),
        sqlite_where=sa.text("status = 'published'"),
    )
    op.create_index(
        "uq_production_config_snapshot_current_asset_environment",
        "production_config_snapshots",
        ["tenant_id", "workspace_id", "asset_id", "environment"],
        unique=True,
        postgresql_where=sa.text("status = 'current'"),
        sqlite_where=sa.text("status = 'current'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_production_config_snapshot_current_asset_environment",
        table_name="production_config_snapshots",
    )
    op.drop_index(
        "uq_production_config_policy_published_asset",
        table_name="production_config_policies",
    )
