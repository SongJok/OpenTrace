"""DataAgent V2 knowledge asset tables — metric_definitions, schema_metadata,
table_relationships, analytical_skills, query_patterns, metric_lineage.

Revision ID: 20260513_data_agent_v2_knowledge_tables
Revises: 20260513_add_user_registration
Create Date: 2026-05-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB


revision = "20260513_data_agent_v2_knowledge_tables"
down_revision = "20260513_add_user_registration"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, table: str) -> bool:
    try:
        return inspector.has_table(table, schema="public")
    except Exception:
        return False


def _column_exists(inspector: sa.Inspector, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspector.get_columns(table, schema="public"))
    except Exception:
        return False


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # ── 3.1 metric_definitions ─────────────────────────────────────────
    if not _table_exists(inspector, "metric_definitions"):
        op.create_table(
            "metric_definitions",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("aliases", ARRAY(sa.Text), nullable=False, server_default="{}"),
            sa.Column("formula", sa.Text, nullable=False),
            sa.Column("underlying_columns", ARRAY(sa.Text), nullable=False, server_default="{}"),
            sa.Column("agg_function", sa.String(50), nullable=True),
            sa.Column("business_definition", sa.Text, nullable=True),
            sa.Column("unit", sa.String(50), nullable=True),
            sa.Column("category", sa.String(100), nullable=True),
            sa.Column("tags", ARRAY(sa.Text), nullable=False, server_default="{}"),
            sa.Column("sensitivity", sa.String(20), nullable=False, server_default="public"),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
            sa.Column("approved_by", sa.String(36), nullable=True),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            schema="public",
        )
        op.create_index("ix_metric_defs_ds_status", "metric_definitions", ["data_source_id", "status"], schema="public")

    # ── 3.2 schema_metadata ────────────────────────────────────────────
    if not _table_exists(inspector, "schema_metadata"):
        op.create_table(
            "schema_metadata",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("table_name", sa.String(255), nullable=False),
            sa.Column("column_name", sa.String(255), nullable=False),
            sa.Column("business_name", sa.String(255), nullable=True),
            sa.Column("business_description", sa.Text, nullable=True),
            sa.Column("semantic_type", sa.String(100), nullable=True),
            sa.Column("value_map", JSONB, nullable=True),
            sa.Column("is_primary_key", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("is_foreign_key", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("is_time_column", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("time_grain", sa.String(20), nullable=True),
            sa.Column("is_metric_column", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("is_dimension_column", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("is_sensitive", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("masking_rule", sa.String(50), nullable=True),
            sa.Column("lifecycle_stage", sa.String(50), nullable=True),
            sa.Column("nullable", sa.Boolean, nullable=False, server_default="true"),
            sa.Column("default_value", sa.Text, nullable=True),
            sa.Column("sample_values", ARRAY(sa.Text), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("data_source_id", "table_name", "column_name", name="uq_schema_meta_ds_table_col"),
            schema="public",
        )

    # ── 3.3 table_relationships ────────────────────────────────────────
    if not _table_exists(inspector, "table_relationships"):
        op.create_table(
            "table_relationships",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("data_source_id", sa.String(36), sa.ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("left_table", sa.String(255), nullable=False),
            sa.Column("left_column", sa.String(255), nullable=False),
            sa.Column("right_table", sa.String(255), nullable=False),
            sa.Column("right_column", sa.String(255), nullable=False),
            sa.Column("join_type", sa.String(20), nullable=False, server_default="LEFT"),
            sa.Column("cardinality", sa.String(10), nullable=True),
            sa.Column("amplification_risk", sa.String(10), nullable=True),
            sa.Column("is_verified", sa.Boolean, nullable=False, server_default="false"),
            sa.Column("verified_by", sa.String(36), nullable=True),
            sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("success_rate", sa.Float, nullable=False, server_default="1.0"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint("data_source_id", "left_table", "left_column", "right_table", "right_column", name="uq_table_rel_ds_lr"),
            schema="public",
        )

    # ── 3.4 analytical_skills ──────────────────────────────────────────
    if not _table_exists(inspector, "analytical_skills"):
        op.create_table(
            "analytical_skills",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("skill_type", sa.String(50), nullable=False),
            sa.Column("description", sa.Text, nullable=True),
            sa.Column("required_intent_types", ARRAY(sa.Text), nullable=False, server_default="{}"),
            sa.Column("required_metric_count", sa.Integer, nullable=False, server_default="1"),
            sa.Column("required_dimension_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("plan_template", JSONB, nullable=False, server_default="{}"),
            sa.Column("sql_template", sa.Text, nullable=True),
            sa.Column("visualization_hint", sa.String(50), nullable=True),
            sa.Column("parameters_schema", JSONB, nullable=True),
            sa.Column("examples", JSONB, nullable=True),
            sa.Column("version", sa.Integer, nullable=False, server_default="1"),
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            schema="public",
        )
        op.create_index("ix_analytical_skills_type_status", "analytical_skills", ["skill_type", "status"], schema="public")

    # ── 3.5 query_patterns ─────────────────────────────────────────────
    if not _table_exists(inspector, "query_patterns"):
        op.create_table(
            "query_patterns",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("pattern_hash", sa.String(64), nullable=False, unique=True),
            sa.Column("query_template", sa.Text, nullable=False),
            sa.Column("intent_type", sa.String(50), nullable=True),
            sa.Column("entities", ARRAY(sa.Text), nullable=True),
            sa.Column("metrics", ARRAY(sa.Text), nullable=True),
            sa.Column("successful_sql", sa.Text, nullable=True),
            sa.Column("success_count", sa.Integer, nullable=False, server_default="1"),
            sa.Column("failure_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("avg_confidence", sa.Float, nullable=True),
            sa.Column("avg_latency_ms", sa.Float, nullable=True),
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            schema="public",
        )

    # ── 3.6 metric_lineage ─────────────────────────────────────────────
    if not _table_exists(inspector, "metric_lineage"):
        op.create_table(
            "metric_lineage",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("metric_id", sa.String(36), sa.ForeignKey("metric_definitions.id", ondelete="CASCADE"), nullable=False, index=True),
            sa.Column("depends_on_metric_id", sa.String(36), sa.ForeignKey("metric_definitions.id", ondelete="SET NULL"), nullable=True),
            sa.Column("depends_on_column", sa.String(255), nullable=True),
            sa.Column("transformation", sa.Text, nullable=True),
            sa.Column("lineage_type", sa.String(20), nullable=False, server_default="derived"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
            schema="public",
        )

    # ── 3.7 Enhance existing tables ────────────────────────────────────

    # data_source_schemas
    if not _column_exists(inspector, "data_source_schemas", "auto_metadata"):
        op.add_column("data_source_schemas", sa.Column("auto_metadata", JSONB, nullable=True), schema="public")
    if not _column_exists(inspector, "data_source_schemas", "relationship_hints"):
        op.add_column("data_source_schemas", sa.Column("relationship_hints", JSONB, nullable=True), schema="public")
    if not _column_exists(inspector, "data_source_schemas", "last_analyzed_at"):
        op.add_column("data_source_schemas", sa.Column("last_analyzed_at", sa.DateTime(timezone=True), nullable=True), schema="public")

    # feedback
    if not _column_exists(inspector, "feedback", "agent_trace_id"):
        op.add_column("feedback", sa.Column("agent_trace_id", sa.String(255), nullable=True), schema="public")
    if not _column_exists(inspector, "feedback", "corrected_metric_id"):
        op.add_column("feedback", sa.Column("corrected_metric_id", sa.String(36), nullable=True), schema="public")
    if not _column_exists(inspector, "feedback", "corrected_sql"):
        op.add_column("feedback", sa.Column("corrected_sql", sa.Text, nullable=True), schema="public")
    if not _column_exists(inspector, "feedback", "learning_applied"):
        op.add_column("feedback", sa.Column("learning_applied", sa.Boolean, nullable=False, server_default="false"), schema="public")


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Remove enhanced columns from feedback
    for col in ("learning_applied", "corrected_sql", "corrected_metric_id", "agent_trace_id"):
        if _column_exists(inspector, "feedback", col):
            op.drop_column("feedback", col, schema="public")

    # Remove enhanced columns from data_source_schemas
    for col in ("last_analyzed_at", "relationship_hints", "auto_metadata"):
        if _column_exists(inspector, "data_source_schemas", col):
            op.drop_column("data_source_schemas", col, schema="public")

    # Drop new tables in reverse dependency order
    for table in ("metric_lineage", "query_patterns", "analytical_skills", "table_relationships", "schema_metadata", "metric_definitions"):
        if _table_exists(inspector, table):
            op.drop_table(table, schema="public")
