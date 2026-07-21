"""P1 — Claim graph, coverage, capability score, predictive world, RAG clusters."""

from __future__ import annotations

import inspect

import pytest

from agents.web_intelligence.coverage_evaluator import evaluate_coverage
from kernel.capability_intelligence.capability_score import (
    compute_capability_score,
    record_capability_outcome,
)
from kernel.cognition.predictive_world import predict_from_time_series_stub
from services.evidence_graph.claim_graph import run_claim_pipeline
from services.rag_retrieval_clusters import cluster_evidence_chunks


def test_claim_pipeline_supporting_and_conflicting():
    items = [
        {"id": "1", "content": "Revenue increase sharply in Q1.", "credibility_score": 0.8},
        {"id": "2", "content": "Revenue decrease in the same period.", "credibility_score": 0.7},
    ]
    out = run_claim_pipeline("revenue Q1", items)
    assert out["claim_graph"]["claim_count"] >= 1
    assert "supporting_claims" in out
    assert "conflicting_claims" in out


def test_rag_enrich_includes_claim_graph_when_enabled():
    from services.rag_evidence_intelligence import enrich_evidence_intelligence

    chunks = [{"id": "c1", "content": "OpenTrace is a cognitive runtime.", "source": "d1"}]
    intel = enrich_evidence_intelligence(chunks, query="cognitive runtime", source_kind="document")
    assert intel.get("evidence_clusters", {}).get("cluster_count", 0) >= 0
    assert "claim_graph" in intel or intel.get("supporting_claims") is not None


def test_coverage_evaluator_missing_dims():
    report = evaluate_coverage("北京天气怎么样", [])
    assert report.score == 0.0
    assert report.should_supplement is True


def test_capability_score_record_and_compute():
    record_capability_outcome(
        "data.query",
        success=True,
        latency_ms=120,
        evidence_quality=0.9,
        query_preview="sales",
    )
    cs = compute_capability_score("data.query")
    assert cs.capability_type == "data.query"
    assert cs.score >= 0.0


def test_predictive_stub_slope():
    up = predict_from_time_series_stub([10.0, 11.0, 12.5], metric_name="inventory")
    assert up.direction == "up"
    assert up.narrative


def test_cluster_evidence():
    chunks = [
        {"content": "a", "source": "s1"},
        {"content": "b", "source": "s1"},
    ]
    c = cluster_evidence_chunks(chunks)
    assert c["total_chunks"] == 2


def test_selector_uses_capability_score_path():
    from kernel.capability_runtime.selector import rank_capabilities_for_intent

    src = inspect.getsource(rank_capabilities_for_intent)
    assert "kernel_capability_score_ranking_enabled" in src


def test_world_decision_predictive_hook():
    from kernel.agent_runtime import world_decision_runtime as wdr

    assert "kernel_predictive_world_enabled" in inspect.getsource(wdr.enrich_world_projection_for_turn)


@pytest.mark.asyncio
async def test_web_agent_coverage_metadata(monkeypatch):
    from agents.base import TaskMessage
    from agents.web_intelligence_agent import WebIntelligenceAgent

    calls = {"n": 0}

    async def fake_by_name(self, **kw):
        calls["n"] += 1
        return '{"items":[{"title":"t","snippet":"北京 天气 晴","url":"http://x"}]}'

    monkeypatch.setattr(
        "agents.web_intelligence_agent.ToolRouter.execute_by_name",
        fake_by_name,
    )

    agent = WebIntelligenceAgent()
    task = TaskMessage(task_id="t1", agent_type="web_intelligence", query="北京天气")
    result = await agent.execute(task)
    assert result.status == "success"
    assert "web_coverage" in result.metadata