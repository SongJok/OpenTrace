"""Merge heads: cognitive_events branch + enterprise tenant/RLS branch."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260610_merge_heads"
down_revision = ("20260514_cognitive_events", "20260606_enterprise_tenants_rls")
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    insp.get_table_names()
    if "tenants" in insp.get_table_names():
        try:
            insp.get_columns("tenants")
        except Exception:
            pass


def downgrade() -> None:
    pass