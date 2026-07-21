"""Multi-tenant six-layer isolation."""

from __future__ import annotations

from tenant.tenant_context import resolve_tenant_context
from tenant.tenant_manager import TenantManager, TenantRecord
from tenant.workspace_manager import WorkspaceManager, WorkspaceRecord


class TestTenantContext:
    def test_isolation_key(self):
        ctx = resolve_tenant_context(tenant_id="t1", org_id="o1", workspace_id="ws1")
        assert ctx.isolation_key() == "t1:o1:ws1"

    def test_metadata_merge(self):
        ctx = resolve_tenant_context(metadata={"tenant_id": "acme", "data_residency": "eu"})
        assert ctx.tenant_id == "acme"
        assert ctx.data_residency == "eu"


class TestTenantWorkspaceManagers:
    def test_register_tenant_and_workspace(self):
        tm = TenantManager()
        tm.register(TenantRecord(tenant_id="t2", tier="enterprise"))
        assert tm.get("t2").tier == "enterprise"
        wm = WorkspaceManager()
        wm.register(WorkspaceRecord(workspace_id="w1", tenant_id="t2", org_id="o2"))
        assert wm.get("t2", "w1").org_id == "o2"