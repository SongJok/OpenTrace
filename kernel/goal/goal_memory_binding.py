"""将目标完成与 Memory Fabric 关系图绑定。"""

from __future__ import annotations

from typing import Any


def bind_goal_turn_to_memory_fabric(
    *,
    session_id: str,
    request_id: str,
    goal_id: str,
    route: str = "",
    query_preview: str = "",
    answer_preview: str = "",
) -> None:
    try:
        from memory.fabric.router_singleton import bind_turn_memory

        bind_turn_memory(
            session_id=session_id,
            request_id=request_id,
            goal_id=goal_id,
            query=query_preview,
            answer_preview=answer_preview,
            route=route,
        )
    except Exception:
        pass


def bind_from_runtime_context(ctx: Any, answer_preview: str = "") -> None:
    md = getattr(ctx, "metadata", None) or {}
    gg = md.get("goal_graph") or {}
    sid = str(getattr(ctx, "session_id", "") or "")
    bind_goal_turn_to_memory_fabric(
        session_id=sid,
        request_id=str(getattr(ctx, "request_id", "") or ""),
        goal_id=str(gg.get("root_goal_id", "") or getattr(ctx, "request_id", "")),
        route=str(md.get("route", "") or ""),
        query_preview=str(getattr(ctx, "query", "") or "")[:120],
        answer_preview=answer_preview[:200],
    )