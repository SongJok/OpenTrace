"""Shared world state + world graph."""

from __future__ import annotations

from world.world_runtime import WorldGraph, build_shared_world_state
from kernel.cognition.runtime_grounding import RuntimeGroundingState


class _Ctx:
    session_id = "s-wm"
    request_id = "r-wm"
    metadata = {"goal_graph": {"root_goal_id": "g1", "goals": []}}
    allowed_capabilities = ["data_query"]
    user_preferences = []


class TestWorldModelRuntime:
    def test_world_graph_links_goal_to_capabilities(self):
        state = RuntimeGroundingState()
        state.goal.root_goal_id = "g1"
        state.capability.active_capabilities = ["data_query"]
        g = WorldGraph.from_grounding(state)
        d = g.to_dict()
        assert any(e["relation"] == "uses" for e in d["edges"])

    def test_build_shared_world_state_includes_tenant_model(self):
        sws = build_shared_world_state(_Ctx(), tenant_ctx=None)
        d = sws.to_dict()
        assert "tenant_model" in d
        assert "world_graph" in d