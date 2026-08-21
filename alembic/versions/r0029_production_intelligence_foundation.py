"""生产智能平台资产图、连接器与证据基础表

Revision ID: r0029_production_intelligence_foundation
Revises: r0028_reconcile_legacy_approval_class
Create Date: 2026-08-20 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0029_production_intelligence_foundation"
down_revision = "r0028_reconcile_legacy_approval_class"
branch_labels = None
depends_on = None


def _timestamps() -> tuple[sa.Column, sa.Column]:
    return (
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )


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
        "enterprise_connectors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("connector_kind", sa.String(32), nullable=False),
        sa.Column("transport", sa.String(16), nullable=False, server_default="native"),
        sa.Column("endpoint", sa.String(1024), nullable=True),
        sa.Column("secret_ref", sa.String(512), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="disabled"),
        sa.Column("allowed_operations", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "allowed_environments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
        ),
        sa.Column("data_classification", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "name",
            name="uq_enterprise_connector_scope_name",
        ),
    )
    op.create_index(
        "ix_enterprise_connectors_scope_kind_status",
        "enterprise_connectors",
        ["tenant_id", "workspace_id", "connector_kind", "status"],
    )
    op.create_index("ix_enterprise_connectors_created_by", "enterprise_connectors", ["created_by"])

    op.create_table(
        "production_assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("asset_type", sa.String(32), nullable=False),
        sa.Column("external_key", sa.String(255), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("environment", sa.String(32), nullable=False, server_default="shared"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("criticality", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("classification", sa.String(20), nullable=False, server_default="internal"),
        sa.Column(
            "connector_id",
            sa.String(36),
            sa.ForeignKey("enterprise_connectors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "asset_type",
            "external_key",
            name="uq_production_asset_scope_external_key",
        ),
    )
    op.create_index(
        "ix_production_assets_scope_type_status",
        "production_assets",
        ["tenant_id", "workspace_id", "asset_type", "status"],
    )
    op.create_index(
        "ix_production_assets_scope_environment",
        "production_assets",
        ["tenant_id", "workspace_id", "environment"],
    )
    op.create_index("ix_production_assets_name", "production_assets", ["name"])
    op.create_index("ix_production_assets_connector_id", "production_assets", ["connector_id"])
    op.create_index("ix_production_assets_created_by", "production_assets", ["created_by"])

    op.create_table(
        "production_asset_relations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column(
            "source_asset_id",
            sa.String(36),
            sa.ForeignKey("production_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_asset_id",
            sa.String(36),
            sa.ForeignKey("production_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1"),
        sa.Column("source_kind", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_by",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        *_timestamps(),
        sa.UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "source_asset_id",
            "target_asset_id",
            "relation_type",
            name="uq_production_asset_relation_edge",
        ),
    )
    op.create_index(
        "ix_production_asset_relations_scope_source",
        "production_asset_relations",
        ["tenant_id", "workspace_id", "source_asset_id"],
    )
    op.create_index(
        "ix_production_asset_relations_scope_target",
        "production_asset_relations",
        ["tenant_id", "workspace_id", "target_asset_id"],
    )
    op.create_index(
        "ix_production_asset_relations_relation_type",
        "production_asset_relations",
        ["relation_type"],
    )
    op.create_index(
        "ix_production_asset_relations_created_by",
        "production_asset_relations",
        ["created_by"],
    )

    op.create_table(
        "production_evidence",
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
            "connector_id",
            sa.String(36),
            sa.ForeignKey("enterprise_connectors.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("production_assets.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("source_kind", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(2048), nullable=False),
        sa.Column("environment", sa.String(32), nullable=False, server_default="shared"),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "authority", sa.String(32), nullable=False, server_default="external_observation"
        ),
        sa.Column("permission_class", sa.String(20), nullable=False, server_default="internal"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "ix_production_evidence_scope_response",
        "production_evidence",
        ["tenant_id", "workspace_id", "response_id", "created_at"],
    )
    op.create_index(
        "ix_production_evidence_scope_type",
        "production_evidence",
        ["tenant_id", "workspace_id", "evidence_type", "environment"],
    )
    for column in ("connector_id", "asset_id", "content_hash"):
        op.create_index(f"ix_production_evidence_{column}", "production_evidence", [column])

    for table in (
        "enterprise_connectors",
        "production_assets",
        "production_asset_relations",
        "production_evidence",
    ):
        _enable_scope_rls(table)


def downgrade() -> None:
    op.drop_table("production_evidence")
    op.drop_table("production_asset_relations")
    op.drop_table("production_assets")
    op.drop_table("enterprise_connectors")
