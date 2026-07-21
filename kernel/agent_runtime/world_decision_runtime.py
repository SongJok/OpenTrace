"""World decision runtime — heuristic projected / counterfactual slices for planners."""

from __future__ import annotations

import re
from typing import Any

from kernel.agent_runtime.world_projection import (
    WorldProjection,
    WorldProjectionBundle,
    apply_counterfactual_assumption,
    build_projection_bundle_from_context,
)

_SCALE_PATTERNS: list[tuple[re.Pattern[str], str, float]] = [
    (re.compile(r"库存.{0,6}(减少|下降|降).{0,4}(\d+)\s*%", re.I), "inventory", 0.0),
    (re.compile(r"inventory.{0,12}(down|decrease|reduce).{0,4}(\d+)\s*%", re.I), "inventory", 0.0),
    (re.compile(r"预算.{0,6}(砍|削减|减少).{0,4}(\d+)\s*%", re.I), "budget", 0.0),
    (re.compile(r"budget.{0,12}(cut|reduce).{0,4}(\d+)\s*%", re.I), "budget", 0.0),
]


def _extract_scale_factor(text: str, var: str) -> tuple[str, dict[str, Any]] | None:
    for pat, key, _ in _SCALE_PATTERNS:
        if key != var:
            continue
        m = pat.search(text)
        if not m:
            continue
        try:
            pct = float(m.group(2))
            factor = max(0.0, 1.0 - pct / 100.0)
            return (
                f"{key}_down_{int(pct)}pct",
                {key: {"op": "scale", "factor": factor}},
            )
        except (TypeError, ValueError, IndexError):
            continue
    return None


def enrich_world_projection_for_turn(
    ctx: Any,
    *,
    query: str = "",
    goal_description: str = "",
) -> WorldProjectionBundle:
    """Attach projected + optional counterfactual slices to context metadata."""
    bundle = build_projection_bundle_from_context(ctx)
    text = f"{query}\n{goal_description}".strip()
    if bundle.current and not bundle.current.variables:
        bundle.current.variables.setdefault("turn_query_preview", text[:200])

    projected_vars = dict(bundle.current.variables if bundle.current else {})
    projected_vars["planning_mode"] = "decision_support"
    bundle.projected = WorldProjection(
        kind="projected",
        session_id=bundle.current.session_id if bundle.current else "",
        tenant_id=bundle.current.tenant_id if bundle.current else "",
        variables=projected_vars,
        assumptions=["baseline_from_current_world"],
        confidence=0.55,
        metadata={"source": "world_decision_runtime"},
    )

    for var in ("inventory", "budget"):
        hit = _extract_scale_factor(text, var)
        if hit:
            assumption, deltas = hit
            bundle = apply_counterfactual_assumption(
                bundle,
                assumption=assumption,
                variable_deltas=deltas,
            )
            break

    md = dict(getattr(ctx, "metadata", None) or {})
    md.update(bundle.to_metadata_dict())
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_predictive_world_enabled", True)):
            from kernel.cognition.predictive_world import enrich_world_projection_with_predictions

            wp = dict(md.get("goal_world_projection") or {})
            md["goal_world_projection"] = enrich_world_projection_with_predictions(
                wp,
                query=query,
            )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_degradation_in_context

        record_degradation_in_context(
            ctx,
            subsystem="predictive_world",
            detail="enrich_world_projection_with_predictions",
            exc=exc,
        )
    ctx.metadata = md
    return bundle
