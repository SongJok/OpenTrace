"""Capability Control Plane descriptors."""

from __future__ import annotations

from kernel.capability_runtime.capability_control_plane import (
    get_capability_descriptor,
    list_capability_descriptors,
    rank_capabilities_for_intent,
)
from kernel.protocol.runtime_contract import CapabilityRef


class TestCapabilityRankingUnified:
    def test_selector_delegates_to_control_plane(self):
        from kernel.capability_runtime.selector import rank_capabilities_for_intent

        ranked = rank_capabilities_for_intent(
            ["data_query", "web_search"],
            intent_category="data_query",
        )
        assert ranked
        assert "score" in ranked[0]
        assert ranked[0]["capability_type"] == "data_query"


class TestCapabilityControlPlane:
    def test_data_query_owned_by_data_intelligence(self):
        d = get_capability_descriptor("data_query")
        assert d is not None
        assert d.owner_runtime == "data_intelligence"
        assert d.risk_tier == "medium"

    def test_enrich_ref_attaches_control_plane(self):
        from kernel.capability_runtime.capability_control_plane import enrich_ref_with_descriptor

        ref = enrich_ref_with_descriptor(CapabilityRef(capability_type="web_search"))
        assert "_control_plane" in (ref.params or {})

    def test_rank_respects_allowlist(self):
        ranked = rank_capabilities_for_intent(
            ["web_search", "data_query"],
            allowed=["data_query"],
        )
        types = [r["capability_type"] for r in ranked]
        assert types == ["data_query"]

    def test_list_descriptors_non_empty(self):
        assert len(list_capability_descriptors()) >= 3