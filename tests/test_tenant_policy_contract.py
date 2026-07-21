"""Tenant policy manager."""

from __future__ import annotations

from tenant.policy_manager import PolicyManager, TenantPolicy
from tenant.tenant_context import resolve_tenant_context


def test_policy_applied_to_metadata():
    ctx = resolve_tenant_context(tenant_id="t-pol", metadata={"data_residency": "eu"})
    pol = TenantPolicy(tenant_id="t-pol", compliance_frameworks=["gdpr", "soc2"])
    pm = PolicyManager()
    pm.set_policy(pol)
    md = pm.apply_to_metadata(ctx, {})
    assert md["data_residency"] == "eu"
    assert "gdpr" in md["compliance_frameworks"]
    assert md.get("tenant_policy")