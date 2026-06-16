"""P0 capability boost — verification replan, RAG RRF, staging learning."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_data_supervisor_verification_replan_wiring():
    text = (ROOT / "agents/data_agent_v2/supervisor.py").read_text(encoding="utf-8")
    assert "_maybe_replan_after_verification_fail" in text
    assert "ErrorClassifier" in text
    assert "verification_replan" in text


def test_rag_rrf_fusion_wiring():
    text = (ROOT / "agents/rag_agent.py").read_text(encoding="utf-8")
    assert "reciprocal_rank_fusion" in text
    assert "rag_rrf_fusion_enabled" in text


def test_rag_rrf_promotes_cross_lane_item():
    from services.rag_retrieval_fusion import reciprocal_rank_fusion

    items = [
        {"source_type": "document", "id": "d1", "text": "a", "score": 0.9},
        {"source_type": "llmwiki", "id": "w1", "text": "b", "score": 0.85},
        {"source_type": "memory", "id": "m1", "text": "c", "score": 0.4},
    ]
    merged = reciprocal_rank_fusion(items, k=60, top_n=3)
    assert len(merged) == 3
    assert all("rrf_score" in x for x in merged)


def test_staging_profile_enables_learning_auto_apply(monkeypatch):
    monkeypatch.setenv("APP_ENV", "staging")
    from infra.config.settings import Settings

    s = Settings()
    assert s.app_env == "staging"
    assert s.kernel_agent_learning_auto_apply is True


@pytest.mark.asyncio
async def test_learning_hook_strategy_stored_when_auto_apply_on(monkeypatch):
    from infra.config import settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "kernel_capability_intelligence_enabled", True)
    monkeypatch.setattr(settings_mod.settings, "kernel_agent_learning_auto_apply", True)
    from kernel.agent_runtime.learning_hook import record_agent_learning_signal

    out = await record_agent_learning_signal(
        agent_type="rag",
        task_id="t-staging",
        session_id="s1",
        passed=True,
        confidence=0.9,
        evidence_quality=0.85,
        metadata={"query_type": "fact", "query_preview": "test query"},
    )
    assert out.get("strategy_hint_stored") is True
    assert not out.get("strategy_shadow")