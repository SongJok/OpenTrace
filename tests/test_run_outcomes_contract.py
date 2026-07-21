"""KernelResponse metadata must surface cognitive runtime turn bundles."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from kernel.cognitive_supervisor.run_outcomes import executive_result_to_kernel_response


def _minimal_result():
    fusion = SimpleNamespace(confidence=0.8, merged_context="answer text")
    critic = SimpleNamespace(passed=True, hallucination_risk=0.1, factuality=0.85)
    return SimpleNamespace(
        answer="answer text",
        policy_denied=False,
        evidence_objects=[],
        fusion_result=fusion,
        critic_result=critic,
        plan=None,
        rewrite_trace="",
        understanding=None,
        risk_level="low",
        metadata={},
    )


def test_executive_response_includes_goal_progress_from_ctx():
    request = SimpleNamespace(
        session_id="sess-1",
        metadata={
            "request_id": "req-1",
            "goal_graph": {
                "root_goal_id": "g-root",
                "goals": [
                    {
                        "goal_id": "g-root",
                        "description": "test",
                        "priority": 0,
                        "parent_id": None,
                        "success_criteria": "",
                        "metadata": {"lifecycle_state": "executing"},
                    }
                ],
            },
        },
    )
    ctx = MagicMock()
    ctx.metadata = {
        "goal_progress": {"root_goal_id": "g-root", "lifecycle_state": "completed"},
        "runtime_contribution_turn": {"version": "runtime_contribution_v1", "evidence": []},
        "cognitive_state_graph": {"version": "cognitive_state_graph_v1", "nodes": {}},
        "failure_memory": {"failure_memory_records": 0},
        "world_projection": {"current": {"kind": "current", "variables": {}}},
    }

    resp = executive_result_to_kernel_response(
        _minimal_result(), request, total_ms=42, ctx=ctx
    )
    md = resp.metadata or {}
    assert md.get("goal_progress", {}).get("lifecycle_state") == "completed"
    assert md.get("runtime_contribution_turn", {}).get("version") == "runtime_contribution_v1"
    assert "cognitive_state_graph" in md
    assert md.get("goal_graph", {}).get("root_goal_id") == "g-root"