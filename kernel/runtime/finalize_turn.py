"""Post-turn enterprise hooks — quota consume + usage metering."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from infra.observability.turn_metering import get_turn_tokens, merge_turn_tokens_into_metadata
from tenant.tenant_context import resolve_tenant_context

logger = get_logger(__name__)


def post_turn_enterprise_accounting(request: Any, response: Any | None = None) -> None:
    """Best-effort quota + usage after a successful kernel turn (sync-safe)."""
    try:
        md = merge_turn_tokens_into_metadata(dict(getattr(request, "metadata", None) or {}))
        if hasattr(request, "metadata"):
            request.metadata = md
    except Exception as exc:
        logger.debug("finalize_turn_merge_tokens_skipped", error=str(exc))
        md = dict(getattr(request, "metadata", None) or {})

    try:
        ctx = resolve_tenant_context(
            user_id=getattr(request, "user_id", None),
            session_id=getattr(request, "session_id", None),
            tenant_id=md.get("tenant_id"),
            org_id=md.get("org_id"),
            workspace_id=md.get("workspace_id"),
            metadata=md,
        )
    except Exception as exc:
        logger.warning("finalize_turn_tenant_context_skipped", error=str(exc))
        return

    try:
        from tenant.billing_runtime import apply_billing_to_metadata, resolve_turn_cost

        md = apply_billing_to_metadata(
            md,
            capability_type=str(md.get("capability_type") or md.get("route") or ""),
            goal_id=str((md.get("goal_graph") or {}).get("root_goal_id", "") or ""),
        )
        if hasattr(request, "metadata"):
            request.metadata = md
        cost = resolve_turn_cost(md)
    except Exception as exc:
        logger.debug("finalize_turn_billing_runtime_skipped", error=str(exc))
        cost = float(md.get("estimated_cost") or 0.0)
    if response is not None:
        try:
            rmd = getattr(response, "metadata", None) or {}
            if isinstance(rmd, dict):
                cost = float(
                    rmd.get("estimated_cost") or rmd.get("turn_cost") or cost
                )
        except Exception as exc:
            logger.warning("finalize_turn_response_cost_skipped", error=str(exc))

    try:
        import asyncio

        from control_plane.control_plane import get_enterprise_control_plane

        cp = get_enterprise_control_plane()

        async def _consume_async() -> None:
            await cp.consume_turn_quota_async(ctx, cost=cost)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_consume_async())
        except RuntimeError:
            cp.consume_turn_quota(ctx, cost=cost)
    except Exception as exc:
        logger.warning("finalize_turn_quota_consume_skipped", error=str(exc))

    try:
        from tenant.billing_runtime import record_turn_billing

        attr = record_turn_billing(
            ctx,
            metadata=md,
            capability_type=str(md.get("capability_type") or md.get("route") or ""),
            session_id=str(getattr(request, "session_id", "") or ""),
        )
        md["billing_attribution"] = attr.to_dict()
        if hasattr(request, "metadata"):
            request.metadata = md
    except Exception as exc:
        logger.debug("finalize_turn_billing_record_skipped", error=str(exc))

    tok = get_turn_tokens()
    cap = str(md.get("capability_type") or md.get("route") or "")
    try:
        from tenant.usage_metering import get_usage_metering

        get_usage_metering().record_turn(
            ctx,
            session_id=str(getattr(request, "session_id", "") or ""),
            goal_id=str((md.get("goal_graph") or {}).get("root_goal_id", "") or ""),
            capability_type=cap,
            prompt_tokens=int(tok.get("prompt_tokens", 0) or 0),
            completion_tokens=int(tok.get("completion_tokens", 0) or 0),
            extra_cost=cost,
        )
    except Exception as exc:
        logger.warning("finalize_turn_usage_record_skipped", error=str(exc))

    try:
        import asyncio

        from kernel.agent_runtime.learning_hook import record_agent_learning_signal

        passed = True
        confidence = 0.85
        latency_ms = 0
        if response is not None:
            passed = bool(getattr(response, "passed_validation", True))
            confidence = float(getattr(response, "validation_score", 0.85) or 0.85)
            latency_ms = int(getattr(response, "total_latency_ms", 0) or 0)
            rmd = getattr(response, "metadata", None) or {}
            if isinstance(rmd, dict) and rmd.get("validation_score") is not None:
                confidence = float(rmd.get("validation_score") or confidence)

        async def _learn() -> None:
            await record_agent_learning_signal(
                agent_type=cap or "turn",
                task_id=str(md.get("request_id") or getattr(request, "session_id", "") or ""),
                session_id=str(getattr(request, "session_id", "") or ""),
                passed=passed,
                confidence=confidence,
                latency_ms=latency_ms,
                metadata={
                    "query_preview": str(getattr(request, "query", "") or "")[:80],
                    "route": str(md.get("route") or cap),
                    "multi_turn": bool(md.get("multi_turn_resolution")),
                },
            )

        try:
            asyncio.get_running_loop().create_task(_learn())
        except RuntimeError:
            asyncio.run(_learn())
    except Exception as exc:
        logger.debug("finalize_turn_learning_skipped", error=str(exc))

    try:
        from kernel.runtime.finalize_semantic_and_evolution import finalize_semantic_and_evolution

        finalize_semantic_and_evolution(request, response)
    except Exception as exc:
        logger.debug("finalize_semantic_evolution_skipped", error=str(exc))

    try:
        import asyncio

        from kernel.world_turn_finalize import finalize_world_model_for_turn

        sid = str(getattr(request, "session_id", "") or "")

        async def _world() -> None:
            await finalize_world_model_for_turn(
                session_id=sid,
                request=request,
                response=response,
            )

        try:
            asyncio.get_running_loop().create_task(_world())
        except RuntimeError:
            asyncio.run(_world())
    except Exception as exc:
        logger.debug("finalize_turn_world_skipped", error=str(exc))