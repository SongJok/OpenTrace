"""SQL 资产项目隔离与查询执行恢复

Revision ID: r0017_sql_asset_governance
Revises: r0016_sql_assets
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0017_sql_asset_governance"
down_revision = "r0016_sql_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sql_query_drafts",
        sa.Column("execution_started_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.drop_constraint(
        "uq_sql_asset_source_scope_hash",
        "sql_asset_sources",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sql_asset_source_scope_hash",
        "sql_asset_sources",
        ["tenant_id", "workspace_id", "data_source_id", "project_id", "content_sha256"],
    )
    op.create_index(
        "uq_sql_asset_source_global_hash",
        "sql_asset_sources",
        ["tenant_id", "workspace_id", "data_source_id", "content_sha256"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )

    op.drop_constraint("uq_sql_asset_scope_hash", "sql_assets", type_="unique")
    op.create_unique_constraint(
        "uq_sql_asset_scope_hash",
        "sql_assets",
        ["tenant_id", "workspace_id", "data_source_id", "project_id", "sql_hash"],
    )
    op.create_index(
        "uq_sql_asset_global_hash",
        "sql_assets",
        ["tenant_id", "workspace_id", "data_source_id", "sql_hash"],
        unique=True,
        postgresql_where=sa.text("project_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_sql_asset_global_hash", table_name="sql_assets")
    op.drop_constraint("uq_sql_asset_scope_hash", "sql_assets", type_="unique")
    op.create_unique_constraint(
        "uq_sql_asset_scope_hash",
        "sql_assets",
        ["tenant_id", "workspace_id", "data_source_id", "sql_hash"],
    )

    op.drop_index("uq_sql_asset_source_global_hash", table_name="sql_asset_sources")
    op.drop_constraint(
        "uq_sql_asset_source_scope_hash",
        "sql_asset_sources",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_sql_asset_source_scope_hash",
        "sql_asset_sources",
        ["tenant_id", "workspace_id", "data_source_id", "content_sha256"],
    )

    op.drop_column("sql_query_drafts", "execution_started_at")
