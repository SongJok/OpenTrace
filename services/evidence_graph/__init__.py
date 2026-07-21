"""Evidence graph — nodes, trust, contradiction edges."""

from services.evidence_graph.engine import (
    EvidenceGraph,
    build_evidence_graph_from_items,
    detect_contradictions,
    rank_evidence,
    synthesize_evidence_summary,
)

__all__ = [
    "EvidenceGraph",
    "build_evidence_graph_from_items",
    "detect_contradictions",
    "rank_evidence",
    "synthesize_evidence_summary",
]