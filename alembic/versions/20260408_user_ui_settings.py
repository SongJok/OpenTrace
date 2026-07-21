"""user ui settings

Revision ID: 20260408_ui_settings
Revises: 20260407_audit_ret
Create Date: 2026-04-08
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260408_ui_settings"
down_revision = "20260407_audit_ret"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_ui_settings",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False, unique=True),
        sa.Column("reasoning_default_expanded", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("graph_default_expanded", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_user_ui_settings_user", "user_ui_settings", ["user_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_user_ui_settings_user", table_name="user_ui_settings")
    op.drop_table("user_ui_settings")
