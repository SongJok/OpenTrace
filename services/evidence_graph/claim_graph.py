"""Claim layer — extract claims, verify, build claim graph for fusion."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Claim:
    claim_id: str
    text: str
    source_id: str = ""
    confidence: float = 0.5
    status: str = "proposed"  # proposed | supported | conflicting | rejected
    evidence_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text[:500],
            "source_id": self.source_id,
            "confidence": round(self.confidence, 4),
            "status": self.status,
            "evidence_ids": list(self.evidence_ids),
        }


def _claim_id(text: str, source: str) -> str:
    raw = f"{source}:{text[:120]}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def extract_claims_from_evidence(
    items: list[dict[str, Any]],
    *,
    max_claims: int = 12,
) -> list[Claim]:
    """Heuristic claim extraction from ranked evidence rows."""
    claims: list[Claim] = []
    seen: set[str] = set()
    sentence_split = re.compile(r"[。！？.!?]\s*")
    for it in items[:max_claims * 2]:
        body = str(it.get("content") or it.get("snippet") or "")[:800]
        if not body.strip():
            continue
        sid = str(it.get("id", it.get("chunk_id", "")))
        cred = float(it.get("credibility_score", it.get("credibility", 0.5)) or 0.5)
        for sent in sentence_split.split(body):
            s = sent.strip()
            if len(s) < 8:
                continue
            cid = _claim_id(s, sid)
            if cid in seen:
                continue
            seen.add(cid)
            claims.append(
                Claim(
                    claim_id=cid,
                    text=s,
                    source_id=sid,
                    confidence=cred,
                    status="proposed",
                    evidence_ids=[sid] if sid else [],
                )
            )
            if len(claims) >= max_claims:
                return claims
    return claims


def verify_claims_against_query(
    query: str,
    claims: list[Claim],
    *,
    anchor_threshold: float = 0.28,
) -> list[Claim]:
    from kernel.cognitive_controls import relevance_score

    q = (query or "").strip()
    out: list[Claim] = []
    for c in claims:
        score = float(relevance_score(q, c.text)) if q else 0.5
        if score >= anchor_threshold:
            c.status = "supported"
            c.confidence = max(c.confidence, score)
        else:
            c.status = "proposed"
        out.append(c)
    return out


def build_claim_graph(
    claims: list[Claim],
    contradictions: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
) -> dict[str, Any]:
    """Claim graph with supporting / conflicting counts for fusion metadata."""
    id_to_claim: dict[str, Claim] = {c.claim_id: c for c in claims}
    for pair in contradictions:
        a_id = str(pair.get("a", ""))
        b_id = str(pair.get("b", ""))
        for cid in (a_id, b_id):
            for c in claims:
                if c.source_id == cid or cid in c.evidence_ids:
                    c.status = "conflicting"

    supporting = sum(1 for c in claims if c.status == "supported")
    conflicting = sum(1 for c in claims if c.status == "conflicting")
    nodes = [c.to_dict() for c in claims]
    edges: list[dict[str, str]] = []
    for pair in contradictions:
        edges.append(
            {
                "source": str(pair.get("a", "")),
                "target": str(pair.get("b", "")),
                "relation": "contradicts",
            }
        )

    return {
        "claims": nodes,
        "edges": edges,
        "supporting_claims": supporting,
        "conflicting_claims": conflicting,
        "evidence_count": len(evidence_items),
        "claim_count": len(claims),
    }


def run_claim_pipeline(
    query: str,
    ranked_items: list[dict[str, Any]],
    contradictions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from services.evidence_graph.engine import detect_contradictions

    contradictions = contradictions if contradictions is not None else detect_contradictions(ranked_items)
    claims = extract_claims_from_evidence(ranked_items)
    claims = verify_claims_against_query(query, claims)
    graph = build_claim_graph(claims, contradictions, ranked_items)
    return {
        "claim_graph": graph,
        "supporting_claims": graph["supporting_claims"],
        "conflicting_claims": graph["conflicting_claims"],
        "needs_review": graph["conflicting_claims"] > 0 or graph["supporting_claims"] == 0,
    }