"""Capability selection using registry metadata + topology."""

from __future__ import annotations

from typing import Any

from kernel.runtime.capability import capability_registry


def rank_capabilities_for_intent(
    capability_types: list[str],
    *,
    intent_category: str = "general",
    allowed: list[str] | None = None,
    max_items: int = 8,
) -> list[dict[str, Any]]:
    """Single ranking path: Control Plane descriptors + intent/topology boosts."""
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_capability_score_ranking_enabled", True)):
            from kernel.capability_intelligence.capability_score import rank_capabilities_by_score

            return rank_capabilities_by_score(
                capability_types,
                intent_category=intent_category,
            )[:max_items]
    except Exception:
        pass
    from kernel.capability_runtime.capability_control_plane import (
        get_capability_descriptor,
        rank_capabilities_for_intent as control_plane_rank,
    )
    from kernel.capability_runtime.topology import dependents_of

    base = control_plane_rank(
        capability_types,
        allowed=allowed,
        max_items=max_items,
    )
    if not base:
        return []

    out: list[dict[str, Any]] = []
    for row in base:
        ctype = str(row.get("capability_type", "") or "")
        score = float(row.get("score", 0.0) or 0.0)
        if intent_category == "data_query" and ctype == "data_query":
            score += 0.5
        if dependents_of(ctype):
            score += 0.05
        desc = get_capability_descriptor(ctype)
        meta = desc.to_dict() if desc else capability_registry.runtime_metadata(ctype)
        out.append(
            {
                "capability_type": ctype,
                "score": round(score, 4),
                "metadata": meta,
                "owner_runtime": row.get("owner_runtime") or (desc.owner_runtime if desc else ""),
            }
        )
    out.sort(key=lambda x: float(x.get("score", 0.0)), reverse=True)
    return out[:max_items]