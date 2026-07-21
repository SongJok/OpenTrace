"""Enterprise telemetry."""

from __future__ import annotations

from observability.enterprise_telemetry import get_enterprise_telemetry


class TestEnterpriseTelemetry:
    def test_record_turn_exports_three_layers(self):
        tel = get_enterprise_telemetry()
        snap = tel.record_turn(
            success=True,
            replanned=True,
            capability_types=["data_query", "web_search"],
            cost=0.5,
            goal_id="g1",
        )
        assert "cognitive" in snap
        assert "runtime" in snap
        assert "business" in snap
        assert snap["runtime"]["replan_rate"] > 0