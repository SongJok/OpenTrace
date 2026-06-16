"""Pre-turn world model hydrate — merge persisted grounding into in-process store."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


async def hydrate_world_model_for_turn(
    *,
    session_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Load Redis/cross-process snapshot when flags enabled; return hydrate metadata."""
    sid = (session_id or "").strip()
    out: dict[str, Any] = {"hydrated": False}
    if not sid:
        return out

    md = dict(metadata or {})
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_world_state_persist_enabled", False)):
            from world.world_state_redis import hydrate_session

            snap = await hydrate_session(sid)
            if snap:
                out["hydrated"] = True
                out["world_snapshot_keys"] = list(snap.keys())[:16]
    except Exception as exc:
        logger.debug("world_hydrate_redis_skipped", error=str(exc))

    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_world_model_cross_process_enabled", False)):
            from world.cross_process_world import get_cross_process_world

            merged = await get_cross_process_world().fetch_merged(sid)
            if merged and merged.slices:
                out["cross_process_slices"] = merged.to_dict()
                out["hydrated"] = True
                md["world_cross_process"] = merged.to_dict()
    except Exception as exc:
        logger.debug("world_hydrate_cross_process_skipped", error=str(exc))

    return out