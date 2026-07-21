"""动态上下文图节点（每回合 goal / runtime / memory 关联）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextFabricNode:
    node_id: str
    node_type: str  # goal | memory | evidence | user_state | runtime
    content_ref: str = ""
    salience: float = 0.5
    edges: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextFabricGraph:
    def __init__(self) -> None:
        self._nodes: dict[str, ContextFabricNode] = {}

    def upsert(self, node: ContextFabricNode) -> None:
        self._nodes[node.node_id] = node

    def link(self, from_id: str, to_id: str) -> None:
        if from_id in self._nodes and to_id not in self._nodes[from_id].edges:
            self._nodes[from_id].edges.append(to_id)

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "node_id": n.node_id,
                    "node_type": n.node_type,
                    "content_ref": n.content_ref,
                    "salience": n.salience,
                    "edges": list(n.edges),
                    "metadata": dict(n.metadata),
                }
                for n in self._nodes.values()
            ]
        }


def build_fabric_graph_from_turn(turn_context: Any, goal_projection: dict[str, Any] | None) -> ContextFabricGraph:
    g = ContextFabricGraph()
    sid = str(getattr(turn_context, "session_id", "") or "")
    rid = str((getattr(turn_context, "metadata", None) or {}).get("request_id", sid))
    root = (goal_projection or {}).get("root_goal_id", rid)
    g.upsert(
        ContextFabricNode(
            node_id=f"goal:{root}",
            node_type="goal",
            content_ref=root,
            salience=1.0,
            metadata={"intent": (goal_projection or {}).get("intent_category", "")},
        )
    )
    g.upsert(
        ContextFabricNode(
            node_id=f"user:{sid}",
            node_type="user_state",
            content_ref=sid,
            salience=0.7,
        )
    )
    g.link(f"goal:{root}", f"user:{sid}")
    for i, mc in enumerate(getattr(turn_context, "memory_context", None) or []):
        if isinstance(mc, dict) and mc.get("content"):
            nid = f"mem:{rid}:{i}"
            g.upsert(
                ContextFabricNode(
                    node_id=nid,
                    node_type="memory",
                    content_ref=mc.get("content", "")[:80],
                    salience=float(mc.get("score", 0.5) or 0.5),
                )
            )
            g.link(f"goal:{root}", nid)
    return g