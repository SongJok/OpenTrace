"""Pre-dispatch control plane gate — quota / compliance before heavy planning."""

from __future__ import annotations

from typing import Any


def _capability_from_force(md: dict[str, Any]) -> str:
    force = str(md.get("force_mode") or "")
    return {
        "data_query": "data_query",
        "rag": "document_retrieval",
        "web": "web_search",
    }.get(force, "")


def evaluate_request_control_plane(request: Any) -> dict[str, Any]:
    """Return decision dict; allowed=False should short-circuit with policy_denied."""
    try:
        from control_plane.control_plane import get_enterprise_control_plane

        md = dict(getattr(request, "metadata", None) or {})
        decision = get_enterprise_control_plane().evaluate_turn(
            user_id=getattr(request, "user_id", None),
            session_id=getattr(request, "session_id", None),
            tenant_id=md.get("tenant_id"),
            org_id=md.get("org_id"),
            workspace_id=md.get("workspace_id"),
            capability_type=_capability_from_force(md),
            estimated_cost=float(md.get("estimated_cost") or 0.01),
            pii_detected=bool(md.get("pii_detected")),
            data_region=str(md.get("data_residency") or ""),
            metadata=md,
        )
        out = decision.to_dict()
        if not out.get("allowed", True):
            try:
                from observability.prometheus_export import record_control_plane_denial

                v = (out.get("violations") or ["unknown"])[0]
                record_control_plane_denial(str(v))
            except Exception as exc:
                from infra.observability.logger import get_logger
                from infra.observability.runtime_degraded import record_runtime_degradation

                md = dict(getattr(request, "metadata", None) or {})
                record_runtime_degradation(
                    md,
                    subsystem="prometheus",
                    detail="control_plane_denial_metric",
                    exc=exc,
                )
                get_logger(__name__).warning("control_plane_denial_metric_failed", error=str(exc))
        return out
    except Exception as exc:
        from infra.observability.logger import get_logger
        from infra.observability.runtime_degraded import record_runtime_degradation

        md = dict(getattr(request, "metadata", None) or {})
        record_runtime_degradation(
            md,
            subsystem="control_plane",
            detail="evaluate_turn_unavailable_fail_open",
            exc=exc,
        )
        get_logger(__name__).warning("control_plane_gate_fail_open", error=str(exc))
        if isinstance(md, dict):
            try:
                request.metadata = md
            except Exception as meta_exc:
                get_logger(__name__).warning(
                    "control_plane_metadata_attach_failed",
                    error=str(meta_exc),
                )
        return {"allowed": True, "violations": [], "fail_open": True, "degraded": True}


async def evaluate_request_control_plane_async(request: Any) -> dict[str, Any]:
    """Async gate — Redis-backed quota when enterprise_quota_redis_enabled."""
    try:
        from control_plane.control_plane import get_enterprise_control_plane

        md = dict(getattr(request, "metadata", None) or {})
        decision = await get_enterprise_control_plane().evaluate_turn_async(
            user_id=getattr(request, "user_id", None),
            session_id=getattr(request, "session_id", None),
            tenant_id=md.get("tenant_id"),
            org_id=md.get("org_id"),
            workspace_id=md.get("workspace_id"),
            capability_type=_capability_from_force(md),
            estimated_cost=float(md.get("estimated_cost") or 0.01),
            pii_detected=bool(md.get("pii_detected")),
            data_region=str(md.get("data_residency") or ""),
            metadata=md,
        )
        return decision.to_dict()
    except Exception as exc:
        from infra.observability.logger import get_logger
        from infra.observability.runtime_degraded import record_runtime_degradation

        md = dict(getattr(request, "metadata", None) or {})
        record_runtime_degradation(
            md,
            subsystem="control_plane",
            detail="evaluate_turn_async_unavailable_fail_open",
            exc=exc,
        )
        get_logger(__name__).warning("control_plane_gate_async_fail_open", error=str(exc))
        return {"allowed": True, "violations": [], "fail_open": True, "degraded": True}