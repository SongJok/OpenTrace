"""Unified episodic write: relation graph + session memory evolution."""

from __future__ import annotations

from typing import Any


def remember_turn(
    *,
    session_id: str,
    request_id: str,
    goal_id: str,
    query: str,
    answer_preview: str,
    route: str = "",
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Single entry for turn memory binding (router + graph + evolution counter)."""
    from memory.fabric.memory_evolution import evolve_session_memory
    from memory.fabric.router_singleton import bind_turn_memory, get_memory_fabric_router

    bind_turn_memory(
        session_id=session_id,
        request_id=request_id,
        goal_id=goal_id,
        query=query,
        answer_preview=answer_preview,
        route=route,
    )
    router = get_memory_fabric_router()
    for eid in evidence_ids or []:
        router.bind(
            f"{session_id}:{request_id}:ev:{eid}",
            goal_id=goal_id,
            evidence_id=eid,
            salience=0.7,
            metadata={"session_id": session_id},
        )
    evo = evolve_session_memory(
        session_id,
        request_id=request_id,
        goal_id=goal_id,
        relations_added=1 + len(evidence_ids or []),
    )
    snap = router.graph_snapshot(session_id)
    return {"evolution": evo, "graph": snap}