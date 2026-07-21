"""Add the user memory score required by the ORM.

Revision ID: 20260726_user_memory_score
Revises: 20260725_vector_columns
"""

from __future__ import annotations

from alembic import op

revision = "20260726_user_memory_score"
down_revision = "20260725_vector_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE public.user_memories "
        "ADD COLUMN IF NOT EXISTS score DOUBLE PRECISION NOT NULL DEFAULT 0.5"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.user_memories DROP COLUMN IF EXISTS score"
    )
