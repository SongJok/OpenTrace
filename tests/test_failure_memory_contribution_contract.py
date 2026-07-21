"""Failure memory ingestion from RuntimeContribution risks."""

from __future__ import annotations

from agents.base import AgentResult
from kernel.agent_runtime.failure_from_contribution import (
    record_risks_from_contribution,
    record_turn_failure_signals,
)
from kernel.agent_runtime.runtime_contribution import runtime_contribution_from_agent_result
from kernel.capability_intelligence.failure_memory import failure_memory


def test_record_risks_from_failed_contribution():
    failure_memory.reset()
    rc = runtime_contribution_from_agent_result(
        AgentResult(
            task_id="f1",
            agent_type="rag",
            status="error",
            content="",
            confidence=0.1,
            error="timeout",
        ),
        capability_type="document_retrieval",
    )
    n = record_risks_from_contribution(rc, query_preview="test query")
    assert n >= 1
    stats = failure_memory.get_stats("document_retrieval")
    assert stats.total_failures >= 1


def test_record_turn_failure_signals_merged():
    failure_memory.reset()
    results = [
        AgentResult(
            task_id="a",
            agent_type="tool",
            status="success",
            content="ok",
            confidence=0.2,
        ),
    ]
    out = record_turn_failure_signals(
        results,
        query_preview="low conf",
        root_goal_id="g1",
    )
    assert "failure_memory_records" in out
    assert out["failure_memory_records"] >= 1