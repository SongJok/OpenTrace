"""Bridge memory compression plans to Truth Maintenance System."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from memory.fabric.memory_compression import CompressionPlan, plan_memory_maintenance

logger = get_logger(__name__)


async def run_session_memory_maintenance(
    memories: list[dict[str, Any]],
    *,
    max_active: int = 128,
) -> dict[str, Any]:
    plan: CompressionPlan = plan_memory_maintenance(memories, max_active=max_active)
    out: dict[str, Any] = {"compression_plan": plan.to_dict()}
    try:
        from kernel.runtime.memory.truth_maintenance import TruthMaintenanceSystem

        tms = TruthMaintenanceSystem()
        report = await tms.run(memories=memories, auto_archive=True)
        out["tms_report"] = {
            "overall_health": report.overall_health,
            "memories_checked": report.memories_checked,
            "contradictions_detected": report.contradictions_detected,
            "memories_archived": report.memories_archived,
        }
    except Exception as exc:
        logger.warning("tms_bridge_run_skipped", error=str(exc))
        out["tms_report"] = {"skipped": True, "error": str(exc)[:200]}
    return out