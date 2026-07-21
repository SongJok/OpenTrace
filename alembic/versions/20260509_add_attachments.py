"""add attachments table

Revision ID: 20260509_add_attachments
Revises: 20260508_add_conversation_state
Create Date: 2026-05-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260509_add_attachments"
down_revision = "20260508_add_conversation_state"
branch_labels = None
depends_on = None


def _public_tables(inspector: sa.Inspector) -> set[str]:
    try:
        return set(inspector.get_table_names(schema="public"))
    except Exception:
        return set()


def _index_exists(inspector: sa.Inspector, table: str, index_name: str) -> bool:
    try:
        return any(
            ix.get("name") == index_name
            for ix in inspector.get_indexes(table, schema="public")
        )
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _public_tables(inspector)

    if "attachments" not in tables:
        op.create_table(
            "attachments",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("session_id", sa.String(length=36), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("filename", sa.String(length=512), nullable=False),
            sa.Column("file_size", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("mime_type", sa.String(length=255), nullable=True),
            sa.Column("file_extension", sa.String(length=20), nullable=True),
            sa.Column("content_hash", sa.String(length=128), nullable=True),
            sa.Column("content_text", sa.Text(), nullable=True),
            sa.Column("content_summary", sa.String(length=512), nullable=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="'active'"),
            sa.Column("image_base64", sa.Text(), nullable=True),
            sa.Column("image_mime", sa.String(length=100), nullable=True),
            sa.Column("message_id", sa.String(length=36), nullable=True),
            sa.Column("duplicate_of", sa.String(length=36), nullable=True),
            sa.Column("state_version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["session_id"], ["public.chat_sessions.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(
                ["user_id"], ["public.users.id"], ondelete="CASCADE"
            ),
            schema="public",
        )

    inspector = sa.inspect(bind)

    if not _index_exists(inspector, "attachments", "ix_attachments_session_id"):
        op.create_index(
            "ix_attachments_session_id",
            "attachments",
            ["session_id"],
            schema="public",
        )

    if not _index_exists(inspector, "attachments", "ix_attachments_user_id"):
        op.create_index(
            "ix_attachments_user_id",
            "attachments",
            ["user_id"],
            schema="public",
        )

    if not _index_exists(inspector, "attachments", "ix_attachments_content_hash"):
        op.create_index(
            "ix_attachments_content_hash",
            "attachments",
            ["content_hash"],
            schema="public",
        )

    if not _index_exists(inspector, "attachments", "ix_attachments_session_created"):
        op.create_index(
            "ix_attachments_session_created",
            "attachments",
            ["session_id", "created_at"],
            schema="public",
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = _public_tables(inspector)
    if "attachments" in tables:
        op.drop_table("attachments", schema="public")
