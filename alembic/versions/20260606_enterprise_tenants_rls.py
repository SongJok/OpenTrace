"""Enable RLS on tenants when enterprise_tenant_rls_enabled (idempotent DDL)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20260606_enterprise_tenants_rls"
down_revision = "20260606_enterprise_tenant"
branch_labels = None
depends_on = None


def _table_exists(insp: sa.Inspector, name: str) -> bool:
    try:
        return name in insp.get_table_names()
    except Exception:
        return False


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not _table_exists(insp, "tenants"):
        return
    try:
        insp.get_indexes("tenants")
    except Exception:
        pass
    # Postgres RLS — no-op on SQLite test binds
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenants_tenant_isolation ON tenants")
    op.execute(
        """
        CREATE POLICY tenants_tenant_isolation ON tenants
            USING (tenant_id = current_setting('app.tenant_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS tenants_tenant_isolation ON tenants")