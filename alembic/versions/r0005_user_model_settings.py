"""Add scoped dynamic LLM endpoint settings.

Revision ID: r0005_user_model_settings
Revises: r0004_enterprise_runtime_governance
Create Date: 2026-07-29
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0005_user_model_settings"
down_revision = "r0004_enterprise_runtime_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "user_model_settings" not in inspector.get_table_names():
        op.create_table(
            "user_model_settings",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column(
                "active_profile", sa.String(20), nullable=False, server_default="environment"
            ),
            sa.Column("official_provider", sa.String(128), nullable=False, server_default=""),
            sa.Column("official_base_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("official_api_key_encrypted", sa.Text()),
            sa.Column("official_model", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "official_models",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column("official_api_mode", sa.String(32), nullable=False, server_default="auto"),
            sa.Column("relay_provider", sa.String(128), nullable=False, server_default=""),
            sa.Column("relay_base_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("relay_api_key_encrypted", sa.Text()),
            sa.Column("relay_model", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "relay_models",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'::json"),
            ),
            sa.Column(
                "relay_api_mode",
                sa.String(32),
                nullable=False,
                server_default="chat_completions",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "user_id", "tenant_id", "workspace_id", name="uq_user_model_settings_scope"
            ),
        )
    for statement in (
        "CREATE INDEX IF NOT EXISTS ix_user_model_settings_user_id "
        "ON user_model_settings (user_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_model_settings_tenant_id "
        "ON user_model_settings (tenant_id)",
        "CREATE INDEX IF NOT EXISTS ix_user_model_settings_workspace_id "
        "ON user_model_settings (workspace_id)",
    ):
        op.execute(statement)


def downgrade() -> None:
    op.drop_table("user_model_settings")
