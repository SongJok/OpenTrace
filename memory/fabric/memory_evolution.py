"""Memory fabric evolution after turns."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


def evolve_session_memory(
    session_id: str,
    *,
    request_id: str,
    goal_id: str,
    relations_added: int = 0,
) -> dict[str, Any]:
    try:
        from memory.fabric.router_singleton import get_memory_fabric_router

        router = get_memory_fabric_router()
        count = len(getattr(router, "_relations", []) or [])
    except Exception as exc:
        logger.warning("memory_evolution_count_failed", session_id=session_id, error=str(exc))
        count = 0
    return {
        "session_id": session_id,
        "request_id": request_id,
        "goal_id": goal_id,
        "relation_count": count,
        "relations_added": relations_added,
    }