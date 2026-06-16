"""Single extension point for CognitiveAgent learning → capability intelligence (optional)."""

from __future__ import annotations

import time
from typing import Any


async def record_agent_learning_signal(
    *,
    agent_type: str,
    task_id: str,
    session_id: str,
    passed: bool,
    confidence: float,
    evidence_quality: float | None = None,
    latency_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Record lightweight learning signal; failure memory + feedback loop when enabled."""
    out: dict[str, Any] = {
        "agent_type": agent_type,
        "task_id": task_id,
        "passed": passed,
        "confidence": confidence,
    }
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_capability_intelligence_enabled", True)):
            out["skipped"] = "capability_intelligence_disabled"
            return out
        from kernel.capability_intelligence.failure_memory import FailureMemory, FailureRecord

        if not passed:
            FailureMemory().record(
                FailureRecord(
                    capability_type=agent_type,
                    failure_type="cognitive_reflection_failed",
                    context_snapshot=f"task={task_id} session={session_id}",
                )
            )
            out["failure_recorded"] = True

        try:
            from kernel.capability_intelligence.feedback import CapabilityFeedbackLoop
            from kernel.capability_intelligence.profile import ExecutionRecord
            from kernel.capability_intelligence.profiler import CapabilityProfiler

            profiler = CapabilityProfiler()
            loop = CapabilityFeedbackLoop(profiler)
            eq = float(evidence_quality if evidence_quality is not None else confidence)
            preview = str((metadata or {}).get("query_preview", task_id))[:80]
            loop.record(
                ExecutionRecord(
                    capability_type=agent_type,
                    query_preview=preview,
                    success=bool(passed),
                    latency_ms=int(latency_ms or 0),
                    evidence_quality=max(0.0, min(1.0, eq)),
                    timestamp=time.time(),
                )
            )
            out["feedback_recorded"] = True
            out["recent_stats"] = loop.recent_stats(agent_type, n=10)
        except Exception as fb_exc:
            out["feedback_error"] = str(fb_exc)[:120]

        if passed and confidence >= 0.75:
            try:
                from infra.config.settings import settings

                auto_apply = bool(
                    getattr(settings, "kernel_agent_learning_auto_apply", False)
                )
                if not auto_apply:
                    out["strategy_shadow"] = True
                else:
                    from kernel.capability_intelligence.profile import StrategyRecord
                    from kernel.capability_intelligence.strategy_memory import StrategyMemory

                    domain = str((metadata or {}).get("query_type", "general"))[:40]
                    StrategyMemory().record(
                        StrategyRecord(
                            strategy_type="direct",
                            capabilities_used=[agent_type],
                            query_domain=domain,
                            query_preview=str((metadata or {}).get("query_preview", ""))[:80],
                            success=True,
                            turn_success=True,
                            latency_ms=int(latency_ms or 0),
                            timestamp=time.time(),
                        )
                    )
                    out["strategy_hint_stored"] = True
            except Exception:
                pass
    except Exception as exc:
        out["error"] = str(exc)[:200]
    return out