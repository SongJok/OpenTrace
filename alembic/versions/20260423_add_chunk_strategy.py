"""add chunk_strategy column to documents

Revision ID: 20260423_add_chunk_strategy
Revises: 20260422_add_semantic_mappings
Create Date: 2026-04-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260423_add_chunk_strategy"
down_revision = "20260422_add_semantic_mappings"
branch_labels = None
depends_on = None


def _table_exists(inspector: sa.Inspector, name: str) -> bool:
    try:
        return name in set(inspector.get_table_names(schema="public"))
    except Exception:
        return False


def _column_exists(inspector: sa.Inspector, table: str, column: str) -> bool:
    try:
        return any(col.get("name") == column for col in inspector.get_columns(table, schema="public"))
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "documents"):
        return

    if not _column_exists(inspector, "documents", "chunk_strategy"):
        op.add_column(
            "documents",
            sa.Column("chunk_strategy", sa.Integer(), nullable=False, server_default="1"),
            schema="public",
        )
        op.alter_column("documents", "chunk_strategy", server_default=None, schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "documents"):
        return

    if _column_exists(inspector, "documents", "chunk_strategy"):
        op.drop_column("documents", "chunk_strategy", schema="public")
