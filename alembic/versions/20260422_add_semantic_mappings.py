"""add semantic_mappings column to data_source_schemas

Revision ID: 20260422_add_semantic_mappings
Revises: 20260422_add_document_llmwiki
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_add_semantic_mappings"
down_revision = "20260422_add_document_llmwiki"
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table: str, column: str) -> bool:
    try:
        return any(col.get("name") == column for col in inspector.get_columns(table, schema="public"))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _column_exists(inspector, "data_source_schemas", "semantic_mappings"):
        return

    op.add_column(
        "data_source_schemas",
        sa.Column("semantic_mappings", sa.dialects.postgresql.JSONB, nullable=False, server_default="{}"),
        schema="public",
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _column_exists(inspector, "data_source_schemas", "semantic_mappings"):
        return

    op.drop_column("data_source_schemas", "semantic_mappings", schema="public")
