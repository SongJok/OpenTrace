"""Coverage evaluation for web search — gap detection and supplemental search hints."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CoverageReport:
    score: float = 0.0
    covered_dimensions: list[str] = field(default_factory=list)
    missing_dimensions: list[str] = field(default_factory=list)
    should_supplement: bool = False
    supplement_queries: list[str] = field(default_factory=list)
    round: int = 0

    def to_metadata(self) -> dict[str, Any]:
        return {
            "coverage_score": round(self.score, 4),
            "covered_dimensions": list(self.covered_dimensions),
            "missing_dimensions": list(self.missing_dimensions),
            "should_supplement": self.should_supplement,
            "supplement_queries": list(self.supplement_queries),
            "coverage_round": self.round,
        }


_DIMENSION_PATTERNS: tuple[tuple[str, str], ...] = (
    ("entity", r"谁|什么公司|哪家|which|who|company"),
    ("time", r"何时|什么时候|今年|本月|when|202\d|Q[1-4]"),
    ("location", r"哪里|在哪|城市|where|city"),
    ("metric", r"多少|价格|营收|销量|how much|revenue|sales"),
    ("comparison", r"对比|相比|vs|versus|compare"),
    ("causal", r"为什么|原因|why|because"),
)


def decompose_query_dimensions(query: str) -> list[str]:
    q = (query or "").lower()
    found: list[str] = []
    for dim, pat in _DIMENSION_PATTERNS:
        if re.search(pat, q, re.I):
            found.append(dim)
    if not found:
        found.append("topic")
    return found


def evaluate_coverage(
    query: str,
    ranked_items: list[dict[str, Any]],
    *,
    round_index: int = 0,
    min_score: float = 0.55,
) -> CoverageReport:
    """Score how well web results cover query dimensions (deterministic)."""
    dims = decompose_query_dimensions(query)
    if not ranked_items:
        return CoverageReport(
            score=0.0,
            covered_dimensions=[],
            missing_dimensions=dims,
            should_supplement=True,
            supplement_queries=[query],
            round=round_index,
        )

    corpus = " ".join(
        str(it.get("content") or it.get("snippet") or it.get("title") or "")
        for it in ranked_items[:10]
    ).lower()

    covered: list[str] = []
    missing: list[str] = []
    for dim in dims:
        pat = next((p for d, p in _DIMENSION_PATTERNS if d == dim), None)
        if dim == "topic":
            if len(corpus) > 40:
                covered.append(dim)
            else:
                missing.append(dim)
            continue
        if pat and re.search(pat, corpus, re.I):
            covered.append(dim)
        else:
            missing.append(dim)

    score = len(covered) / max(1, len(dims))
    should = score < min_score and round_index < 2
    supplements: list[str] = []
    if should:
        for m in missing[:3]:
            supplements.append(f"{query} {m}")
        if not supplements:
            supplements.append(query)

    return CoverageReport(
        score=score,
        covered_dimensions=covered,
        missing_dimensions=missing,
        should_supplement=should,
        supplement_queries=supplements,
        round=round_index,
    )