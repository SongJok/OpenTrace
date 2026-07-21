"""DataAgent V2 cognitive_events — audit trail for supervisor pipeline steps.

Revision ID: 20260514_cognitive_events
Revises: 20260513_data_agent_v2_knowledge_tables
Create Date: 2026-05-14
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "20260514_cognitive_events"
down_revision = "20260513_data_agent_v2_knowledge_tables"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table: str) -> bool:
    try:
        return inspector.has_table(table, schema="public")
    except Exception:
        return False


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _table_exists(inspector, "cognitive_events"):
        return

    op.create_table(
        "cognitive_events",
        sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("trace_id", sa.String(64), nullable=False),
        sa.Column("query_id", sa.String(64), nullable=True),
        sa.Column("step", sa.String(64), nullable=False),
        sa.Column("node_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="start"),
        sa.Column("payload", JSONB, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("idx_cognitive_events_trace", "cognitive_events", ["trace_id", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_cognitive_events_trace", table_name="cognitive_events")
    op.drop_table("cognitive_events")
