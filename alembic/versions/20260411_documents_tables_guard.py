"""ensure documents tables exist in public schema

Revision ID: 20260411_documents_guard
Revises: 20260411_public_core_guard
Create Date: 2026-04-11
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260411_documents_guard"
down_revision = "20260411_public_core_guard"
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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _public_tables(inspector)

    if "documents" not in tables:
        op.create_table(
            "documents",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("owner_id", sa.String(length=36), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("file_type", sa.String(length=20), nullable=False, server_default="text"),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content", sa.Text(), nullable=True),
            sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("doc_metadata", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["owner_id"], ["public.users.id"], ondelete="CASCADE"),
            schema="public",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "documents", "ix_documents_owner_id"):
        op.create_index("ix_documents_owner_id", "documents", ["owner_id"], unique=False, schema="public")

    tables = _public_tables(sa.inspect(bind))
    if "document_chunks" not in tables:
        op.create_table(
            "document_chunks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("document_id", sa.String(length=36), nullable=False),
            sa.Column("chunk_index", sa.Integer(), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("embedding_json", sa.Text(), nullable=True),
            sa.Column("chunk_metadata", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["document_id"], ["public.documents.id"], ondelete="CASCADE"),
            schema="public",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "document_chunks", "ix_document_chunks_document_id"):
        op.create_index("ix_document_chunks_document_id", "document_chunks", ["document_id"], unique=False, schema="public")


def downgrade() -> None:
    pass
