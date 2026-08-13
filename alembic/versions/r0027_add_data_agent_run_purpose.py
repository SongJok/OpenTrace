"""add_data_agent_run_purpose

Revision ID: r0027_add_data_agent_run_purpose
Revises: r0026_data_agent_operational_governance
Create Date: 2026-08-13 11:46:44.968356
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "r0027_add_data_agent_run_purpose"
down_revision = "r0026_data_agent_operational_governance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "data_agent_runs",
        sa.Column("run_purpose", sa.String(length=20), nullable=False, server_default="online"),
    )
    op.create_index("ix_data_agent_runs_run_purpose", "data_agent_runs", ["run_purpose"])


def downgrade() -> None:
    op.drop_index("ix_data_agent_runs_run_purpose", table_name="data_agent_runs")
    op.drop_column("data_agent_runs", "run_purpose")
