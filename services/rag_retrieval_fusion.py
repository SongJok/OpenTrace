"""Reciprocal Rank Fusion (RRF) across RAG retrieval lanes."""

from __future__ import annotations

from typing import Any

_LANE_KEYS = ("document", "llmwiki", "memory", "episodic")


def _lane_of(item: dict[str, Any]) -> str:
    st = str(item.get("source_type") or "document").lower()
    if st == "llmwiki":
        return "llmwiki"
    if st in ("memory", "semantic_memory"):
        return "memory"
    if st in ("episodic", "episodic_memory"):
        return "episodic"
    return "document"


def reciprocal_rank_fusion(
    items: list[dict[str, Any]],
    *,
    k: int = 60,
    top_n: int = 20,
) -> list[dict[str, Any]]:
    """Merge heterogeneous retrieval hits with RRF; preserves item dicts, sets rrf_score."""
    if not items:
        return []

    lanes: dict[str, list[dict[str, Any]]] = {lk: [] for lk in _LANE_KEYS}
    for it in items:
        lane = _lane_of(it)
        if lane not in lanes:
            lane = "document"
        lanes[lane].append(it)

    for lane_items in lanes.values():
        lane_items.sort(
            key=lambda x: float(x.get("score", 0.0) or 0.0),
            reverse=True,
        )

    def _item_key(it: dict[str, Any]) -> str:
        return (
            f"{it.get('source_type')}::{it.get('id')}::"
            f"{str(it.get('text') or it.get('answer') or '')[:80]}"
        )

    rrf_scores: dict[str, float] = {}
    key_to_item: dict[str, dict[str, Any]] = {}
    for lane_items in lanes.values():
        for rank, it in enumerate(lane_items, start=1):
            key = _item_key(it)
            key_to_item[key] = it
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (k + rank)

    ordered = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    out: list[dict[str, Any]] = []
    for key, rrf in ordered:
        row = dict(key_to_item[key])
        row["rrf_score"] = round(rrf, 6)
        row["score"] = max(float(row.get("score", 0.0) or 0.0), rrf)
        out.append(row)
    return out