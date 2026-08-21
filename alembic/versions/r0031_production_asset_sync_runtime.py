"""生产资产同步运行、租约与来源可追溯字段

Revision ID: r0031_production_asset_sync_runtime
Revises: r0030_config_intelligence
Create Date: 2026-08-20 16:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0031_production_asset_sync_runtime"
down_revision = "r0030_config_intelligence"
branch_labels = None
depends_on = None


def _enable_scope_rls(table: str) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f"""CREATE POLICY "{table}_scope_isolation" ON "{table}"
            USING (
                current_setting('app.service_role', true) = 'worker'
                OR (
                    tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                    AND workspace_id = COALESCE(NULLIF(current_setting('app.workspace_id', true), ''), 'default')
                )
            )
            WITH CHECK (
                current_setting('app.service_role', true) = 'worker'
                OR (
                    tenant_id = COALESCE(NULLIF(current_setting('app.tenant_id', true), ''), 'default')
                    AND workspace_id = COALESCE(NULLIF(current_setting('app.workspace_id', true), ''), 'default')
                )
            )""")


def upgrade() -> None:
    op.create_table(
        "production_asset_sync_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("source_key", sa.String(128), nullable=False),
        sa.Column(
            "connector_id",
            sa.String(36),
            sa.ForeignKey("enterprise_connectors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("input_hash", sa.String(80), nullable=False),
        sa.Column("cursor_before", sa.String(512), nullable=True),
        sa.Column("cursor_after", sa.String(512), nullable=True),
        sa.Column("authoritative", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("lease_owner", sa.String(128), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("stats", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "requested_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "source_key",
            "idempotency_key",
            name="uq_production_asset_sync_idempotency",
        ),
    )
    op.create_index(
        "ix_production_asset_sync_scope_source_status",
        "production_asset_sync_runs",
        ["tenant_id", "workspace_id", "source_key", "status", "started_at"],
    )
    for column in (
        "tenant_id",
        "workspace_id",
        "source_key",
        "connector_id",
        "status",
        "input_hash",
        "lease_expires_at",
        "requested_by",
    ):
        op.create_index(
            f"ix_production_asset_sync_runs_{column}", "production_asset_sync_runs", [column]
        )

    for table in ("production_assets", "production_asset_relations"):
        op.add_column(table, sa.Column("source_key", sa.String(128), nullable=True))
        op.add_column(table, sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(table, sa.Column("last_sync_run_id", sa.String(36), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_last_sync_run_id",
            table,
            "production_asset_sync_runs",
            ["last_sync_run_id"],
            ["id"],
            ondelete="SET NULL",
        )
        op.create_index(f"ix_{table}_source_key", table, ["source_key"])
        op.create_index(f"ix_{table}_last_seen_at", table, ["last_seen_at"])
        op.create_index(f"ix_{table}_last_sync_run_id", table, ["last_sync_run_id"])

    _enable_scope_rls("production_asset_sync_runs")


def downgrade() -> None:
    for table in ("production_asset_relations", "production_assets"):
        op.drop_index(f"ix_{table}_last_sync_run_id", table_name=table)
        op.drop_index(f"ix_{table}_last_seen_at", table_name=table)
        op.drop_index(f"ix_{table}_source_key", table_name=table)
        op.drop_constraint(f"fk_{table}_last_sync_run_id", table, type_="foreignkey")
        op.drop_column(table, "last_sync_run_id")
        op.drop_column(table, "last_seen_at")
        op.drop_column(table, "source_key")
    op.drop_table("production_asset_sync_runs")
