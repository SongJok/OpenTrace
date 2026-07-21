"""Add the DataSourceSchema embedding column required by the ORM.

Revision ID: 20260730_ds_schema_embedding
Revises: 20260729_skillhub_acl
"""

from __future__ import annotations

from alembic import op

revision = "20260730_ds_schema_embedding"
down_revision = "20260729_skillhub_acl"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS public.data_source_schemas "
        "ADD COLUMN IF NOT EXISTS embedding TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE IF EXISTS public.data_source_schemas " "DROP COLUMN IF EXISTS embedding"
    )
