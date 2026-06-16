"""Post-turn capability evolution — execution memory + EvolutionEngine.on_turn_complete."""

from __future__ import annotations

from typing import Any


def record_capability_evolution_turn(
    *,
    capability_types: list[str] | None = None,
    passed: bool = True,
    latency_ms: int = 0,
    evidence_quality: float = 0.75,
    query_preview: str = "",
    skip_if_executive_evolution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Feed execution memory and tick evolution engine (best-effort)."""
    out: dict[str, Any] = {"recorded": [], "insights": []}
    if skip_if_executive_evolution and skip_if_executive_evolution.get("source") == "cognitive_executive":
        out["skipped"] = "executive_already_evolved"
        out["insights"] = list(skip_if_executive_evolution.get("insights") or [])
        out["recorded"] = list(skip_if_executive_evolution.get("recorded") or [])
        out["turn_count"] = skip_if_executive_evolution.get("turn_count")
        return out
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_capability_evolution_enabled", True)):
            out["skipped"] = "evolution_disabled"
            return out
        if not bool(getattr(settings, "kernel_capability_intelligence_phase2_enabled", True)):
            out["skipped"] = "phase2_disabled"
            return out

        from kernel.capability_intelligence.execution_memory import execution_memory
        from kernel.capability_intelligence.evolution import _ensure_evolution_engine
        from kernel.capability_intelligence.profile import ExecutionRecord
        from kernel.capability_intelligence.profiler import CapabilityProfiler
        from kernel.capability_intelligence.strategy_memory import strategy_memory

        caps = list(capability_types or [])
        if not caps:
            caps = ["turn"]

        preview = (query_preview or "")[:80]
        for cap in caps[:12]:
            execution_memory.record(
                ExecutionRecord(
                    capability_type=cap,
                    query_preview=preview,
                    success=bool(passed),
                    latency_ms=int(latency_ms or 0),
                    evidence_quality=max(0.0, min(1.0, float(evidence_quality))),
                    timestamp=__import__("time").time(),
                )
            )
            out["recorded"].append(cap)

        profiler = CapabilityProfiler()
        interval = int(getattr(settings, "kernel_capability_evolution_interval", 10) or 10)
        engine = _ensure_evolution_engine(
            execution_memory=execution_memory,
            strategy_memory=strategy_memory,
            reasoner=profiler.get_reasoner(),
            interval=interval,
        )
        insights = engine.on_turn_complete()
        out["insights"] = [
            {
                "insight_type": i.insight_type,
                "capability_type": i.capability_type,
                "severity": i.severity,
                "message": i.message[:200],
            }
            for i in insights
        ]
        out["turn_count"] = engine._turn_count
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out