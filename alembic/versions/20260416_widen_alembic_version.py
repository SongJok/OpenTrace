"""Widen Alembic's version column before revisions exceed 32 characters.

Revision ID: 20260416_version_num_128
Revises: 20260411_documents_guard
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260416_version_num_128"
down_revision = "20260411_documents_guard"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite does not enforce VARCHAR lengths and cannot alter the column with
    # this syntax. PostgreSQL and the other supported server databases can.
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=32),
        type_=sa.String(length=128),
        existing_nullable=False,
    )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        return
    op.alter_column(
        "alembic_version",
        "version_num",
        existing_type=sa.String(length=128),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
