"""进程级 MemoryFabricRouter 单例。"""

from __future__ import annotations

from memory.fabric.relation_engine import MemoryFabricRouter

_router: MemoryFabricRouter | None = None


def get_memory_fabric_router() -> MemoryFabricRouter:
    global _router
    if _router is None:
        _router = MemoryFabricRouter()
    return _router


def bind_turn_memory(
    *,
    session_id: str,
    request_id: str,
    goal_id: str,
    query: str,
    answer_preview: str,
    route: str = "",
) -> None:
    """将回合写入 episodic 时绑定到目标图（轻量关系）。"""
    router = get_memory_fabric_router()
    memory_id = f"{session_id}:{request_id}:turn"
    router.bind(
        memory_id,
        goal_id=goal_id or request_id,
        capability_type=route or "turn",
        salience=0.6,
        metadata={
            "session_id": session_id,
            "query_preview": query[:120],
            "answer_preview": answer_preview[:200],
        },
    )