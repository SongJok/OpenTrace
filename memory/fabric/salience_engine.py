"""Salience scoring for memory fabric retrieval."""

from __future__ import annotations

from typing import Any

def score_memory_item(item: dict[str, Any], *, goal_id: str = "") -> float:
    base = float(item.get("score", 0.5) or 0.5)
    if goal_id and item.get("goal_id") == goal_id:
        base = min(1.0, base + 0.25)
    recency = float(item.get("recency_boost", 0.0) or 0.0)
    return min(1.0, base + recency)

def rank_memory_items(items: list[dict[str, Any]], *, goal_id: str = "", limit: int = 8) -> list[dict[str, Any]]:
    scored = [(score_memory_item(it, goal_id=goal_id), it) for it in items]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [it for _, it in scored[:limit]]