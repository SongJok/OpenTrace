"""交互层查询流水线：意图识别、热缓存和渐进式披露。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from knowledge.orchestration.wiki.query.hot_memory import HotMemory
from knowledge.query import (
    build_knowledge_query_plan,
    infer_knowledge_query_type,
    search_knowledge,
)


class RetrievalLevel(StrEnum):
    L1_HOT = "l1_hot"
    L2_INDEX = "l2_index"
    L3_KNOWLEDGE = "l3_knowledge"
    L4_SOURCE = "l4_source"


@dataclass(slots=True)
class QueryResult:
    query: str
    query_type: str
    answer: str
    evidence: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    confidence: float
    retrieval_levels_used: list[RetrievalLevel] = field(default_factory=list)
    plan: dict[str, Any] = field(default_factory=dict)


SearchFunction = Callable[..., Awaitable[list[dict[str, Any]]]]


class QueryPipeline:
    """公共查询适配层；最终自然语言回答仍由 Manager/RAG 融合层生成。"""

    def __init__(
        self,
        *,
        hot_memory: HotMemory | None = None,
        search_function: SearchFunction = search_knowledge,
    ) -> None:
        self.hot_memory = hot_memory or HotMemory()
        self.search_function = search_function

    async def query(
        self,
        query: str,
        *,
        user_id: str = "shared",
        tenant_id: str = "default",
        workspace_id: str = "default",
        session_id: str | None = None,
        top_k: int = 5,
    ) -> QueryResult:
        query_type = infer_knowledge_query_type(query)
        plan = build_knowledge_query_plan(query_type, top_k)
        levels: list[RetrievalLevel] = []
        evidence = self.hot_memory.search(query, top_k=top_k)
        if evidence:
            levels.append(RetrievalLevel.L1_HOT)

        if len(evidence) < top_k:
            fetched = await self.search_function(
                query=query,
                user_id=user_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                top_k=top_k,
                query_type=query_type,
                session_id=session_id,
            )
            seen = {(str(item.get("source_type")), str(item.get("id"))) for item in evidence}
            for item in fetched:
                key = (str(item.get("source_type")), str(item.get("id")))
                if key not in seen:
                    seen.add(key)
                    evidence.append(item)

        stages = {str(item.get("disclosure_stage") or "") for item in evidence}
        if stages & {"summary", "page"}:
            levels.append(RetrievalLevel.L2_INDEX)
        if stages & {"claim", "relation"}:
            levels.append(RetrievalLevel.L3_KNOWLEDGE)
        if stages & {"source_evidence"}:
            levels.append(RetrievalLevel.L4_SOURCE)

        evidence = sorted(
            evidence,
            key=lambda item: float(item.get("score", 0.0) or 0.0),
            reverse=True,
        )[: max(1, top_k)]
        self.hot_memory.remember(evidence)
        confidence = self._confidence(evidence)
        sources = [
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "source_type": item.get("source_type"),
                "source_id": item.get("source_id"),
                "source_version_id": item.get("source_version_id"),
                "document_id": item.get("document_id"),
                "provenance": item.get("provenance") or {},
            }
            for item in evidence
        ]
        return QueryResult(
            query=query,
            query_type=query_type,
            answer=self._compose_context(evidence),
            evidence=evidence,
            sources=sources,
            confidence=confidence,
            retrieval_levels_used=list(dict.fromkeys(levels)),
            plan=plan.to_dict(),
        )

    @staticmethod
    def _confidence(evidence: list[dict[str, Any]]) -> float:
        if not evidence:
            return 0.0
        scores = [float(item.get("score", 0.0) or 0.0) for item in evidence]
        provenance_ratio = sum(bool(item.get("provenance")) for item in evidence) / len(evidence)
        return round(min(0.99, max(scores) * 0.7 + provenance_ratio * 0.3), 3)

    @staticmethod
    def _compose_context(evidence: list[dict[str, Any]]) -> str:
        if not evidence:
            return "未在已发布的 Wiki 知识中找到可溯源内容。"
        parts = []
        for item in evidence[:5]:
            title = str(item.get("title") or "Knowledge")
            text = str(item.get("text") or "").strip()
            if text:
                parts.append(f"[[{title}]]：{text}")
        return "\n\n".join(parts)
