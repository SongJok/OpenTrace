"""tasks stage1

Revision ID: 20260407_task_stage1
Revises: 20260407_mem_stage1
Create Date: 2026-04-07
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260407_task_stage1"
down_revision = "20260407_mem_stage1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_definitions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("trigger_type", sa.String(length=20), nullable=False, server_default="interval"),
        sa.Column("trigger_config_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index("ix_task_definitions_user", "task_definitions", ["user_id"], unique=False)

    op.create_table(
        "task_runs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("task_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="running"),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_runs_task", "task_runs", ["task_id"], unique=False)
    op.create_index("ix_task_runs_user", "task_runs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_task_runs_user", table_name="task_runs")
    op.drop_index("ix_task_runs_task", table_name="task_runs")
    op.drop_table("task_runs")
    op.drop_index("ix_task_definitions_user", table_name="task_definitions")
    op.drop_table("task_definitions")
