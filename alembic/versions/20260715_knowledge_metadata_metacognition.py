"""Add metadata rules, metacognition observations and merge governance."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260715_knowledge_metadata_metacognition"
down_revision = "20260714_knowledge_search_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "knowledge_rules" not in tables:
        op.create_table(
            "knowledge_rules",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("rule_key", sa.String(128), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("rule_type", sa.String(32), nullable=False, server_default="schema"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("schema_json", sa.JSON(), nullable=False),
            sa.Column("instructions", sa.Text(), nullable=True),
            sa.Column("provenance", sa.JSON(), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("tenant_id", "workspace_id", "rule_key", "version", name="uq_knowledge_rule_version"),
        )
        for column in ("owner_id", "tenant_id", "workspace_id", "rule_key", "status"):
            op.create_index(f"ix_knowledge_rules_{column}", "knowledge_rules", [column])
    if "knowledge_observations" not in tables:
        op.create_table(
            "knowledge_observations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("metric", sa.String(128), nullable=False),
            sa.Column("value", sa.Float(), nullable=False),
            sa.Column("dimensions", sa.JSON(), nullable=False),
            sa.Column("trigger", sa.String(64), nullable=False, server_default="scheduled"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        for column in ("owner_id", "tenant_id", "workspace_id", "metric", "created_at"):
            op.create_index(f"ix_knowledge_observations_{column}", "knowledge_observations", [column])
    if "knowledge_merge_cases" not in tables:
        op.create_table(
            "knowledge_merge_cases",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("tenant_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("workspace_id", sa.String(128), nullable=False, server_default="default"),
            sa.Column("entity_key", sa.String(255), nullable=False),
            sa.Column("conflict_type", sa.String(64), nullable=False, server_default="duplicate_claim"),
            sa.Column("candidate_ids", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("resolution", sa.JSON(), nullable=False),
            sa.Column("resolved_by", sa.String(36), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
        )
        for column in ("owner_id", "tenant_id", "workspace_id", "entity_key", "status"):
            op.create_index(f"ix_knowledge_merge_cases_{column}", "knowledge_merge_cases", [column])


def downgrade() -> None:
    for table in ("knowledge_merge_cases", "knowledge_observations", "knowledge_rules"):
        op.drop_table(table)
