"""Cognitive / runtime / business telemetry for enterprise operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CognitiveTelemetry:
    goal_stability: float = 1.0
    planner_drift: float = 0.0
    reasoning_drift: float = 0.0
    capability_entropy: float = 0.0
    memory_pollution_risk: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "goal_stability": self.goal_stability,
            "planner_drift": self.planner_drift,
            "reasoning_drift": self.reasoning_drift,
            "capability_entropy": self.capability_entropy,
            "memory_pollution_risk": self.memory_pollution_risk,
        }


@dataclass
class RuntimeTelemetry:
    success_rate: float = 1.0
    recovery_rate: float = 0.0
    fallback_rate: float = 0.0
    replan_rate: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "success_rate": self.success_rate,
            "recovery_rate": self.recovery_rate,
            "fallback_rate": self.fallback_rate,
            "replan_rate": self.replan_rate,
        }


@dataclass
class BusinessTelemetry:
    cost_per_goal: float = 0.0
    cost_per_tenant: float = 0.0
    cost_per_capability: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_per_goal": self.cost_per_goal,
            "cost_per_tenant": self.cost_per_tenant,
            "cost_per_capability": dict(self.cost_per_capability),
        }


class EnterpriseTelemetryCollector:
    def __init__(self) -> None:
        self._turns: list[dict[str, Any]] = []

    def record_turn(
        self,
        *,
        success: bool,
        replanned: bool = False,
        fallback: bool = False,
        recovered: bool = False,
        goal_id: str = "",
        tenant_id: str = "default",
        capability_types: list[str] | None = None,
        cost: float = 0.0,
        blocked_goals: int = 0,
        sub_goal_count: int = 0,
        memory_ref_count: int = 0,
    ) -> dict[str, Any]:
        caps = capability_types or []
        entropy = 0.0
        if len(caps) > 1:
            entropy = min(1.0, len(set(caps)) / max(len(caps), 1))
        pollution = min(1.0, memory_ref_count / 64.0) if memory_ref_count else 0.0
        stability = 1.0 - min(0.5, blocked_goals * 0.1 + (0.05 if replanned else 0.0))
        cognitive = CognitiveTelemetry(
            goal_stability=stability,
            planner_drift=0.1 if replanned else 0.0,
            reasoning_drift=0.05 if fallback else 0.0,
            capability_entropy=entropy,
            memory_pollution_risk=pollution,
        )
        n = len(self._turns) + 1
        successes = sum(1 for t in self._turns if t.get("success")) + (1 if success else 0)
        replans = sum(1 for t in self._turns if t.get("replanned")) + (1 if replanned else 0)
        fallbacks = sum(1 for t in self._turns if t.get("fallback")) + (1 if fallback else 0)
        recoveries = sum(1 for t in self._turns if t.get("recovered")) + (1 if recovered else 0)
        runtime = RuntimeTelemetry(
            success_rate=successes / n,
            recovery_rate=recoveries / n,
            fallback_rate=fallbacks / n,
            replan_rate=replans / n,
        )
        total_cost = sum(float(t.get("cost", 0)) for t in self._turns) + cost
        by_cap: dict[str, float] = {}
        for c in caps:
            by_cap[c] = by_cap.get(c, 0.0) + cost / max(len(caps), 1)
        business = BusinessTelemetry(
            cost_per_goal=cost if goal_id else 0.0,
            cost_per_tenant=total_cost,
            cost_per_capability=by_cap,
        )
        row = {
            "success": success,
            "replanned": replanned,
            "fallback": fallback,
            "recovered": recovered,
            "goal_id": goal_id,
            "tenant_id": tenant_id,
            "cost": cost,
            "sub_goal_count": sub_goal_count,
        }
        self._turns.append(row)
        snapshot = {
            "cognitive": cognitive.to_dict(),
            "runtime": runtime.to_dict(),
            "business": business.to_dict(),
        }
        try:
            from observability.prometheus_export import record_enterprise_turn_metrics

            record_enterprise_turn_metrics(
                tenant_id=tenant_id,
                success=success,
                goal_stability=cognitive.goal_stability,
                cost=cost,
                capability_types=caps,
            )
        except Exception:
            pass
        return snapshot

    def export_snapshot(self) -> dict[str, Any]:
        return {"turn_count": len(self._turns), "turns": list(self._turns[-50:])}


_collector: EnterpriseTelemetryCollector | None = None


def get_enterprise_telemetry() -> EnterpriseTelemetryCollector:
    global _collector
    if _collector is None:
        _collector = EnterpriseTelemetryCollector()
    return _collector