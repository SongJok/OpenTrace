import asyncio

import pytest

from agents.base import TaskMessage
from agents.rag_agent import RagAgent
from kernel.context_builder import ContextChunk
from services.rag_query_planning import (
    RAG_EVIDENCE_VERSION,
    RAG_PLAN_VERSION,
    assess_answerability,
    build_rag_query_plan,
    normalize_rag_evidence,
)


def test_build_rag_query_plan_exposes_lanes_filters_and_budget():
    plan = build_rag_query_plan(
        raw_query="/rag 什么是队长？",
        normalized_query="什么是队长？",
        rewritten_query="什么是队长",
        query_type="definition",
        hints=["prefer_llmwiki", "lower_threshold"],
        query_terms=["队长", "身份", "权限"],
        sources=["documents", "semantic_memory"],
        top_k=5,
        llmwiki_top_k=5,
        min_score=0.27,
        user_id="u1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        params={"max_search_queries": 4},
    )

    data = plan.to_dict()
    assert data["version"] == RAG_PLAN_VERSION
    assert data["filters"]["tenant_id"] == "tenant-a"
    assert data["filters"]["workspace_id"] == "workspace-a"
    assert data["filters"]["acl_scope_enforced"] is True
    assert data["budget"]["max_query_variants"] == 4
    assert data["query_variants"][0] == "队长 身份 权限 角色 申请 条件"
    lane_weights = {lane["name"]: lane["weight"] for lane in data["lanes"]}
    assert lane_weights["llmwiki"] > lane_weights["document"]


def test_normalize_rag_evidence_preserves_scope_and_protocol_version():
    plan = build_rag_query_plan(
        raw_query="退款政策",
        normalized_query="退款政策",
        rewritten_query="退款政策",
        query_type="fact",
        hints=["prefer_documents"],
        query_terms=["退款", "政策"],
        sources=["documents"],
        top_k=3,
        llmwiki_top_k=2,
        min_score=0.4,
        user_id="u1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
    )

    evidence = normalize_rag_evidence(
        {
            "source_type": "document",
            "id": "doc_1",
            "title": "退款制度",
            "text": "退款政策说明与流程",
            "score": 0.8,
            "document_id": "d1",
            "chunk_index": 2,
            "evidence_tier": "factual",
        },
        plan=plan,
        rank=1,
        citation={"id": 1, "title": "退款制度"},
    )

    assert evidence["version"] == RAG_EVIDENCE_VERSION
    assert evidence["lane"] == "document"
    assert evidence["access_scope"]["tenant_id"] == "tenant-a"
    assert evidence["citation"]["title"] == "退款制度"
    assert evidence["metadata"]["query_type"] == "fact"


def test_assess_answerability_returns_explicit_states():
    strong = assess_answerability(
        has_evidence=True,
        retrieval_strong=True,
        gated=True,
        confidence=0.7,
        anchor_score=0.5,
        max_score=0.8,
        min_score=0.35,
    )
    conflict = assess_answerability(
        has_evidence=True,
        retrieval_strong=True,
        gated=True,
        confidence=0.7,
        anchor_score=0.5,
        max_score=0.8,
        min_score=0.35,
        contradiction_count=1,
    )

    assert strong["state"] == "answerable"
    assert strong["answerable"] is True
    assert conflict["state"] == "conflict"
    assert conflict["answerable"] is False


@pytest.mark.asyncio
async def test_rag_agent_returns_query_plan_trace_and_protocol_evidence(monkeypatch):
    calls = []

    async def fake_search_chunks(
        self,
        query,
        user_id,
        top_k=6,
        *,
        tenant_id=None,
        workspace_id=None,
    ):
        calls.append(("chunks", query, tenant_id, workspace_id))
        return [
            ContextChunk(
                content="退款政策说明与流程：用户可在订单完成后7天内申请退款。",
                source_type="document",
                score=0.82,
                confidence=0.82,
                metadata={
                    "document_id": "doc-a",
                    "chunk_index": 1,
                    "title": "退款制度",
                },
            )
        ]

    async def fake_search_llmwiki(
        self,
        query,
        user_id,
        top_k=3,
        *,
        tenant_id=None,
        workspace_id=None,
    ):
        calls.append(("llmwiki", query, tenant_id, workspace_id))
        return [
            ContextChunk(
                content="退款政策是订单完成后7天内可申请退款的规则。",
                source_type="llmwiki",
                score=0.76,
                confidence=0.76,
                metadata={
                    "document_id": "doc-a",
                    "chunk_id": "wiki-a",
                    "title": "退款制度",
                    "question": "什么是退款政策？",
                    "keywords": ["退款", "政策"],
                },
            )
        ]

    monkeypatch.setattr("plugins.document_plugin.DocumentPlugin.search_chunks", fake_search_chunks)
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_llmwiki", fake_search_llmwiki
    )
    monkeypatch.setattr("agents.rag_agent.settings.rag_rerank_enabled", False)

    result = await RagAgent().execute(
        TaskMessage(
            task_id="rag-plan-1",
            agent_type="rag",
            query="退款政策是什么？",
            user_id="u1",
            params={
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "sources": ["documents"],
                "top_k": 3,
            },
        )
    )

    assert result.status == "success"
    assert result.metadata["rag_query_plan"]["version"] == RAG_PLAN_VERSION
    assert result.metadata["rag_trace"]["version"] == "rag_trace_v1"
    assert result.metadata["rag_trace"]["query_plan"]["filters"]["tenant_id"] == "tenant-a"
    assert result.metadata["quality"]["answerability_state"] in {"answerable", "weak"}
    assert result.metadata["rag_evidence_objects"][0]["version"] == RAG_EVIDENCE_VERSION
    assert (
        result.evidence_objects[0].metadata["rag_evidence"]["access_scope"]["workspace_id"]
        == "workspace-a"
    )
    assert any(
        call[0] == "llmwiki" and call[2] == "tenant-a" and call[3] == "workspace-a"
        for call in calls
    )


@pytest.mark.asyncio
async def test_document_fallback_keeps_workspace_scope(monkeypatch):
    calls = []

    async def fake_search_chunks(
        self,
        query,
        user_id,
        top_k=6,
        *,
        tenant_id=None,
        workspace_id=None,
    ):
        calls.append(("chunks", tenant_id, workspace_id))
        return []

    async def fake_search_llmwiki(
        self,
        query,
        user_id,
        top_k=3,
        *,
        tenant_id=None,
        workspace_id=None,
    ):
        calls.append(("llmwiki", tenant_id, workspace_id))
        return []

    monkeypatch.setattr("plugins.document_plugin.DocumentPlugin.search_chunks", fake_search_chunks)
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_llmwiki", fake_search_llmwiki
    )
    monkeypatch.setattr("agents.rag_agent.settings.rag_rerank_enabled", False)

    result = await RagAgent().execute(
        TaskMessage(
            task_id="rag-project-fallback",
            agent_type="rag",
            query="只在项目知识中查找不存在的条目",
            user_id="u1",
            params={
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "sources": ["documents"],
            },
        )
    )

    assert result.status == "success"
    assert calls
    assert all(call[1:] == ("tenant-a", "workspace-a") for call in calls)


@pytest.mark.asyncio
async def test_rag_agent_keeps_partial_results_and_records_sanitized_lane_failure(monkeypatch):
    async def fake_search_chunks(
        self,
        query,
        user_id,
        top_k=6,
        *,
        tenant_id=None,
        workspace_id=None,
    ):
        return [
            ContextChunk(
                content="报销制度要求员工在费用发生后 30 天内提交申请。",
                source_type="document",
                score=0.92,
                confidence=0.92,
                metadata={"document_id": "doc-policy", "chunk_index": 1, "title": "报销制度"},
            )
        ]

    async def failing_search_llmwiki(*args, **kwargs):
        raise RuntimeError("credential=super-secret")

    monkeypatch.setattr("plugins.document_plugin.DocumentPlugin.search_chunks", fake_search_chunks)
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_llmwiki", failing_search_llmwiki
    )
    monkeypatch.setattr("agents.rag_agent.settings.rag_rerank_enabled", False)

    result = await RagAgent().execute(
        TaskMessage(
            task_id="rag-degraded",
            agent_type="rag",
            query="报销制度要求什么？",
            user_id="u1",
            params={
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "sources": ["documents"],
                "max_search_queries": 1,
            },
        )
    )

    trace = result.metadata["rag_trace"]["retrieval"]
    assert result.status == "success"
    assert result.metadata["chunks"]
    assert result.metadata["quality"]["retrieval_availability"] == "degraded"
    assert trace["availability"] == "degraded"
    assert trace["lanes"]["document"]["succeeded"] == 1
    assert trace["lanes"]["llmwiki"]["errors"] == 1
    assert trace["failures"] == [
        {
            "lane": "llmwiki",
            "phase": "primary",
            "query_variant": 0,
            "reason": "retrieval_error",
            "retryable": True,
            "elapsed_ms": trace["failures"][0]["elapsed_ms"],
        }
    ]
    assert "super-secret" not in str(trace)


@pytest.mark.asyncio
async def test_enterprise_rag_timeout_is_not_reported_as_missing_knowledge(monkeypatch):
    async def slow_search_knowledge(**kwargs):
        await asyncio.sleep(0.05)
        return []

    monkeypatch.setattr("agents.rag_agent.search_knowledge", slow_search_knowledge)
    monkeypatch.setattr("agents.rag_agent.settings.rag_lane_timeout_seconds", 0.01)
    monkeypatch.setattr("agents.rag_agent.settings.rag_rerank_enabled", False)

    result = await RagAgent().execute(
        TaskMessage(
            task_id="rag-timeout",
            agent_type="rag",
            query="公司保密制度是什么？",
            user_id="u1",
            params={
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "sources": ["knowledge", "documents"],
                "knowledge_space_ids": ["space-company"],
                "enterprise_grounding_required": True,
                "max_search_queries": 1,
            },
        )
    )

    trace = result.metadata["rag_trace"]["retrieval"]
    assert result.status == "success"
    assert result.metadata["sources"] == ["knowledge"]
    assert result.metadata["chunks"] == []
    assert result.metadata["quality"]["retrieval_availability"] == "unavailable"
    assert "检索通道暂时不可用" in result.content
    assert "未将本次故障视为知识库无内容" in result.content
    assert "retrieval_unavailable" in result.metadata["quality"]["answerability"]["reasons"]
    assert trace["availability"] == "unavailable"
    assert trace["failures"][0]["reason"] == "deadline_exceeded"


@pytest.mark.asyncio
async def test_quality_sufficiency_uses_effective_evidence_threshold(monkeypatch):
    async def fake_search_chunks(*args, **kwargs):
        return []

    async def fake_search_llmwiki(*args, **kwargs):
        return [
            ContextChunk(
                content="这是一条与查询有关但证据强度不足的文档摘要。",
                source_type="llmwiki",
                score=0.5,
                confidence=0.5,
                metadata={
                    "document_id": "doc-weak",
                    "chunk_id": "wiki-weak",
                    "title": "弱证据",
                    "question": "查询规则",
                },
            )
        ]

    monkeypatch.setattr("plugins.document_plugin.DocumentPlugin.search_chunks", fake_search_chunks)
    monkeypatch.setattr(
        "plugins.document_plugin.DocumentPlugin.search_llmwiki", fake_search_llmwiki
    )
    monkeypatch.setattr("agents.rag_agent.settings.rag_rerank_enabled", False)
    monkeypatch.setattr("agents.rag_agent.settings.rag_min_evidence_score", 0.65)

    result = await RagAgent().execute(
        TaskMessage(
            task_id="rag-threshold",
            agent_type="rag",
            query="查询规则有哪些",
            user_id="u1",
            params={
                "tenant_id": "tenant-a",
                "workspace_id": "workspace-a",
                "sources": ["documents"],
                "max_search_queries": 1,
            },
        )
    )

    assert result.metadata["rag_query_plan"]["min_score"] == 0.65
    assert result.metadata["quality"]["avg_score"] < 0.65
    assert result.metadata["quality"]["sufficient"] is False
