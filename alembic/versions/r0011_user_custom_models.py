"""Add user-scoped custom models and unified model selection.

Revision ID: r0011_user_custom_models
Revises: r0010_beijing_timezone_defaults
Create Date: 2026-07-31 14:45:03.060011
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0011_user_custom_models"
down_revision = "r0010_beijing_timezone_defaults"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    table_names = set(inspector.get_table_names())
    if "user_custom_models" not in table_names:
        op.create_table(
            "user_custom_models",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column(
                "user_id",
                sa.String(36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("provider", sa.String(128), nullable=False, server_default="自定义 / Custom"),
            sa.Column("base_url", sa.Text(), nullable=False),
            sa.Column("api_key_encrypted", sa.Text(), nullable=False),
            sa.Column("model", sa.String(255), nullable=False),
            sa.Column("api_mode", sa.String(32), nullable=False, server_default="chat_completions"),
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
                "user_id",
                "tenant_id",
                "workspace_id",
                "name",
                name="uq_user_custom_models_scope_name",
            ),
        )
    for column in ("user_id", "tenant_id", "workspace_id"):
        op.execute(
            f"CREATE INDEX IF NOT EXISTS ix_user_custom_models_{column} "
            f"ON user_custom_models ({column})"
        )

    existing_columns = (
        {column["name"] for column in inspector.get_columns("user_model_settings")}
        if "user_model_settings" in table_names
        else set()
    )
    if "active_source" not in existing_columns:
        op.add_column(
            "user_model_settings",
            sa.Column("active_source", sa.String(20), nullable=False, server_default="free"),
        )
    if "active_free_model" not in existing_columns:
        op.add_column(
            "user_model_settings",
            sa.Column("active_free_model", sa.String(255), nullable=False, server_default=""),
        )
    if "active_custom_model_id" not in existing_columns:
        op.add_column(
            "user_model_settings",
            sa.Column("active_custom_model_id", sa.String(36), nullable=True),
        )
    existing_foreign_keys = (
        {key.get("name") for key in inspector.get_foreign_keys("user_model_settings")}
        if "user_model_settings" in table_names and hasattr(inspector, "get_foreign_keys")
        else set()
    )
    if "fk_user_model_settings_active_custom_model_id" not in existing_foreign_keys:
        op.create_foreign_key(
            "fk_user_model_settings_active_custom_model_id",
            "user_model_settings",
            "user_custom_models",
            ["active_custom_model_id"],
            ["id"],
            ondelete="SET NULL",
        )

    # 已保存独立密钥的旧端点转为自定义模型；环境变量密钥不会复制进用户数据。
    op.execute(
        """
        INSERT INTO user_custom_models (
            id, user_id, tenant_id, workspace_id, name, provider, base_url,
            api_key_encrypted, model, api_mode
        )
        SELECT
            substr(md5(id || ':' || 'official'), 1, 8) || '-' ||
            substr(md5(id || ':' || 'official'), 9, 4) || '-' ||
            substr(md5(id || ':' || 'official'), 13, 4) || '-' ||
            substr(md5(id || ':' || 'official'), 17, 4) || '-' ||
            substr(md5(id || ':' || 'official'), 21, 12),
            user_id, tenant_id, workspace_id,
            left('原始服务 - ' || official_model, 128),
            COALESCE(NULLIF(official_provider, ''), '自定义 / Custom'),
            official_base_url, official_api_key_encrypted, official_model,
            COALESCE(NULLIF(official_api_mode, ''), 'chat_completions')
        FROM user_model_settings
        WHERE official_api_key_encrypted IS NOT NULL
          AND official_base_url <> '' AND official_model <> ''
        ON CONFLICT (user_id, tenant_id, workspace_id, name) DO NOTHING
        """
    )
    op.execute(
        """
        INSERT INTO user_custom_models (
            id, user_id, tenant_id, workspace_id, name, provider, base_url,
            api_key_encrypted, model, api_mode
        )
        SELECT
            substr(md5(id || ':' || 'relay'), 1, 8) || '-' ||
            substr(md5(id || ':' || 'relay'), 9, 4) || '-' ||
            substr(md5(id || ':' || 'relay'), 13, 4) || '-' ||
            substr(md5(id || ':' || 'relay'), 17, 4) || '-' ||
            substr(md5(id || ':' || 'relay'), 21, 12),
            user_id, tenant_id, workspace_id,
            left('中转服务 - ' || relay_model, 128),
            COALESCE(NULLIF(relay_provider, ''), '自定义 / Custom'),
            relay_base_url, relay_api_key_encrypted, relay_model,
            COALESCE(NULLIF(relay_api_mode, ''), 'chat_completions')
        FROM user_model_settings
        WHERE relay_api_key_encrypted IS NOT NULL
          AND relay_base_url <> '' AND relay_model <> ''
        ON CONFLICT (user_id, tenant_id, workspace_id, name) DO NOTHING
        """
    )
    op.execute(
        """
        UPDATE user_model_settings
        SET active_source = 'custom',
            active_custom_model_id = CASE active_profile
                WHEN 'official' THEN
                    substr(md5(id || ':' || 'official'), 1, 8) || '-' ||
                    substr(md5(id || ':' || 'official'), 9, 4) || '-' ||
                    substr(md5(id || ':' || 'official'), 13, 4) || '-' ||
                    substr(md5(id || ':' || 'official'), 17, 4) || '-' ||
                    substr(md5(id || ':' || 'official'), 21, 12)
                WHEN 'relay' THEN
                    substr(md5(id || ':' || 'relay'), 1, 8) || '-' ||
                    substr(md5(id || ':' || 'relay'), 9, 4) || '-' ||
                    substr(md5(id || ':' || 'relay'), 13, 4) || '-' ||
                    substr(md5(id || ':' || 'relay'), 17, 4) || '-' ||
                    substr(md5(id || ':' || 'relay'), 21, 12)
            END
        WHERE (active_profile = 'official' AND official_api_key_encrypted IS NOT NULL
               AND official_base_url <> '' AND official_model <> '')
           OR (active_profile = 'relay' AND relay_api_key_encrypted IS NOT NULL
               AND relay_base_url <> '' AND relay_model <> '')
        """
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_user_model_settings_active_custom_model_id",
        "user_model_settings",
        type_="foreignkey",
    )
    op.drop_column("user_model_settings", "active_custom_model_id")
    op.drop_column("user_model_settings", "active_free_model")
    op.drop_column("user_model_settings", "active_source")
    op.drop_table("user_custom_models")
