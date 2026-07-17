"""Normalize document embedding columns to pgvector.

Revision ID: 20260725_vector_columns
Revises: 20260724_chatgpt_runtime_completion
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260725_vector_columns"
down_revision = "20260724_chatgpt_runtime_completion"
branch_labels = None
depends_on = None

VECTOR_DIMENSIONS = 1024


def _table_names(inspector: sa.Inspector) -> set[str]:
    try:
        return set(inspector.get_table_names(schema="public"))
    except Exception:
        return set()


def _column_names(inspector: sa.Inspector, table: str) -> set[str]:
    try:
        return {column["name"] for column in inspector.get_columns(table, schema="public")}
    except Exception:
        return set()


def _column_udt(bind, table: str, column: str) -> str | None:
    return bind.execute(
        sa.text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = :table "
            "AND column_name = :column"
        ),
        {"table": table, "column": column},
    ).scalar_one_or_none()


def _normalize_vector_column(bind, table: str) -> None:
    inspector = sa.inspect(bind)
    if table not in _table_names(inspector):
        return

    if "embedding_vector" not in _column_names(inspector, table):
        op.execute(
            f"ALTER TABLE public.{table} "
            f"ADD COLUMN embedding_vector vector({VECTOR_DIMENSIONS})"
        )
        return

    if _column_udt(bind, table, "embedding_vector") == "vector":
        return

    # embedding_json remains the compatibility copy. Legacy vectors with a
    # different dimension become NULL here and can be regenerated safely.
    op.execute(
        f"ALTER TABLE public.{table} ALTER COLUMN embedding_vector "
        f"TYPE vector({VECTOR_DIMENSIONS}) USING ("
        "CASE "
        "WHEN embedding_vector IS NULL OR btrim(embedding_vector) = '' THEN NULL "
        f"WHEN vector_dims(embedding_vector::vector) = {VECTOR_DIMENSIONS} "
        f"THEN embedding_vector::vector({VECTOR_DIMENSIONS}) "
        "ELSE NULL END)"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    _normalize_vector_column(bind, "document_chunks")
    _normalize_vector_column(bind, "document_llmwiki")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw "
        "ON public.document_chunks USING hnsw (embedding_vector vector_cosine_ops)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP INDEX IF EXISTS public.ix_document_chunks_embedding_hnsw")
    for table in ("document_llmwiki", "document_chunks"):
        if _column_udt(bind, table, "embedding_vector") == "vector":
            op.execute(
                f"ALTER TABLE public.{table} ALTER COLUMN embedding_vector "
                "TYPE text USING embedding_vector::text"
            )
