"""Enterprise tenant RLS skeleton contracts."""

from __future__ import annotations

from tenant.tenant_rls import require_tenant_persist, TENANTS_TABLE_DDL


def test_tenants_ddl_contains_rls_ready_table():
    assert "CREATE TABLE IF NOT EXISTS tenants" in TENANTS_TABLE_DDL
    assert "tenant_id" in TENANTS_TABLE_DDL


def test_require_tenant_persist_only_prod_with_flag():
    from types import SimpleNamespace

    s = SimpleNamespace(app_env="development", enterprise_tenant_rls_enabled=True)
    assert require_tenant_persist(s) is False
    s2 = SimpleNamespace(app_env="production", enterprise_tenant_rls_enabled=True)
    assert require_tenant_persist(s2) is True