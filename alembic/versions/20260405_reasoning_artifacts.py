"""Persist reasoning artifacts on trace logs

Revision ID: 20260405_reasoning_artifacts
Revises: 
Create Date: 2026-04-05
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260405_reasoning_artifacts"
down_revision = "20260401_redis_shadow"
branch_labels = None
depends_on = None


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {c.get("name") for c in inspector.get_columns(table)}
    except Exception:
        return set()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = _column_names(inspector, "trace_logs")

    if "reasoning_steps_json" not in cols:
        op.add_column("trace_logs", sa.Column("reasoning_steps_json", sa.Text(), nullable=True))
    if "execution_graph_json" not in cols:
        op.add_column("trace_logs", sa.Column("execution_graph_json", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = _column_names(inspector, "trace_logs")

    if "execution_graph_json" in cols:
        op.drop_column("trace_logs", "execution_graph_json")
    if "reasoning_steps_json" in cols:
        op.drop_column("trace_logs", "reasoning_steps_json")
