"""RAG query planning, evidence protocol and answerability helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from knowledge.query import build_knowledge_query_plan

RAG_PLAN_VERSION = "rag_query_plan_v1"
RAG_EVIDENCE_VERSION = "rag_evidence_object_v1"


@dataclass(slots=True)
class RagRetrievalLane:
    """A retrieval lane with explicit strategy knobs."""

    name: str
    enabled: bool = True
    weight: float = 1.0
    top_k: int = 5
    reason: str = ""


@dataclass(slots=True)
class RagQueryPlan:
    """Explicit retrieval plan for one RAG turn."""

    version: str
    raw_query: str
    normalized_query: str
    rewritten_query: str
    query_type: str
    hints: list[str]
    query_terms: list[str]
    query_variants: list[str]
    lanes: list[RagRetrievalLane]
    filters: dict[str, Any]
    top_k: int
    min_score: float
    answerability_gate: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    knowledge_plan: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["lanes"] = [asdict(lane) for lane in self.lanes if lane.enabled]
        return data


def _dedupe_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        v = (value or "").strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _lane_weights(query_type: str) -> dict[str, float]:
    weights = {
        "knowledge": 1.12,
        "document": 1.0,
        "llmwiki": 0.9,
        "memory": 0.75,
        "episodic": 0.65,
    }
    if query_type == "definition":
        weights.update({"knowledge": 1.25, "llmwiki": 1.15, "document": 0.95})
    elif query_type == "fact":
        weights.update({"knowledge": 1.2, "document": 1.15, "llmwiki": 0.95})
    elif query_type == "procedure":
        weights.update({"knowledge": 1.2, "document": 1.1, "llmwiki": 0.85})
    elif query_type == "comparison":
        weights.update({"document": 1.0, "llmwiki": 1.0, "memory": 0.65})
    elif query_type == "memory":
        weights.update({"memory": 1.2, "episodic": 1.05, "document": 0.55, "llmwiki": 0.45})
    return weights


def build_rag_query_plan(
    *,
    raw_query: str,
    normalized_query: str,
    rewritten_query: str,
    query_type: str,
    hints: list[str],
    query_terms: list[str],
    sources: list[str],
    top_k: int,
    llmwiki_top_k: int,
    min_score: float,
    user_id: str,
    tenant_id: str | None,
    workspace_id: str | None,
    params: dict[str, Any] | None = None,
) -> RagQueryPlan:
    """Build an explicit RAG retrieval plan before any retrieval call."""

    params = params or {}
    weights = _lane_weights(query_type)
    source_set = {str(src) for src in sources}

    lanes = [
        RagRetrievalLane(
            name="knowledge",
            enabled="knowledge" in source_set,
            weight=weights["knowledge"],
            top_k=max(top_k, 6),
            reason="published knowledge pages and traceable claims",
        ),
        RagRetrievalLane(
            name="document",
            enabled="documents" in source_set,
            weight=weights["document"],
            top_k=max(top_k, 8),
            reason="primary knowledge-base chunk retrieval",
        ),
        RagRetrievalLane(
            name="llmwiki",
            enabled="documents" in source_set,
            weight=weights["llmwiki"],
            top_k=llmwiki_top_k,
            reason="curated document QA/summary lane",
        ),
        RagRetrievalLane(
            name="memory",
            enabled="semantic_memory" in source_set,
            weight=weights["memory"],
            top_k=min(max(top_k, 5), 10),
            reason="stable user profile and semantic memory",
        ),
        RagRetrievalLane(
            name="episodic",
            enabled="episodic_memory" in source_set,
            weight=weights["episodic"],
            top_k=min(max(top_k, 5), 10),
            reason="recent events and session memory",
        ),
    ]

    variants = [rewritten_query]
    if query_terms:
        title_seed = " ".join(query_terms[:4])
        variants.insert(0, title_seed)
        variants.extend([f"{rewritten_query} {term}".strip() for term in query_terms[:4]])
        if any(term in rewritten_query for term in ["队长", "身份", "权限", "角色"]):
            variants.insert(0, "队长 身份 权限 角色 申请 条件")
    max_variants = int(params.get("max_search_queries", 3) or 3)
    max_variants = max(1, min(max_variants, 6))

    return RagQueryPlan(
        version=RAG_PLAN_VERSION,
        raw_query=raw_query,
        normalized_query=normalized_query,
        rewritten_query=rewritten_query,
        query_type=query_type,
        hints=list(hints or []),
        query_terms=list(query_terms or []),
        query_variants=_dedupe_keep_order(variants)[:max_variants],
        lanes=lanes,
        filters={
            "user_id": user_id,
            "tenant_id": (tenant_id or "default"),
            "workspace_id": (workspace_id or "default"),
            "acl_scope_enforced": True,
            "pre_retrieval_filtering": True,
        },
        top_k=top_k,
        min_score=round(float(min_score), 4),
        answerability_gate={
            "min_score": round(float(min_score), 4),
            "min_anchor_score": 0.30,
            "weak_anchor_score": 0.15,
            "min_confidence": 0.35,
            "states": ["answerable", "weak", "unanswerable", "conflict"],
        },
        budget={
            "max_query_variants": max_variants,
            "max_candidates": max(top_k * 3, 20),
            "rerank_top_k": min(top_k * 3, 20),
        },
        knowledge_plan=build_knowledge_query_plan(query_type, top_k).to_dict(),
    )


def lane_weight(plan: RagQueryPlan, source_type: str) -> float:
    lane = lane_from_source_type(source_type)
    for item in plan.lanes:
        if item.name == lane:
            return item.weight
    return 1.0


def lane_from_source_type(source_type: str) -> str:
    st = (source_type or "document").lower()
    if st in {"knowledge", "knowledge_page", "knowledge_claim", "knowledge_relation"}:
        return "knowledge"
    if st == "llmwiki":
        return "llmwiki"
    if st in {"memory", "semantic_memory"}:
        return "memory"
    if st in {"episodic", "episodic_memory"}:
        return "episodic"
    return "document"


def normalize_rag_evidence(
    item: dict[str, Any],
    *,
    plan: RagQueryPlan,
    rank: int | None = None,
    citation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Normalize heterogeneous retrieval rows into one evidence protocol."""

    source_type = str(item.get("source_type") or "document")
    score = float(item.get("score", 0.0) or 0.0)
    raw_score = float(item.get("raw_score", score) or 0.0)
    weighted_score = float(
        item.get("weighted_score", min(0.999, raw_score * lane_weight(plan, source_type))) or 0.0
    )
    text = str(item.get("text") or item.get("answer") or item.get("content") or "")
    evidence_id = str(item.get("id") or item.get("chunk_id") or f"{source_type}:{rank or 0}")
    return {
        "version": RAG_EVIDENCE_VERSION,
        "id": evidence_id,
        "rank": rank,
        "lane": lane_from_source_type(source_type),
        "source_type": source_type,
        "title": str(item.get("title") or ""),
        "text": text,
        "score": round(score, 4),
        "raw_score": round(raw_score, 4),
        "weighted_score": round(weighted_score, 4),
        "document_id": item.get("document_id"),
        "chunk_id": item.get("chunk_id") or item.get("id"),
        "chunk_index": item.get("chunk_index"),
        "knowledge_page_id": item.get("knowledge_page_id"),
        "claim_id": item.get("claim_id"),
        "relation_id": item.get("relation_id"),
        "target_page_id": item.get("target_page_id"),
        "source_id": item.get("source_id"),
        "source_version_id": item.get("source_version_id"),
        "space_id": item.get("space_id"),
        "classification": item.get("classification"),
        "source_system": item.get("source_system"),
        "sync_status": item.get("sync_status"),
        "effective_from": item.get("effective_from"),
        "effective_to": item.get("effective_to"),
        "review_due_at": item.get("review_due_at"),
        "provenance": dict(item.get("provenance") or {}),
        "matched_query": item.get("matched_query") or plan.rewritten_query,
        "evidence_tier": item.get("evidence_tier", "contextual"),
        "disclosure_stage": item.get("disclosure_stage", "source_evidence"),
        "citation": citation or {},
        "access_scope": dict(plan.filters),
        "answer_anchor": {
            "claim_anchor_score": item.get("claim_anchor_score"),
            "claim_anchored": item.get("claim_anchored"),
            "needs_review": bool(item.get("needs_review")),
        },
        "metadata": {
            "query_type": plan.query_type,
            "rerank_score": item.get("_rerank_score"),
            "rrf_score": item.get("rrf_score"),
            "rrf_raw_score": item.get("rrf_raw_score"),
            "retrieval_hit_count": item.get("retrieval_hit_count"),
            "retrieval_ranks": item.get("retrieval_ranks"),
            "matched_queries": item.get("matched_queries"),
            "memory_type": item.get("memory_type"),
            "authority": item.get("authority"),
            "knowledge_status": item.get("knowledge_status"),
        },
    }


def assess_answerability(
    *,
    has_evidence: bool,
    retrieval_strong: bool,
    gated: bool,
    confidence: float,
    anchor_score: float,
    max_score: float,
    min_score: float,
    contradiction_count: int = 0,
    claim_needs_review: bool = False,
) -> dict[str, Any]:
    """Return a tri-state answerability decision with explicit reasons."""

    reasons: list[str] = []
    state = "unanswerable"
    answerable = False

    if contradiction_count:
        state = "conflict"
        reasons.append("conflicting_evidence")
    elif not has_evidence:
        reasons.append("no_evidence")
    elif claim_needs_review:
        state = "weak"
        answerable = bool(retrieval_strong and has_evidence)
        reasons.append("claim_anchor_needs_review")
    elif retrieval_strong and gated and confidence >= 0.35 and anchor_score >= 0.30:
        state = "answerable"
        answerable = True
        reasons.append("strong_retrieval_and_anchor")
    elif retrieval_strong and max_score >= min_score + 0.05 and anchor_score >= 0.15:
        state = "weak"
        answerable = True
        reasons.append("score_strong_anchor_weak")
    elif max_score >= 0.45 and anchor_score >= 0.10:
        state = "weak"
        answerable = True
        reasons.append("fallback_score_anchor")
    else:
        reasons.append("below_answerability_threshold")

    return {
        "answerable": answerable,
        "state": state,
        "reasons": reasons,
        "signals": {
            "has_evidence": has_evidence,
            "retrieval_strong": retrieval_strong,
            "gated": gated,
            "confidence": round(float(confidence), 4),
            "anchor_score": round(float(anchor_score), 4),
            "max_score": round(float(max_score), 4),
            "min_score": round(float(min_score), 4),
            "contradiction_count": contradiction_count,
            "claim_needs_review": claim_needs_review,
        },
    }


def build_rag_trace(
    *,
    plan: RagQueryPlan,
    total_retrieved: int,
    deduped_count: int,
    final_count: int,
    quality: dict[str, Any],
    dropped: list[dict[str, Any]] | None = None,
    retrieval_attempts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compact retrieval trace for observability and eval replay."""

    attempts = [dict(item) for item in retrieval_attempts or []]
    lane_stats: dict[str, dict[str, Any]] = {}
    failures: list[dict[str, Any]] = []
    for attempt in attempts:
        lane = str(attempt.get("lane") or "unknown")
        status = str(attempt.get("status") or "error")
        stats = lane_stats.setdefault(
            lane,
            {
                "attempts": 0,
                "succeeded": 0,
                "timed_out": 0,
                "errors": 0,
                "result_count": 0,
                "max_elapsed_ms": 0,
            },
        )
        stats["attempts"] += 1
        stats["result_count"] += max(0, int(attempt.get("result_count") or 0))
        stats["max_elapsed_ms"] = max(
            stats["max_elapsed_ms"], max(0, int(attempt.get("elapsed_ms") or 0))
        )
        if status == "success":
            stats["succeeded"] += 1
            continue
        if status == "timeout":
            stats["timed_out"] += 1
        else:
            stats["errors"] += 1
        failures.append(
            {
                "lane": lane,
                "phase": str(attempt.get("phase") or "primary"),
                "query_variant": max(0, int(attempt.get("query_variant") or 0)),
                "reason": "deadline_exceeded" if status == "timeout" else "retrieval_error",
                "retryable": True,
                "elapsed_ms": max(0, int(attempt.get("elapsed_ms") or 0)),
            }
        )

    succeeded = sum(int(item["succeeded"]) for item in lane_stats.values())
    if attempts and succeeded == 0:
        availability = "unavailable"
    elif failures:
        availability = "degraded"
    elif attempts:
        availability = "available"
    else:
        availability = "not_attempted"

    return {
        "version": "rag_trace_v1",
        "query_plan": plan.to_dict(),
        "retrieval": {
            "total_retrieved": total_retrieved,
            "deduped_count": deduped_count,
            "final_count": final_count,
            "dropped": dropped or [],
            "availability": availability,
            "degraded": bool(failures),
            "lanes": lane_stats,
            "failures": failures,
        },
        "quality": dict(quality or {}),
    }
