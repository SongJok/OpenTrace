"""ensure data source tables exist in public schema

Revision ID: 20260412_data_sources_guard
Revises: 20260411_documents_guard
Create Date: 2026-04-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260412_data_sources_guard"
down_revision = "20260417_document_chunks_pgvector"
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

    if "data_sources" not in tables:
        op.create_table(
            "data_sources",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("name", sa.String(length=100), nullable=False),
            sa.Column("source_type", sa.String(length=32), nullable=False),
            sa.Column("host", sa.String(length=255), nullable=False),
            sa.Column("port", sa.Integer(), nullable=False),
            sa.Column("database", sa.String(length=255), nullable=False),
            sa.Column("username", sa.String(length=255), nullable=False),
            sa.Column("password_encrypted", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["public.users.id"], ondelete="CASCADE"),
            schema="public",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "data_sources", "ix_data_sources_user_id"):
        op.create_index("ix_data_sources_user_id", "data_sources", ["user_id"], unique=False, schema="public")

    tables = _public_tables(sa.inspect(bind))
    if "data_source_schemas" not in tables:
        op.create_table(
            "data_source_schemas",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("data_source_id", sa.String(length=36), nullable=False),
            sa.Column("schema_json", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["data_source_id"], ["public.data_sources.id"], ondelete="CASCADE"),
            schema="public",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "data_source_schemas", "ix_data_source_schemas_data_source_id"):
        op.create_index(
            "ix_data_source_schemas_data_source_id",
            "data_source_schemas",
            ["data_source_id"],
            unique=False,
            schema="public",
        )

    tables = _public_tables(sa.inspect(bind))
    if "data_query_logs" not in tables:
        op.create_table(
            "data_query_logs",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("data_source_id", sa.String(length=36), nullable=False),
            sa.Column("query_text", sa.Text(), nullable=False),
            sa.Column("generated_sql", sa.Text(), nullable=True),
            sa.Column("execution_time", sa.Integer(), nullable=True),
            sa.Column("row_count", sa.Integer(), nullable=True),
            sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["user_id"], ["public.users.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["data_source_id"], ["public.data_sources.id"], ondelete="CASCADE"),
            schema="public",
        )

    inspector = sa.inspect(bind)
    if not _index_exists(inspector, "data_query_logs", "ix_data_query_logs_user_id"):
        op.create_index("ix_data_query_logs_user_id", "data_query_logs", ["user_id"], unique=False, schema="public")
    if not _index_exists(inspector, "data_query_logs", "ix_data_query_logs_data_source_id"):
        op.create_index(
            "ix_data_query_logs_data_source_id",
            "data_query_logs",
            ["data_source_id"],
            unique=False,
            schema="public",
        )


def downgrade() -> None:
    pass
