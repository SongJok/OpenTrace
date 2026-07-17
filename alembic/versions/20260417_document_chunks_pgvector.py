"""add pgvector embedding column to document_chunks

Revision ID: 20260417_document_chunks_pgvector
Revises: 20260411_documents_guard
Create Date: 2026-04-17
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260417_document_chunks_pgvector"
down_revision = "20260411_documents_guard"
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
    if not _table_exists(inspector, "document_chunks"):
        return

    try:
        op.execute(sa.text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception:
        pass

    if not _column_exists(inspector, "document_chunks", "embedding_vector"):
        op.add_column(
            "document_chunks",
            sa.Column("embedding_vector", sa.Text(), nullable=True),
            schema="public",
        )

    if not _column_exists(inspector, "document_chunks", "embedding_dims"):
        op.add_column(
            "document_chunks",
            sa.Column("embedding_dims", sa.Integer(), nullable=False, server_default="384"),
            schema="public",
        )
        op.execute(sa.text("UPDATE public.document_chunks SET embedding_dims = 384 WHERE embedding_dims IS NULL"))
        op.alter_column("document_chunks", "embedding_dims", server_default=None, schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not _table_exists(inspector, "document_chunks"):
        return

    if _column_exists(inspector, "document_chunks", "embedding_vector"):
        op.drop_column("document_chunks", "embedding_vector", schema="public")

    if _column_exists(inspector, "document_chunks", "embedding_dims"):
        op.drop_column("document_chunks", "embedding_dims", schema="public")
