"""Post-turn semantic health + capability evolution (sync-safe metadata merge)."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


def finalize_semantic_and_evolution(
    request: Any,
    response: Any | None = None,
) -> None:
    """Merge cognitive health / self-optimization / evolution into request metadata."""
    try:
        md = dict(getattr(request, "metadata", None) or {})
        rmd = dict(getattr(response, "metadata", None) or {}) if response is not None else {}
        merged = {**md, **rmd}

        if response is not None:
            rmd2 = getattr(response, "metadata", None) or {}
            if isinstance(rmd2, dict):
                existing = (rmd2.get("semantic_observability") or {}).get("cognitive_health")
                if isinstance(existing, dict) and existing:
                    evo_only = _run_evolution_only(request, response, merged)
                    md = dict(getattr(request, "metadata", None) or {})
                    md["capability_evolution"] = evo_only
                    if hasattr(request, "metadata"):
                        request.metadata = md
                    return

        from kernel.governance.semantic_helpers import record_kernel_turn_health

        sem = record_kernel_turn_health(
            request=request,
            response=response,
            ctx=None,
            route=str(merged.get("route") or "kernel_finalize"),
        )
        md = dict(getattr(request, "metadata", None) or {})
        md["semantic_observability"] = sem

        evo = _run_evolution_only(request, response, merged)
        md["capability_evolution"] = evo
        if hasattr(request, "metadata"):
            request.metadata = md
    except Exception as exc:
        logger.debug("finalize_semantic_and_evolution_skipped", error=str(exc))


def _run_evolution_only(request: Any, response: Any | None, merged: dict) -> dict:
    passed = True
    fusion_conf = 0.75
    if response is not None:
        passed = bool(getattr(response, "passed_validation", True))
        fusion_conf = float(getattr(response, "validation_score", 0.75) or 0.75)
    caps = list(merged.get("capabilities_used") or [])
    if not caps:
        cap = str(merged.get("capability_type") or merged.get("route") or "")
        if cap:
            caps = [cap]
    from kernel.capability_intelligence.evolution_hook import record_capability_evolution_turn

    skip_evo = merged.get("capability_evolution")
    if not isinstance(skip_evo, dict):
        skip_evo = None

    return record_capability_evolution_turn(
        capability_types=caps,
        passed=passed,
        latency_ms=int(getattr(response, "total_latency_ms", 0) or 0) if response else 0,
        evidence_quality=fusion_conf,
        query_preview=str(getattr(request, "query", "") or "")[:80],
        skip_if_executive_evolution=skip_evo,
    )