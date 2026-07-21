"""记忆关系引擎 — 关联记忆片段与目标、能力、证据。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MemoryRelation:
    memory_id: str
    goal_id: str = ""
    capability_type: str = ""
    evidence_id: str = ""
    artifact_id: str = ""
    salience: float = 0.5
    relation_type: str = "supports"
    metadata: dict[str, Any] = field(default_factory=dict)


class MemoryFabricRouter:
    """Route memory writes/reads through a lightweight relation graph."""

    def __init__(self) -> None:
        self._relations: list[MemoryRelation] = []

    def bind(
        self,
        memory_id: str,
        *,
        goal_id: str = "",
        capability_type: str = "",
        evidence_id: str = "",
        salience: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryRelation:
        rel = MemoryRelation(
            memory_id=memory_id,
            goal_id=goal_id,
            capability_type=capability_type,
            evidence_id=evidence_id,
            salience=salience,
            metadata=dict(metadata or {}),
        )
        self._relations.append(rel)
        try:
            import asyncio

            from memory.fabric.memory_graph import (
                ensure_memory_graph_hydrated,
                get_memory_graph,
                persist_memory_graph,
            )

            sid = str((metadata or {}).get("session_id", "default"))
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(ensure_memory_graph_hydrated(sid))
            except RuntimeError:
                pass
            g = get_memory_graph(sid)
            g.upsert_node(memory_id, "memory", metadata or {})
            if goal_id:
                g.upsert_node(goal_id, "goal", {})
                g.link(memory_id, goal_id, relation="bound_to_goal", weight=salience)
            if evidence_id:
                g.upsert_node(evidence_id, "evidence", {})
                g.link(memory_id, evidence_id, relation="supports", weight=salience)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(persist_memory_graph(sid))
            except RuntimeError:
                pass
        except Exception as exc:
            logger.warning(
                "memory_fabric_graph_bind_failed",
                session_id=sid,
                memory_id=memory_id,
                error=str(exc),
            )
        return rel

    def graph_snapshot(self, session_id: str) -> dict[str, Any]:
        try:
            from memory.fabric.memory_graph import get_memory_graph

            return get_memory_graph(session_id).to_dict()
        except Exception as exc:
            logger.warning(
                "memory_fabric_graph_snapshot_failed",
                session_id=session_id,
                error=str(exc),
            )
            return {"nodes": [], "edges": []}

    def query_by_goal(self, goal_id: str) -> list[MemoryRelation]:
        return [r for r in self._relations if r.goal_id == goal_id]

    def decay_salience(self, factor: float = 0.95) -> None:
        for r in self._relations:
            r.salience *= factor