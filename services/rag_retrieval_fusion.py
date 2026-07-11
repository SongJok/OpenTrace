"""Reciprocal Rank Fusion (RRF) across RAG retrieval lanes."""

from __future__ import annotations

from typing import Any

_LANE_KEYS = ("knowledge", "document", "llmwiki", "memory", "episodic")


def _lane_of(item: dict[str, Any]) -> str:
    st = str(item.get("source_type") or "document").lower()
    if st in ("knowledge", "knowledge_page", "knowledge_claim", "knowledge_relation"):
        return "knowledge"
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
    lane_weights: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    """Merge heterogeneous retrieval hits with calibrated, weighted RRF.

    The previous implementation compared raw retrieval scores (roughly
    ``0..1``) against an unscaled ``1/(k+rank)`` value (roughly ``0.016``),
    which made RRF almost invisible.  Normalize the rank signal per lane and
    blend it with the calibrated input score so lane diversity can actually
    affect the final order.
    """
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

    weights = {str(key): max(0.0, float(value or 0.0)) for key, value in (lane_weights or {}).items()}
    rrf_scores: dict[str, float] = {}
    lane_max: dict[str, float] = {}
    key_to_item: dict[str, dict[str, Any]] = {}
    for lane, lane_items in lanes.items():
        lane_weight = weights.get(lane, 1.0)
        lane_max[lane] = lane_weight / (k + 1)
        for rank, it in enumerate(lane_items, start=1):
            key = _item_key(it)
            key_to_item[key] = it
            rrf_scores[key] = rrf_scores.get(key, 0.0) + lane_weight / (k + rank)

    ordered = sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    out: list[dict[str, Any]] = []
    for key, rrf in ordered:
        row = dict(key_to_item[key])
        lane = _lane_of(row)
        normalization = max(lane_max.get(lane, 1.0 / (k + 1)), 1e-9)
        rrf_normalized = min(1.0, rrf / normalization)
        original = min(1.0, max(0.0, float(row.get("score", 0.0) or 0.0)))
        row["raw_score"] = round(original, 4)
        row["rrf_score"] = round(rrf_normalized, 6)
        row["score"] = round(0.55 * original + 0.45 * rrf_normalized, 6)
        out.append(row)
    return out
