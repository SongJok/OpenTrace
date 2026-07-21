"""RAG V3 hooks — chunk graph, document trust, cross-doc contradiction, claim anchor."""

from __future__ import annotations

from typing import Any

from services.evidence_graph.engine import (
    build_evidence_graph_from_items,
    detect_contradictions,
    rank_evidence,
    synthesize_evidence_summary,
)


def _claim_anchor_enabled() -> bool:
    try:
        from infra.config.settings import settings

        return bool(getattr(settings, "rag_claim_anchor_enabled", True))
    except Exception:
        return True


def run_lightweight_claim_check(
    query: str,
    ranked: list[dict[str, Any]],
    *,
    anchor_threshold: float = 0.28,
) -> dict[str, Any]:
    """Deterministic query–chunk anchor (no LLM). Flags unanchored top chunks."""
    from kernel.cognitive_controls import relevance_score

    q = (query or "").strip()
    if not q or not ranked:
        return {
            "enabled": _claim_anchor_enabled(),
            "anchor_threshold": anchor_threshold,
            "anchored_count": 0,
            "unanchored_count": 0,
            "top_anchor_score": 0.0,
            "claims": [],
        }

    claims: list[dict[str, Any]] = []
    anchored = 0
    top_anchor = 0.0
    for i, row in enumerate(ranked[:8]):
        text = str(row.get("content") or row.get("text") or row.get("snippet") or "")
        score = float(relevance_score(q, text))
        top_anchor = max(top_anchor, score)
        ok = score >= anchor_threshold
        if ok:
            anchored += 1
        row["claim_anchor_score"] = round(score, 4)
        row["claim_anchored"] = ok
        claims.append(
            {
                "index": i,
                "id": row.get("id", ""),
                "anchor_score": round(score, 4),
                "anchored": ok,
            }
        )

    unanchored = len(claims) - anchored
    return {
        "enabled": _claim_anchor_enabled(),
        "anchor_threshold": anchor_threshold,
        "anchored_count": anchored,
        "unanchored_count": unanchored,
        "top_anchor_score": round(top_anchor, 4),
        "needs_review": unanchored >= 2 and top_anchor < 0.35,
        "claims": claims,
    }


def enrich_evidence_intelligence(
    items: list[dict[str, Any]],
    *,
    query: str = "",
    source_kind: str = "document",
) -> dict[str, Any]:
    """Unified post-retrieval enrichment for RAG and Web evidence."""
    out = enrich_rag_evidence(items, query=query)
    out["source_kind"] = source_kind
    ranked = out.get("ranked_chunks") or []
    if _claim_anchor_enabled() and query:
        claim = run_lightweight_claim_check(query, ranked)
        out["claim_verification"] = claim
        fv = dict(out.get("fact_verification") or {})
        fv["claim_anchor"] = claim
        fv["needs_review"] = bool(fv.get("needs_review")) or claim.get("needs_review")
        out["fact_verification"] = fv
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_claim_graph_enabled", True)) and query and ranked:
            from services.evidence_graph.claim_graph import run_claim_pipeline

            cp = run_claim_pipeline(
                query,
                ranked,
                contradictions=out.get("contradictions"),
            )
            out["claim_graph"] = cp.get("claim_graph")
            out["supporting_claims"] = cp.get("supporting_claims", 0)
            out["conflicting_claims"] = cp.get("conflicting_claims", 0)
            if cp.get("needs_review"):
                fv = dict(out.get("fact_verification") or {})
                fv["needs_review"] = True
                out["fact_verification"] = fv
    except Exception:
        pass
    return out


def enrich_rag_evidence(
    chunks: list[dict[str, Any]],
    *,
    query: str = "",
) -> dict[str, Any]:
    """Post-retrieval enterprise enrichment (deterministic)."""
    for c in chunks:
        src = str(c.get("source", c.get("document_id", "")))
        c.setdefault("document_trust", 0.75 if src else 0.5)
        c.setdefault("source_type", "document")
    ranked = rank_evidence(chunks)
    cluster_meta: dict[str, Any] = {}
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "rag_evidence_cluster_enabled", True)):
            from services.rag_retrieval_clusters import cluster_evidence_chunks

            cluster_meta = cluster_evidence_chunks(ranked)
    except Exception:
        pass
    contradictions = detect_contradictions(ranked)
    graph = build_evidence_graph_from_items(ranked)
    chunk_graph = {
        "node_count": len(graph.to_dict()["nodes"]),
        "edge_count": len(graph.to_dict()["edges"]),
        "contradiction_count": len(contradictions),
    }
    verification = {
        "verified_count": sum(1 for r in ranked if float(r.get("rank_score", 0)) >= 0.55),
        "needs_review": len(contradictions) > 0,
    }
    return {
        "ranked_chunks": ranked,
        "evidence_clusters": cluster_meta,
        "chunk_graph": chunk_graph,
        "contradictions": contradictions,
        "evidence_graph": graph.to_dict(),
        "synthesis_preview": synthesize_evidence_summary(graph),
        "fact_verification": verification,
        "knowledge_evolution_hint": "refresh_stale_docs" if len(ranked) < 2 else "stable",
    }