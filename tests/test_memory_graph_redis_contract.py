"""Memory graph Redis shadow contract (phase 3, optional)."""

from __future__ import annotations

import pytest


class TestMemoryGraphRedis:
    def test_in_process_graph_roundtrip(self):
        from memory.fabric.memory_graph import get_memory_graph

        g = get_memory_graph("s-redis-test")
        g.upsert_node("m1", "memory", {"query_preview": "hello"})
        g.upsert_node("g1", "goal", {})
        g.link("m1", "g1", relation="bound_to_goal", weight=0.8)
        d = g.to_dict()
        assert len(d["nodes"]) >= 2
        assert any(e["source"] == "m1" for e in d["edges"])

    @pytest.mark.asyncio
    async def test_persist_noop_when_disabled(self):
        from memory.fabric.memory_graph_redis import persist_graph_snapshot

        await persist_graph_snapshot("s1", {"nodes": [], "edges": []})