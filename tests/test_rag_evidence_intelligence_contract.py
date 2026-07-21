"""RAG evidence intelligence V3."""

from __future__ import annotations

from services.rag_evidence_intelligence import enrich_rag_evidence


def test_enrich_rag_evidence_graph():
    out = enrich_rag_evidence(
        [
            {"id": "c1", "content": "policy A", "credibility_score": 0.9},
            {"id": "c2", "content": "policy B", "credibility_score": 0.4},
        ],
        query="policy",
    )
    assert out["chunk_graph"]["node_count"] >= 2
    assert "evidence_graph" in out


def test_enrich_evidence_intelligence_claim_anchor():
    from services.rag_evidence_intelligence import enrich_evidence_intelligence

    out = enrich_evidence_intelligence(
        [
            {"id": "c1", "content": "退款政策说明与流程", "credibility_score": 0.8},
            {"id": "c2", "content": "unrelated xyz", "credibility_score": 0.5},
        ],
        query="退款政策",
        source_kind="document",
    )
    assert out.get("source_kind") == "document"
    assert "claim_verification" in out
    assert out["claim_verification"]["anchored_count"] >= 1