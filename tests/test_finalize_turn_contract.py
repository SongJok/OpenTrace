"""Post-turn quota + usage accounting."""

from __future__ import annotations

from types import SimpleNamespace

from kernel.runtime.finalize_turn import post_turn_enterprise_accounting


def test_post_turn_enterprise_accounting_increments_quota():
    from control_plane.control_plane import get_enterprise_control_plane
    from tenant.tenant_context import resolve_tenant_context

    cp = get_enterprise_control_plane()
    ctx = resolve_tenant_context(tenant_id="ft-tenant", org_id="o", workspace_id="w")
    key = ctx.isolation_key()
    cp._quota.set_limits(key, daily_turns=100, daily_cost=50.0)
    before = cp._quota.check_turn(ctx)
    req = SimpleNamespace(
        user_id="u1",
        session_id="s1",
        metadata={"tenant_id": "ft-tenant", "org_id": "o", "workspace_id": "w"},
    )
    post_turn_enterprise_accounting(req, None)
    after = cp._quota.check_turn(ctx)
    assert after.turns_used == before.turns_used + 1


def test_post_turn_writes_billing_attribution():
    req = SimpleNamespace(
        user_id="u1",
        session_id="s2",
        metadata={
            "tenant_id": "ft-tenant",
            "org_id": "o",
            "workspace_id": "w",
            "prompt_tokens": 2000,
            "completion_tokens": 1000,
            "capability_type": "rag",
        },
    )
    post_turn_enterprise_accounting(req, None)
    assert "billing_attribution" in (req.metadata or {})
    assert float(req.metadata.get("estimated_cost", 0)) >= 0