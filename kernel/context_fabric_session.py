"""Session-scoped dynamic context fabric graphs (evolve across turns)."""

from __future__ import annotations

from typing import Any

from kernel.context_fabric_graph import ContextFabricGraph, ContextFabricNode


class ContextFabricSessionStore:
    def __init__(self) -> None:
        self._graphs: dict[str, ContextFabricGraph] = {}

    def get_or_create(self, session_id: str) -> ContextFabricGraph:
        sid = session_id or "default"
        if sid not in self._graphs:
            self._graphs[sid] = ContextFabricGraph()
        return self._graphs[sid]

    def clear_session(self, session_id: str) -> None:
        self._graphs.pop(session_id or "default", None)


_store: ContextFabricSessionStore | None = None


def get_fabric_session_store() -> ContextFabricSessionStore:
    global _store
    if _store is None:
        _store = ContextFabricSessionStore()
    return _store


def sync_evidence_node(
    session_id: str,
    *,
    evidence_id: str,
    goal_id: str = "",
) -> None:
    """Link evidence into fabric session graph."""
    store = get_fabric_session_store()
    g = store.get_or_create(session_id)
    if evidence_id:
        from kernel.context_fabric_graph import ContextFabricNode

        eid = f"evidence:{evidence_id}"
        g.upsert(
            ContextFabricNode(
                node_id=eid,
                node_type="evidence",
                content_ref=evidence_id,
                salience=0.7,
                metadata={"goal_id": goal_id},
            )
        )
        if goal_id:
            g.link(eid, f"goal:{goal_id}")


def evolve_fabric_from_runtime(
    session_id: str,
    *,
    goal_id: str = "",
    runtime_phase: str = "",
    evidence_ref: str = "",
    memory_ref: str = "",
    salience: float = 0.6,
) -> dict[str, Any]:
    """Incrementally update session fabric during runtime (not one-shot assemble)."""
    g = get_fabric_session_store().get_or_create(session_id)
    if goal_id:
        gid = f"goal:{goal_id}"
        g.upsert(
            ContextFabricNode(
                node_id=gid,
                node_type="goal",
                content_ref=goal_id,
                salience=1.0,
                metadata={"phase": runtime_phase},
            )
        )
    if runtime_phase:
        rid = f"runtime:{session_id}:{runtime_phase}"
        g.upsert(
            ContextFabricNode(
                node_id=rid,
                node_type="runtime",
                content_ref=runtime_phase,
                salience=0.8,
            )
        )
        if goal_id:
            g.link(f"goal:{goal_id}", rid)
    if evidence_ref:
        eid = f"evidence:{evidence_ref[:48]}"
        g.upsert(
            ContextFabricNode(
                node_id=eid,
                node_type="evidence",
                content_ref=evidence_ref[:120],
                salience=salience,
            )
        )
        if goal_id:
            g.link(f"goal:{goal_id}", eid)
    if memory_ref:
        mid = f"memory:{memory_ref[:48]}"
        g.upsert(
            ContextFabricNode(
                node_id=mid,
                node_type="memory",
                content_ref=memory_ref[:120],
                salience=salience,
            )
        )
        if goal_id:
            g.link(f"goal:{goal_id}", mid)
    return g.to_dict()