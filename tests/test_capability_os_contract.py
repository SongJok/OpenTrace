"""Capability OS — SLA, lifecycle, marketplace."""

from __future__ import annotations

from kernel.capability_runtime.capability_os import get_capability_os
from kernel.capability_runtime.lifecycle import CapabilityLifecycleState


class TestCapabilityOS:
    def test_marketplace_lists_products(self):
        os = get_capability_os()
        items = os.list_marketplace()
        assert len(items) >= 3
        assert items[0]["sla"]["success_rate"] >= 0

    def test_sla_degrades_to_degraded_lifecycle(self):
        os = get_capability_os()
        cap = "web_search"
        for _ in range(20):
            os.record_invocation(cap, success=False, latency_ms=5000, cost=1.0)
        st = os.get_product_state(cap)
        assert st is not None
        assert st.lifecycle in (
            CapabilityLifecycleState.DEGRADED.value,
            CapabilityLifecycleState.DEPRECATED.value,
        )

    def test_retired_capability_blocked_by_control_plane(self):
        from control_plane.control_plane import get_enterprise_control_plane
        from kernel.capability_runtime.capability_os import get_capability_os

        os = get_capability_os()
        os.set_lifecycle("web_search", CapabilityLifecycleState.RETIRED)
        d = get_enterprise_control_plane().evaluate_turn(capability_type="web_search")
        assert d.allowed is False