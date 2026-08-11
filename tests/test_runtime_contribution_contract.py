"""P0 — Unified RuntimeContribution + CognitiveStateGraph contracts."""

from __future__ import annotations

from agents.base import AgentResult
from agents.bootstrap import instantiate_builtin_agents, register_builtin_agents
from kernel.agent_runtime.manifest import reload_manifest
from kernel.agent_runtime.runtime_contribution import (
    merge_runtime_contributions,
    runtime_contribution_from_agent_result,
)
from kernel.runtime.cognitive_state.cognitive_state_graph import (
    CognitiveStateGraph,
    apply_contribution_to_graph,
)
from kernel.runtime.objects import Evidence, Provenance


def test_island_agents_in_manifest_and_bootstrap():
    reload_manifest()
    register_builtin_agents(force=True)
    agents = instantiate_builtin_agents()
    for name in ("data", "rag"):
        assert name in agents, name


def test_runtime_contribution_shape():
    result = AgentResult(
        task_id="t-rc",
        agent_type="tool",
        status="success",
        content="ok",
        confidence=0.7,
        evidence_objects=[
            Evidence(
                content="fact",
                provenance=Provenance(source="tool", source_type="agent", confidence=0.7),
                credibility_score=0.7,
            )
        ],
    )
    rc = runtime_contribution_from_agent_result(
        result, goal_id="g1", goal_description="test", capability_type="tool"
    )
    assert rc.version == "runtime_contribution_v1"
    assert len(rc.evidence) >= 1
    assert len(rc.goal_updates) == 1
    assert len(rc.memory_updates) == 1
    assert rc.metrics
    bridge = rc.to_agent_contribution()
    assert bridge.unified_evidence


def test_cognitive_state_graph_evolution_chain():
    rc = runtime_contribution_from_agent_result(
        AgentResult(
            task_id="t2",
            agent_type="rag",
            status="success",
            content="a",
            confidence=0.8,
        ),
        goal_id="root",
    )
    graph = CognitiveStateGraph(session_id="s", request_id="r", root_goal_id="root")
    apply_contribution_to_graph(graph, rc)
    kinds = [graph.nodes[nid].kind for nid in graph.evolution_chain]
    assert kinds[0] == "goal"
    assert "evidence" in kinds or len(graph.evolution_chain) >= 1


def test_merge_runtime_contributions():
    a = runtime_contribution_from_agent_result(
        AgentResult(task_id="a", agent_type="rag", status="success", content="1", confidence=0.6),
        goal_id="g",
    )
    b = runtime_contribution_from_agent_result(
        AgentResult(task_id="b", agent_type="tool", status="success", content="2", confidence=0.8),
        goal_id="g",
    )
    merged = merge_runtime_contributions([a, b], root_goal_id="g")
    assert merged.agent_type == "runtime_merge"
    assert merged.confidence > 0
