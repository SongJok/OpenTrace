"""add user registration fields: status, role, approved_at, approved_by

Revision ID: 20260513_add_user_registration
Revises: 20260512_add_state_extension, 20260509_add_attachment_state
Create Date: 2026-05-13
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260513_add_user_registration"
down_revision = ("20260512_add_state_extension", "20260509_add_attachment_state")
branch_labels = None
depends_on = None


def _column_exists(inspector: sa.Inspector, table: str, column: str) -> bool:
    try:
        return any(c["name"] == column for c in inspector.get_columns(table, schema="public"))
    except Exception:
        return False


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    if not _column_exists(inspector, "users", "status"):
        op.add_column(
            "users",
            sa.Column("status", sa.String(20), nullable=False, server_default="active"),
            schema="public",
        )

    if not _column_exists(inspector, "users", "role"):
        op.add_column(
            "users",
            sa.Column("role", sa.String(20), nullable=False, server_default="user"),
            schema="public",
        )

    if not _column_exists(inspector, "users", "approved_at"):
        op.add_column(
            "users",
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            schema="public",
        )

    if not _column_exists(inspector, "users", "approved_by"):
        op.add_column(
            "users",
            sa.Column("approved_by", sa.String(36), nullable=True),
            schema="public",
        )

    # Make hashed_password nullable for pending users
    op.execute(
        sa.text(
            "ALTER TABLE public.users ALTER COLUMN hashed_password DROP NOT NULL"
        )
    )

    # Set role='admin' for existing superusers
    op.execute(
        sa.text("UPDATE public.users SET role = 'admin' WHERE is_superuser = TRUE")
    )

    # Set status='disabled' for existing inactive users (edge case)
    op.execute(
        sa.text("UPDATE public.users SET status = 'disabled' WHERE is_active = FALSE")
    )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())

    # Set non-null passwords back for any NULL rows (shouldn't exist on rollback)
    op.execute(
        sa.text(
            "UPDATE public.users SET hashed_password = '' "
            "WHERE hashed_password IS NULL"
        )
    )
    op.execute(
        sa.text(
            "ALTER TABLE public.users ALTER COLUMN hashed_password SET NOT NULL"
        )
    )

    if _column_exists(inspector, "users", "approved_by"):
        op.drop_column("users", "approved_by", schema="public")

    if _column_exists(inspector, "users", "approved_at"):
        op.drop_column("users", "approved_at", schema="public")

    if _column_exists(inspector, "users", "role"):
        op.drop_column("users", "role", schema="public")

    if _column_exists(inspector, "users", "status"):
        op.drop_column("users", "status", schema="public")
