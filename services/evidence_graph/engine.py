"""Evidence graph engine — ranking, contradiction, synthesis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvidenceNode:
    node_id: str
    content: str
    source: str = ""
    source_type: str = "unknown"
    credibility: float = 0.5
    relevance: float = 0.5
    trust_score: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "content": self.content[:500],
            "source": self.source,
            "source_type": self.source_type,
            "credibility": self.credibility,
            "relevance": self.relevance,
            "trust_score": self.trust_score,
            "metadata": dict(self.metadata),
        }


class EvidenceGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, EvidenceNode] = {}
        self._edges: list[dict[str, str]] = []

    def add(self, node: EvidenceNode) -> None:
        self._nodes[node.node_id] = node

    def link(self, source: str, target: str, relation: str) -> None:
        self._edges.append({"source": source, "target": target, "relation": relation})

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [n.to_dict() for n in self._nodes.values()],
            "edges": list(self._edges),
        }


def rank_evidence(items: list[dict[str, Any]], *, top_k: int = 12) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for i, it in enumerate(items):
        cred = float(it.get("credibility_score", it.get("credibility", 0.5)) or 0.5)
        rel = float(it.get("relevance_score", it.get("relevance", 0.5)) or 0.5)
        trust = float(it.get("trust_score", (cred + rel) / 2) or 0.5)
        doc_trust = float(it.get("document_trust", 0.6) or 0.6)
        score = 0.35 * cred + 0.35 * rel + 0.2 * trust + 0.1 * doc_trust
        row = dict(it)
        row["trust_score"] = round(trust, 4)
        row["rank_score"] = round(score, 4)
        scored.append((score, row))
    scored.sort(key=lambda x: -x[0])
    return [r for _, r in scored[:top_k]]


def detect_contradictions(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Heuristic: opposing polarity keywords on same topic stub."""
    positives = ("增长", "上升", "increase", "up", "yes", "是")
    negatives = ("下降", "减少", "decrease", "down", "no", "否", "不")
    pairs: list[dict[str, Any]] = []
    for i, a in enumerate(items):
        ca = (a.get("content") or a.get("snippet") or "").lower()
        if not ca:
            continue
        pa = any(p in ca for p in positives)
        na = any(n in ca for n in negatives)
        for j in range(i + 1, len(items)):
            b = items[j]
            cb = (b.get("content") or b.get("snippet") or "").lower()
            if not cb:
                continue
            pb = any(p in cb for p in positives)
            nb = any(n in cb for n in negatives)
            if (pa and nb) or (na and pb):
                pairs.append(
                    {
                        "a": a.get("id", i),
                        "b": b.get("id", j),
                        "type": "polarity_conflict",
                    }
                )
    return pairs


def build_evidence_graph_from_items(items: list[dict[str, Any]]) -> EvidenceGraph:
    g = EvidenceGraph()
    ranked = rank_evidence(items)
    for i, it in enumerate(ranked):
        nid = str(it.get("id", it.get("chunk_id", f"ev{i}")))
        g.add(
            EvidenceNode(
                node_id=nid,
                content=str(it.get("content") or it.get("snippet") or "")[:800],
                source=str(it.get("source", "")),
                source_type=str(it.get("source_type", "document")),
                credibility=float(it.get("credibility_score", 0.5) or 0.5),
                relevance=float(it.get("relevance_score", 0.5) or 0.5),
                trust_score=float(it.get("trust_score", 0.5) or 0.5),
                metadata={"rank_score": it.get("rank_score", 0)},
            )
        )
    for c in detect_contradictions(ranked):
        g.link(str(c["a"]), str(c["b"]), "contradicts")
    return g


def synthesize_evidence_summary(graph: EvidenceGraph, *, max_items: int = 5) -> str:
    nodes = sorted(
        graph._nodes.values(),
        key=lambda n: float(n.metadata.get("rank_score", n.trust_score)),
        reverse=True,
    )[:max_items]
    if not nodes:
        return ""
    lines = [f"- [{n.source_type}] {n.content[:200]}" for n in nodes]
    return "Evidence synthesis:\n" + "\n".join(lines)