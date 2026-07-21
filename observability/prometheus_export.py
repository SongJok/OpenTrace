"""Bridge enterprise telemetry into Prometheus metrics."""

from __future__ import annotations

from typing import Any


def record_enterprise_turn_metrics(
    *,
    tenant_id: str,
    success: bool,
    goal_stability: float,
    cost: float,
    capability_types: list[str] | None = None,
) -> None:
    from infra.observability.metrics import (
        ENTERPRISE_TURN_COST,
        ENTERPRISE_TURNS_TOTAL,
        GOAL_STABILITY,
    )

    tid = tenant_id or "default"
    ENTERPRISE_TURNS_TOTAL.labels(tenant_id=tid, success=str(success).lower()).inc()
    caps = capability_types or ["unknown"]
    share = cost / max(len(caps), 1)
    for cap in caps:
        ENTERPRISE_TURN_COST.labels(tenant_id=tid, capability_type=cap or "unknown").inc(share)
    GOAL_STABILITY.set(goal_stability)


def record_control_plane_denial(reason: str) -> None:
    from infra.observability.metrics import CONTROL_PLANE_DENIALS

    CONTROL_PLANE_DENIALS.labels(reason=(reason or "unknown")[:64]).inc()


def record_capability_sla(capability_type: str, success_rate: float) -> None:
    from infra.observability.metrics import CAPABILITY_SUCCESS_RATE

    CAPABILITY_SUCCESS_RATE.labels(capability_type=(capability_type or "unknown")[:64]).set(
        float(success_rate or 0.0)
    )