"""add document llmwiki table

Revision ID: 20260422_add_document_llmwiki
Revises: 20260412_data_sources_guard
Create Date: 2026-04-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260422_add_document_llmwiki"
down_revision = "20260412_data_sources_guard"
branch_labels = None
depends_on = None


def _public_tables(inspector: sa.Inspector) -> set[str]:
    try:
        return set(inspector.get_table_names(schema="public"))
    except Exception:
        return set()


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    try:
        return any(ix.get("name") == index_name for ix in inspector.get_indexes(table, schema="public"))
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
    tables = _public_tables(inspector)

    if "document_llmwiki" not in tables:
        op.create_table(
            "document_llmwiki",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("chunk_id", sa.String(length=36), nullable=True),
            sa.Column("question", sa.Text(), nullable=False),
            sa.Column("answer", sa.Text(), nullable=False),
            sa.Column("keywords", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
            sa.Column("embedding_json", sa.Text(), nullable=True),
            sa.Column("embedding_dims", sa.Integer(), nullable=False, server_default="1024"),
            sa.Column("embedding_vector", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["document_id"], ["public.documents.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["chunk_id"], ["public.document_chunks.id"], ondelete="CASCADE"),
            schema="public",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "document_llmwiki", "ix_document_llmwiki_document_id"):
        op.create_index(
            "ix_document_llmwiki_document_id",
            "document_llmwiki",
            ["document_id"],
            unique=False,
            schema="public",
        )
    if not _index_exists(inspector, "document_llmwiki", "ix_document_llmwiki_chunk_id"):
        op.create_index(
            "ix_document_llmwiki_chunk_id",
            "document_llmwiki",
            ["chunk_id"],
            unique=False,
            schema="public",
        )

    if _column_exists(inspector, "document_llmwiki", "keywords"):
        op.alter_column("document_llmwiki", "keywords", server_default=None, schema="public")
    if _column_exists(inspector, "document_llmwiki", "embedding_dims"):
        op.alter_column("document_llmwiki", "embedding_dims", server_default=None, schema="public")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "document_llmwiki" not in _public_tables(inspector):
        return

    if _index_exists(inspector, "document_llmwiki", "ix_document_llmwiki_chunk_id"):
        op.drop_index("ix_document_llmwiki_chunk_id", table_name="document_llmwiki", schema="public")
    if _index_exists(inspector, "document_llmwiki", "ix_document_llmwiki_document_id"):
        op.drop_index("ix_document_llmwiki_document_id", table_name="document_llmwiki", schema="public")
    op.drop_table("document_llmwiki", schema="public")
