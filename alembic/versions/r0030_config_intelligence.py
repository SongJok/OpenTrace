"""配置智能策略、快照与校验运行

Revision ID: r0030_config_intelligence
Revises: r0029_production_intelligence_foundation
Create Date: 2026-08-20 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0030_config_intelligence"
down_revision = "r0029_production_intelligence_foundation"
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
        "production_config_policies",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("production_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("reference_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("business_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("history_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("capacity_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("conflict_rules", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("dry_run_operation", sa.String(128), nullable=True),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "published_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "asset_id",
            "version",
            name="uq_production_config_policy_asset_version",
        ),
    )
    op.create_index(
        "ix_production_config_policies_scope_asset_status",
        "production_config_policies",
        ["tenant_id", "workspace_id", "asset_id", "status"],
    )
    for column in ("asset_id", "status", "created_by"):
        op.create_index(
            f"ix_production_config_policies_{column}", "production_config_policies", [column]
        )

    op.create_table(
        "production_config_snapshots",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column(
            "response_id",
            sa.String(64),
            sa.ForeignKey("responses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("production_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            sa.String(36),
            sa.ForeignKey("production_config_policies.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("environment", sa.String(32), nullable=False, server_default="shared"),
        sa.Column("version_ref", sa.String(255), nullable=False),
        sa.Column("source_ref", sa.String(2048), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="current"),
        sa.Column("content", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "asset_id",
            "environment",
            "version_ref",
            name="uq_production_config_snapshot_version",
        ),
    )
    op.create_index(
        "ix_production_config_snapshots_scope_asset_environment",
        "production_config_snapshots",
        ["tenant_id", "workspace_id", "asset_id", "environment", "observed_at"],
    )
    for column in (
        "response_id",
        "asset_id",
        "policy_id",
        "status",
        "content_hash",
        "created_by",
    ):
        op.create_index(
            f"ix_production_config_snapshots_{column}", "production_config_snapshots", [column]
        )

    op.create_table(
        "production_config_validation_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column(
            "response_id",
            sa.String(64),
            sa.ForeignKey("responses.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("production_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "policy_id",
            sa.String(36),
            sa.ForeignKey("production_config_policies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("production_config_snapshots.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("candidate_hash", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("risk_level", sa.String(20), nullable=False, server_default="low"),
        sa.Column("checks", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("dry_run", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_production_config_validation_scope_response",
        "production_config_validation_runs",
        ["tenant_id", "workspace_id", "response_id", "created_at"],
    )
    op.create_index(
        "ix_production_config_validation_scope_asset_status",
        "production_config_validation_runs",
        ["tenant_id", "workspace_id", "asset_id", "status"],
    )
    for column in (
        "response_id",
        "asset_id",
        "policy_id",
        "snapshot_id",
        "candidate_hash",
        "status",
        "created_by",
    ):
        op.create_index(
            f"ix_production_config_validation_runs_{column}",
            "production_config_validation_runs",
            [column],
        )

    for table in (
        "production_config_policies",
        "production_config_snapshots",
        "production_config_validation_runs",
    ):
        _enable_scope_rls(table)


def downgrade() -> None:
    op.drop_table("production_config_validation_runs")
    op.drop_table("production_config_snapshots")
    op.drop_table("production_config_policies")
