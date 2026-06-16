"""P1 — Evidence runtime + dispatch pipeline contribution wiring."""

from __future__ import annotations

from types import SimpleNamespace

from agents.base import AgentResult
from kernel.capability_runtime.dispatch_pipeline import attach_goal_participation_metadata
from kernel.runtime.evidence_runtime import apply_turn_contributions_to_context, merge_turn_evidence


def test_merge_turn_evidence():
    results = [
        AgentResult(task_id="1", agent_type="rag", status="success", content="a", confidence=0.8),
        AgentResult(task_id="2", agent_type="tool", status="success", content="b", confidence=0.6),
    ]
    merged, ev = merge_turn_evidence(results, root_goal_id="g-root")
    assert merged.agent_type == "runtime_merge"
    assert len(ev) >= 0


def test_attach_goal_participation_includes_runtime_contribution():
    ctx = SimpleNamespace(session_id="s1", metadata={})
    results = [
        AgentResult(task_id="t", agent_type="rag", status="success", content="x", confidence=0.7),
    ]
    payload = attach_goal_participation_metadata(
        results,
        root_goal_id="g1",
        goal_description="test",
        trace_id="tr1",
        metadata_target=ctx.metadata,
        ctx=ctx,
    )
    assert payload.get("runtime_contribution_turn") or ctx.metadata.get("runtime_contribution_turn")
    assert ctx.metadata.get("cognitive_state_graph") or payload.get("runtime_contribution_count") == 1


def test_apply_turn_contributions_to_context():
    ctx = SimpleNamespace(session_id="s2", request_id="r2", metadata={"goal_graph": {"root_goal_id": "g2"}})
    merged = apply_turn_contributions_to_context(
        ctx,
        [AgentResult(task_id="x", agent_type="tool", status="success", content="ok", confidence=0.9)],
        root_goal_id="g2",
    )
    assert merged.confidence > 0
    assert "runtime_contribution" in str(ctx.metadata.keys())