"""Turn enrichment SSOT — gateway + supervisor + agent params."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_gateway_wires_turn_enrichment():
    text = (ROOT / "kernel/runtime_gateway.py").read_text(encoding="utf-8")
    assert "_ensure_turn_enrichment" in text
    assert "enrich_turn_before_dispatch" in text
    assert "turn_enrichment_applied" in text


def test_dag_invoke_merges_runtime_agent_params():
    text = (ROOT / "kernel/agent_runtime/dag_invoke.py").read_text(encoding="utf-8")
    assert "runtime_agent_params_from_context" in text


def test_rag_agent_uses_retrieval_query_helper():
    text = (ROOT / "agents/rag_agent.py").read_text(encoding="utf-8")
    assert "_retrieval_query_from_task" in text
    assert "raw_user_query" in text


@pytest.mark.asyncio
async def test_context_assembler_memory_injection_uses_current_turn_not_history():
    """Regression: RAG must not retrieve with previous turn's user text from history."""
    from kernel.context_assembler import get_context_assembler

    class _Tctx:
        query = "队长是什么"
        recent_history = [
            {"role": "user", "content": "什么是队长"},
            {"role": "assistant", "content": "队长是…"},
        ]
        memory_context = None
        attachment_contexts = []
        conversation_state = None
        metadata = {"raw_user_query": "队长是什么"}

    assembled = await get_context_assembler().assemble(_Tctx())
    assert assembled.memory_injection_query == "队长是什么"
    assert assembled.memory_injection_query != "什么是队长"


def test_data_v2_supervisor_uses_enrichment_params():
    text = (ROOT / "agents/data_agent_v2/supervisor.py").read_text(encoding="utf-8")
    assert "memory_injection_query" in text
    assert "user_preference_context_block" in text


def test_supervisor_syncs_enrichment_to_runtime_context():
    text = (ROOT / "kernel/cognitive_supervisor/supervisor.py").read_text(encoding="utf-8")
    assert "sync_enrichment_metadata_to_runtime_context" in text


def test_rag_user_memory_scoped_by_user_id():
    text = (ROOT / "agents/rag_agent.py").read_text(encoding="utf-8")
    assert "UserMemory.user_id == user_id" in text


def test_web_intelligence_uses_search_query_helper():
    text = (ROOT / "agents/web_intelligence_agent.py").read_text(encoding="utf-8")
    assert "_search_query_from_task" in text


def test_execution_projection_merges_enrichment_params():
    text = (ROOT / "kernel/runtime/cognitive/execution_projection.py").read_text(encoding="utf-8")
    assert "runtime_agent_params_from_context" in text
    assert "def to_execution_graph(self, ctx:" in text


def test_projection_planner_passes_ctx_to_graph():
    text = (ROOT / "kernel/runtime/cognitive/projection_planner.py").read_text(encoding="utf-8")
    assert "to_execution_graph(ctx)" in text


def test_data_supervisor_reads_data_source_from_params():
    text = (ROOT / "agents/data_agent_v2/supervisor.py").read_text(encoding="utf-8")
    assert "data_source_context" in text


def test_runtime_params_include_data_source_context():
    text = (ROOT / "kernel/turn_enrichment.py").read_text(encoding="utf-8")
    assert '"data_source_context"' in text


@pytest.mark.asyncio
async def test_learning_hook_strategy_shadow_when_auto_apply_off(monkeypatch):
    from infra.config import settings as settings_mod

    monkeypatch.setattr(
        settings_mod.settings,
        "kernel_capability_intelligence_enabled",
        True,
    )
    monkeypatch.setattr(
        settings_mod.settings,
        "kernel_agent_learning_auto_apply",
        False,
    )
    from kernel.agent_runtime.learning_hook import record_agent_learning_signal

    out = await record_agent_learning_signal(
        agent_type="rag",
        task_id="t1",
        session_id="s1",
        passed=True,
        confidence=0.9,
        evidence_quality=0.8,
        metadata={"query_type": "fact", "query_preview": "test"},
    )
    assert out.get("strategy_shadow") is True
    assert not out.get("strategy_hint_stored")


def test_document_retrieval_uses_enterprise_read_scope():
    text = (ROOT / "plugins/document_retrieval.py").read_text(encoding="utf-8")
    assert "accessible_document_predicate" in text
    assert "tenant_metadata" in text


def test_data_supervisor_data_source_context():
    text = (ROOT / "agents/data_agent_v2/supervisor.py").read_text(encoding="utf-8")
    assert "data_source_context" in text


def test_learning_hook_strategy_shadow_flag():
    text = (ROOT / "kernel/agent_runtime/learning_hook.py").read_text(encoding="utf-8")
    assert "kernel_agent_learning_auto_apply" in text
    assert "strategy_shadow" in text


@pytest.mark.asyncio
async def test_enrich_turn_before_dispatch_sets_flag():
    from kernel.cognitive_kernel import KernelRequest
    from kernel.turn_enrichment import enrich_turn_before_dispatch

    req = KernelRequest(
        query="hello",
        session_id="s-enrich",
        user_id="u1",
        metadata={"intent_lock": {"cognitive_budget": {"memory_injection": False}}},
    )
    out = await enrich_turn_before_dispatch(req, skip_multi_turn=True)
    assert out.query == "hello"
    assert req.metadata.get("turn_enrichment_applied") is True


@pytest.mark.asyncio
async def test_runtime_agent_params_from_context():
    from kernel.turn_enrichment import runtime_agent_params_from_context

    class _Ctx:
        session_id = "s1"
        user_id = "u1"
        query = "q"
        metadata = {
            "memory_injection_query": "expanded q",
            "multi_turn_resolution": {"resolved_query": "expanded q", "applied": True},
        }

    params = runtime_agent_params_from_context(_Ctx())
    assert params["memory_injection_query"] == "expanded q"
    assert params["multi_turn_resolution"]["applied"] is True


def test_inject_multi_turn_constraints_into_metadata():
    from kernel.multi_turn_resolution import MultiTurnResolution
    from kernel.reference_resolver import ReferenceResult
    from kernel.turn_enrichment import inject_multi_turn_constraints_into_metadata

    md: dict = {}
    mtr = MultiTurnResolution(
        original_query="按月",
        resolved_query="按月份统计销售额",
        applied=True,
        reference_result=ReferenceResult(
            turn_type="correction",
            resolved_query="按月份统计销售额",
            confidence=0.8,
            corrected_constraints={"time_grain": "month"},
            suggested_domain="data",
        ),
    )
    inject_multi_turn_constraints_into_metadata(md, mtr)
    assert md.get("multi_turn_constraints", {}).get("time_grain") == "month"


def test_data_supervisor_multi_turn_constraints_wiring():
    text = (ROOT / "agents/data_agent_v2/supervisor.py").read_text(encoding="utf-8")
    assert "multi_turn_constraints" in text


def test_turn_enrichment_exports_multi_turn_constraints_param():
    text = (ROOT / "kernel/turn_enrichment.py").read_text(encoding="utf-8")
    assert "multi_turn_constraints" in text
    assert "inject_multi_turn_constraints_into_metadata" in text


def test_rag_claim_anchor_gate_wiring():
    text = (ROOT / "agents/rag_agent.py").read_text(encoding="utf-8")
    assert "claim_verification" in text
    assert "unanchored_count" in text
