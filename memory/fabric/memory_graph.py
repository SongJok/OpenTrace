"""In-process memory relation graph (session-scoped nodes + edges)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class MemoryGraphNode:
    node_id: str
    node_type: str  # memory | goal | evidence | capability
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class MemoryGraphEdge:
    source_id: str
    target_id: str
    relation: str = "supports"
    weight: float = 0.5


class MemoryGraphStore:
    def __init__(self) -> None:
        self._nodes: dict[str, MemoryGraphNode] = {}
        self._edges: list[MemoryGraphEdge] = []

    def upsert_node(self, node_id: str, node_type: str, payload: dict[str, Any] | None = None) -> None:
        self._nodes[node_id] = MemoryGraphNode(
            node_id=node_id,
            node_type=node_type,
            payload=dict(payload or {}),
        )

    def link(
        self,
        source_id: str,
        target_id: str,
        *,
        relation: str = "supports",
        weight: float = 0.5,
    ) -> None:
        for existing in self._edges:
            if (
                existing.source_id == source_id
                and existing.target_id == target_id
                and existing.relation == relation
            ):
                existing.weight = weight
                return
        self._edges.append(
            MemoryGraphEdge(
                source_id=source_id,
                target_id=target_id,
                relation=relation,
                weight=weight,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {"id": n.node_id, "type": n.node_type, **n.payload}
                for n in self._nodes.values()
            ],
            "edges": [
                {
                    "source": e.source_id,
                    "target": e.target_id,
                    "relation": e.relation,
                    "weight": e.weight,
                }
                for e in self._edges
            ],
        }


_by_session: dict[str, MemoryGraphStore] = {}
_hydrated: set[str] = set()


def _apply_snapshot(store: MemoryGraphStore, snap: dict[str, Any]) -> None:
    for n in snap.get("nodes") or []:
        if not isinstance(n, dict):
            continue
        nid = str(n.get("id", ""))
        if not nid:
            continue
        ntype = str(n.get("type", "memory"))
        payload = {k: v for k, v in n.items() if k not in ("id", "type")}
        store.upsert_node(nid, ntype, payload)
    for e in snap.get("edges") or []:
        if not isinstance(e, dict):
            continue
        src = str(e.get("source", ""))
        tgt = str(e.get("target", ""))
        if src and tgt:
            store.link(
                src,
                tgt,
                relation=str(e.get("relation", "supports")),
                weight=float(e.get("weight", 0.5) or 0.5),
            )


def get_memory_graph(session_id: str) -> MemoryGraphStore:
    sid = session_id or "default"
    if sid not in _by_session:
        _by_session[sid] = MemoryGraphStore()
    return _by_session[sid]


async def ensure_memory_graph_hydrated(session_id: str) -> MemoryGraphStore:
    """Load Redis snapshot into process store once per session."""
    sid = session_id or "default"
    store = get_memory_graph(sid)
    if sid in _hydrated:
        return store
    _hydrated.add(sid)
    try:
        from memory.fabric.memory_graph_redis import load_graph_snapshot

        snap = await load_graph_snapshot(sid)
        if snap:
            _apply_snapshot(store, snap)
    except Exception as exc:
        logger.warning("memory_graph_hydrate_failed", session_id=sid, error=str(exc))
    return store


async def persist_memory_graph(session_id: str) -> None:
    sid = session_id or "default"
    store = get_memory_graph(sid)
    try:
        from memory.fabric.memory_graph_redis import persist_graph_snapshot

        await persist_graph_snapshot(sid, store.to_dict())
    except Exception as exc:
        logger.warning("memory_graph_persist_failed", session_id=sid, error=str(exc))
        pass