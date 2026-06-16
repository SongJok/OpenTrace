"""Tier-1 runtime metadata."""

from __future__ import annotations

from kernel.runtime.runtime_tiers import get_runtime_tier, list_tier1_runtimes


class TestRuntimeTiers:
    def test_data_intelligence_is_tier1(self):
        d = get_runtime_tier("data_intelligence")
        assert d is not None
        assert d.tier == 1
        assert d.kind == "data"

    def test_all_registered_defaults_are_tier1(self):
        names = {d.name for d in list_tier1_runtimes()}
        assert "cognitive_executive" in names
        assert "data_intelligence" in names
        assert "multi_goal" in names