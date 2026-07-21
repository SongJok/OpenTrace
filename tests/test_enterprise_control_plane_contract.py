"""Enterprise Control Plane facade."""

from __future__ import annotations

import pytest

from control_plane.control_plane import get_enterprise_control_plane


class TestEnterpriseControlPlane:
    def test_default_turn_allowed(self):
        cp = get_enterprise_control_plane()
        d = cp.evaluate_turn(session_id="s1", user_id="u1")
        assert d.allowed is True
        assert d.tenant.get("tenant_id") == "default"

    def test_quota_denial(self):
        cp = get_enterprise_control_plane()
        from tenant.tenant_context import resolve_tenant_context

        ctx = resolve_tenant_context(tenant_id="t-q", org_id="o", workspace_id="w")
        cp._quota.set_limits(ctx.isolation_key(), daily_turns=0, daily_cost=0.0)
        d = cp.evaluate_turn(tenant_id="t-q", org_id="o", workspace_id="w")
        assert d.allowed is False
        assert "quota_daily_turns_exceeded" in d.violations

    def test_gdpr_pii_violation(self):
        cp = get_enterprise_control_plane()
        d = cp.evaluate_turn(
            metadata={"compliance_frameworks": ["gdpr"], "data_residency": "us"},
            pii_detected=True,
        )
        assert d.allowed is False
        assert any("gdpr" in v for v in d.violations)

    def test_quota_consume_increments_in_process(self):
        cp = get_enterprise_control_plane()
        from tenant.tenant_context import resolve_tenant_context

        ctx = resolve_tenant_context(tenant_id="t-consume", org_id="o", workspace_id="w")
        key = ctx.isolation_key()
        cp._quota.set_limits(key, daily_turns=100, daily_cost=10.0)
        before = cp._quota.check_turn(ctx)
        cp.consume_turn_quota(ctx, cost=0.5)
        after = cp._quota.check_turn(ctx)
        assert after.turns_used == before.turns_used + 1
        assert after.cost_used >= before.cost_used + 0.49


def test_quota_redis_key_format():
    from tenant.quota_redis_store import cost_key, turns_key

    assert turns_key("tenant:a").startswith("opentrace:quota:turns:tenant:a:")
    assert cost_key("tenant:a").startswith("opentrace:quota:cost:tenant:a:")


@pytest.mark.asyncio
async def test_evaluate_turn_async_matches_sync():
    from control_plane.control_plane import get_enterprise_control_plane

    cp = get_enterprise_control_plane()
    sync_d = cp.evaluate_turn(session_id="async-s1", user_id="u1")
    async_d = await cp.evaluate_turn_async(session_id="async-s1", user_id="u1")
    assert sync_d.allowed == async_d.allowed
    assert sync_d.tenant.get("tenant_id") == async_d.tenant.get("tenant_id")