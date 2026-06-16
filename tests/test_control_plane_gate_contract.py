"""Pre-dispatch control plane gate."""

from __future__ import annotations

from types import SimpleNamespace

from kernel.cognitive_supervisor.control_plane_gate import evaluate_request_control_plane


class TestControlPlaneGate:
    def test_allowed_without_headers(self):
        req = SimpleNamespace(
            session_id="s1",
            user_id="u1",
            metadata={"tenant_id": "default"},
        )
        out = evaluate_request_control_plane(req)
        assert out.get("allowed") is True

    def test_denied_when_quota_zero(self):
        from control_plane.control_plane import get_enterprise_control_plane
        from tenant.tenant_context import resolve_tenant_context

        cp = get_enterprise_control_plane()
        ctx = resolve_tenant_context(tenant_id="gate-t", org_id="o", workspace_id="w")
        cp.set_quota_limits(ctx, daily_turns=0, daily_cost=0.0)
        req = SimpleNamespace(
            session_id="s2",
            user_id="u2",
            metadata={"tenant_id": "gate-t", "org_id": "o", "workspace_id": "w"},
        )
        out = evaluate_request_control_plane(req)
        assert out.get("allowed") is False