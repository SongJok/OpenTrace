"""Post-turn world model projection — grounding + optional Redis persist + slices."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class _TurnCtx:
    """Minimal adapter for project_from_context."""

    def __init__(
        self,
        *,
        session_id: str,
        metadata: dict[str, Any],
        user_preferences: list[Any] | None = None,
        request_id: str = "",
    ) -> None:
        self.session_id = session_id
        self.metadata = metadata
        self.user_preferences = user_preferences or metadata.get("user_preferences") or []
        self.request_id = request_id
        self.task_type = metadata.get("task_type", "")
        self.protected_intent = metadata.get("protected_intent", "")
        self.allowed_capabilities: list[str] = list(
            (metadata.get("intent_lock") or {}).get("allowed_capabilities") or []
        )


async def finalize_world_model_for_turn(
    *,
    session_id: str,
    request: Any,
    response: Any | None = None,
) -> dict[str, Any]:
    """将工作区回合投影为 RuntimeGroundingState，并在开关启用时持久化。"""
    sid = (session_id or getattr(request, "session_id", "") or "").strip()
    if not sid:
        return {}

    md = dict(getattr(request, "metadata", None) or {})
    if response is not None:
        rmd = getattr(response, "metadata", None) or {}
        if isinstance(rmd, dict):
            for k in (
                "goal_graph",
                "fabric_graph_live",
                "runtime_phase",
                "adaptive_risk",
                "capability_type",
                "route",
                "rag_evidence_intelligence",
                "data_turn_outcomes",
            ):
                if k in rmd and rmd[k] is not None:
                    md[k] = rmd[k]
            md["route"] = md.get("route") or getattr(response, "route", "")
            md["task_type"] = md.get("task_type") or getattr(response, "intent_category", "")

    prefs = md.get("user_preferences") or []
    if not prefs and getattr(request, "conversation_state", None) is not None:
        cs = request.conversation_state
        lp = getattr(cs, "learned_preferences", None)
        if isinstance(lp, dict):
            prefs = [f"{k}: {v}" for k, v in lp.items()]

    ctx = _TurnCtx(
        session_id=sid,
        metadata=md,
        user_preferences=prefs if isinstance(prefs, list) else [],
        request_id=str(md.get("request_id", "")),
    )

    try:
        from kernel.cognition.runtime_grounding import project_from_context

        state = project_from_context(ctx)
    except Exception as exc:
        logger.warning("world_project_skipped", error=str(exc))
        return {}

    try:
        from world.world_slice_hooks import maybe_publish_data_slice, maybe_publish_rag_slice

        await maybe_publish_data_slice(session_id=sid, metadata=md)
        await maybe_publish_rag_slice(session_id=sid, metadata=md)
    except Exception as exc:
        logger.debug("world_slice_hooks_skipped", error=str(exc))

    out: dict[str, Any] = {"world_grounding": state.to_dict()}
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_world_state_persist_enabled", False)):
            from world.world_state_redis import save_session_world_state

            await save_session_world_state(sid, state)
            out["world_state_persisted"] = True
    except Exception as exc:
        logger.debug("world_persist_skipped", error=str(exc))

    try:
        from tenant.tenant_context import resolve_tenant_context
        from world.world_runtime import build_shared_world_state

        tenant_ctx = resolve_tenant_context(
            user_id=getattr(request, "user_id", None),
            session_id=sid,
            tenant_id=md.get("tenant_id"),
            org_id=md.get("org_id"),
            workspace_id=md.get("workspace_id"),
            metadata=md,
        )
        shared = build_shared_world_state(ctx, tenant_ctx=tenant_ctx)
        out["shared_world_state"] = shared.to_dict()
    except Exception as exc:
        logger.debug("shared_world_skipped", error=str(exc))

    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_world_model_cross_process_enabled", False)):
            from world.cross_process_world import CrossProcessWorldFacade

            facade = CrossProcessWorldFacade()
            gwp = md.get("goal_world_projection") or {}
            if isinstance(gwp, dict) and gwp:
                await facade.publish_slice(sid, "goal", gwp, writer_id="finalize_turn")
            await facade.publish_slice(
                sid,
                "execution",
                {"route": md.get("route"), "capability_type": md.get("capability_type")},
                writer_id="finalize_turn",
            )
            snap = await facade.fetch_merged(sid)
            out["cross_process_world"] = snap.to_dict()
    except Exception as exc:
        logger.debug("cross_process_world_skipped", error=str(exc))

    if response is not None and hasattr(response, "metadata"):
        rmd = getattr(response, "metadata", None) or {}
        if isinstance(rmd, dict):
            rmd.setdefault("world_finalize", out)
            response.metadata = rmd
    return out

    return out
