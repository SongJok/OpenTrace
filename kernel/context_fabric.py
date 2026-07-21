"""
上下文织网 — 统一上下文组装（替代分散的 context_* 入口）。

新代码推荐路径：
  TurnContext → ContextFabric.assemble() → AssembledContext

遗留模块（context_builder、context_composer、context_assembler）仍作为本门面后的实现细节。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

@dataclass
class FabricContext:
    """Unified assembled context for one turn."""

    summary_block: str = ""
    memory_block: str = ""
    attachment_block: str = ""
    state_block: str = ""
    recent_turns: list[dict[str, Any]] = field(default_factory=list)
    memory_injection_query: str = ""
    total_tokens: int = 0
    compressed: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

class ContextFabric:
    def evolve_runtime(
        self,
        session_id: str,
        *,
        goal_id: str = "",
        runtime_phase: str = "",
        evidence_ref: str = "",
        memory_ref: str = "",
    ) -> dict[str, Any]:
        from kernel.context_fabric_session import evolve_fabric_from_runtime

        return evolve_fabric_from_runtime(
            session_id,
            goal_id=goal_id,
            runtime_phase=runtime_phase,
            evidence_ref=evidence_ref,
            memory_ref=memory_ref,
        )

    def get_session_graph(self, session_id: str) -> dict[str, Any]:
        from kernel.context_fabric_session import get_fabric_session_store

        return get_fabric_session_store().get_or_create(session_id).to_dict()

    async def assemble(self, turn_context: Any) -> FabricContext:
        from kernel.context_assembler import get_context_assembler

        assembled = await get_context_assembler().assemble(turn_context)
        meta = dict(getattr(turn_context, "metadata", None) or {})
        goal_proj = meta.get("goal_world_projection")
        fabric_graph = None
        try:
            from kernel.context_fabric_graph import build_fabric_graph_from_turn

            fabric_graph = build_fabric_graph_from_turn(turn_context, goal_proj)
            meta["fabric_graph"] = fabric_graph.to_dict()
        except Exception:
            pass
        return FabricContext(
            summary_block=getattr(assembled, "summary_block", "") or "",
            memory_block=getattr(assembled, "memory_block", "") or "",
            attachment_block=getattr(assembled, "attachment_block", "") or "",
            state_block=getattr(assembled, "state_block", "") or "",
            recent_turns=list(getattr(assembled, "recent_turns", None) or []),
            memory_injection_query=getattr(assembled, "memory_injection_query", "") or "",
            total_tokens=int(getattr(assembled, "total_tokens", 0) or 0),
            compressed=bool(getattr(assembled, "compressed", False)),
            metadata={"source": "context_fabric", **meta},
        )

def get_context_fabric() -> ContextFabric:
    if not hasattr(get_context_fabric, "_inst"):
        get_context_fabric._inst = ContextFabric()  # type: ignore[attr-defined]
    return get_context_fabric._inst  # type: ignore[attr-defined]