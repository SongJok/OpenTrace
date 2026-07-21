"""tasks notifications

Revision ID: 20260407_task_notify
Revises: 20260407_task_stage1
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260407_task_notify"
down_revision = "20260407_task_stage1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_notifications",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("level", sa.String(length=20), nullable=False, server_default="info"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_task_notifications_user", "task_notifications", ["user_id"], unique=False)
    op.create_index("ix_task_notifications_task", "task_notifications", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_notifications_task", table_name="task_notifications")
    op.drop_index("ix_task_notifications_user", table_name="task_notifications")
    op.drop_table("task_notifications")
