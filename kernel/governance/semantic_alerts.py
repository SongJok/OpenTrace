"""Operational alerts from semantic OS metrics — canonical."""

from __future__ import annotations

from typing import Any

REASONING_DRIFT_WARN = 0.55
REASONING_DRIFT_CRITICAL = 0.75
GOAL_STABILITY_WARN = 0.65
MEMORY_POLLUTION_WARN = 0.45
PLANNER_VOLATILITY_WARN = 0.5


def evaluate_health_alerts(
    turn_snapshot: dict[str, Any] | None,
    session_trend: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    alerts: list[dict[str, Any]] = []
    snap = turn_snapshot or {}
    trend = session_trend or {}

    drift = float(snap.get("reasoning_drift", 0) or 0)
    avg_drift = float(trend.get("avg_reasoning_drift", 0) or 0)
    stab = float(snap.get("goal_stability", 1) or 1)
    avg_stab = float(trend.get("avg_goal_stability", 1) or 1)
    mem_pol = float(snap.get("memory_pollution_risk", 0) or 0)
    vol = float(snap.get("planner_volatility", 0) or 0)

    if drift >= REASONING_DRIFT_CRITICAL or avg_drift >= REASONING_DRIFT_CRITICAL:
        alerts.append(
            {
                "code": "reasoning_drift_critical",
                "severity": "critical",
                "message": "Reasoning drift exceeds critical threshold",
                "value": max(drift, avg_drift),
            }
        )
    elif drift >= REASONING_DRIFT_WARN or avg_drift >= REASONING_DRIFT_WARN:
        alerts.append(
            {
                "code": "reasoning_drift_warn",
                "severity": "warning",
                "message": "Elevated reasoning drift",
                "value": max(drift, avg_drift),
            }
        )

    if stab < GOAL_STABILITY_WARN or avg_stab < GOAL_STABILITY_WARN:
        alerts.append(
            {
                "code": "goal_stability_low",
                "severity": "warning",
                "message": "Goal stability degraded",
                "value": min(stab, avg_stab),
            }
        )

    if mem_pol >= MEMORY_POLLUTION_WARN:
        alerts.append(
            {
                "code": "memory_pollution_risk",
                "severity": "warning",
                "message": "Memory pollution risk elevated",
                "value": mem_pol,
            }
        )

    if vol >= PLANNER_VOLATILITY_WARN:
        alerts.append(
            {
                "code": "planner_volatility_high",
                "severity": "info",
                "message": "Planner volatility high (replan/refine activity)",
                "value": vol,
            }
        )

    return alerts


def export_turn_observability(
    session_id: str,
    *,
    turn_snapshot: dict[str, Any],
    session_trend: dict[str, Any],
    route: str = "",
) -> dict[str, Any]:
    alerts = evaluate_health_alerts(turn_snapshot, session_trend)
    return {
        "session_id": session_id,
        "route": route,
        "cognitive_health_turn": turn_snapshot,
        "cognitive_health_trend": session_trend,
        "alerts": alerts,
        "alert_count": len(alerts),
    }