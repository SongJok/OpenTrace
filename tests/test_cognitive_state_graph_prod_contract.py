"""CognitiveStateGraph — bus write path, metadata, optional Redis roundtrip."""

from __future__ import annotations

from types import SimpleNamespace

from agents.base import AgentResult
from kernel.agent_runtime.runtime_contribution import runtime_contribution_from_agent_result
from kernel.runtime.cognitive_state.bus import apply_runtime_contribution_to_bus
from kernel.runtime.cognitive_state.cognitive_state_graph import (
    CognitiveStateGraph,
    CognitiveStateNode,
    graph_from_context,
)


def test_apply_contribution_builds_graph_on_context():
    ctx = SimpleNamespace(
        session_id="s1",
        request_id="r1",
        metadata={"goal_graph": {"root_goal_id": "g-root"}},
    )
    rc = runtime_contribution_from_agent_result(
        AgentResult(
            task_id="t1",
            agent_type="rag",
            status="success",
            content="answer",
            confidence=0.9,
        ),
        capability_type="document_retrieval",
    )
    apply_runtime_contribution_to_bus(ctx, rc)
    md = ctx.metadata
    assert "cognitive_state_graph" in md
    g = CognitiveStateGraph.from_metadata(md)
    assert g is not None
    assert g.root_goal_id == "g-root"
    assert any(n.kind == "goal" for n in g.nodes.values())


def test_graph_from_context_reuses_existing():
    existing = CognitiveStateGraph(session_id="s", request_id="r", root_goal_id="g1")
    ctx = SimpleNamespace(session_id="s", request_id="r", metadata=existing.to_metadata_dict())
    g = graph_from_context(ctx)
    assert g.root_goal_id == "g1"


async def test_graph_redis_roundtrip_when_enabled(monkeypatch):
    from kernel.runtime.cognitive_state.persistence import (
        flush_cognitive_state_graph,
        load_cognitive_state_graph,
    )

    store: dict[str, str] = {}

    class _FakeRedis:
        async def setex(self, key, ttl, val):
            store[key] = val

        async def get(self, key):
            return store.get(key)

    from infra.config import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "kernel_cognitive_state_graph_persist_enabled", True)
    monkeypatch.setattr(settings_mod.settings, "kernel_cognitive_state_graph_ttl_seconds", 60)
    monkeypatch.setattr(settings_mod.settings, "kernel_cognitive_state_persist_enabled", False)

    async def _fake_redis():
        return _FakeRedis()

    monkeypatch.setattr(
        "infra.cache.redis_client.get_memory_redis",
        _fake_redis,
    )

    graph = CognitiveStateGraph(session_id="sess", request_id="req", root_goal_id="g")
    graph.add_node(
        CognitiveStateNode(node_id="goal:g", kind="goal", ref_id="g"),
    )
    await flush_cognitive_state_graph(graph)
    blob = await load_cognitive_state_graph("sess", "req")
    assert blob is not None
    assert blob.get("root_goal_id") == "g"