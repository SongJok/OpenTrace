"""Evidence graph engine."""

from __future__ import annotations

from services.evidence_graph.engine import (
    build_evidence_graph_from_items,
    detect_contradictions,
    rank_evidence,
)


def test_rank_and_contradiction():
    items = [
        {"id": "a", "content": "sales increase", "credibility_score": 0.8},
        {"id": "b", "content": "sales decrease", "credibility_score": 0.7},
    ]
    ranked = rank_evidence(items)
    assert ranked[0]["rank_score"] >= ranked[1]["rank_score"]
    conflicts = detect_contradictions(ranked)
    assert conflicts
    g = build_evidence_graph_from_items(ranked)
    assert g.to_dict()["edges"]