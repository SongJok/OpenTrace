"""enterprise report task and artifact fields

Revision ID: r0014_enterprise_reports
Revises: r0013_calendar_memory_lifecycle
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0014_enterprise_reports"
down_revision = "r0013_calendar_memory_lifecycle"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "task_definitions",
        sa.Column("task_type", sa.String(length=32), nullable=False, server_default="agent_task"),
    )
    op.add_column(
        "task_definitions",
        sa.Column("task_config", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.create_index("ix_task_definitions_task_type", "task_definitions", ["task_type"])
    op.add_column(
        "task_runs",
        sa.Column("output_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )


def downgrade() -> None:
    op.drop_column("task_runs", "output_metadata")
    op.drop_index("ix_task_definitions_task_type", table_name="task_definitions")
    op.drop_column("task_definitions", "task_config")
    op.drop_column("task_definitions", "task_type")
