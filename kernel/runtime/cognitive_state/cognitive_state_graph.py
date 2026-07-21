"""CognitiveStateGraph — unified evolution chain Goal → Evidence → Memory → World."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from kernel.agent_runtime.runtime_contribution import RuntimeContribution

NodeKind = Literal["goal", "evidence", "memory", "world"]


class CognitiveStateNode(BaseModel):
    node_id: str
    kind: NodeKind
    ref_id: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5
    edges_out: list[str] = Field(default_factory=list)


class CognitiveStateGraph(BaseModel):
    """Session/request scoped graph driving cognitive runtime state."""

    version: str = "cognitive_state_graph_v1"
    session_id: str = ""
    request_id: str = ""
    root_goal_id: str = ""
    nodes: dict[str, CognitiveStateNode] = Field(default_factory=dict)
    evolution_chain: list[str] = Field(default_factory=list)  # ordered node_ids

    def add_node(self, node: CognitiveStateNode) -> None:
        self.nodes[node.node_id] = node
        if node.node_id not in self.evolution_chain:
            self.evolution_chain.append(node.node_id)

    def link(self, from_id: str, to_id: str) -> None:
        if from_id in self.nodes and to_id in self.nodes:
            outs = self.nodes[from_id].edges_out
            if to_id not in outs:
                outs.append(to_id)

    def to_metadata_dict(self) -> dict[str, Any]:
        return {"cognitive_state_graph": self.model_dump(mode="json")}

    @classmethod
    def from_metadata(cls, md: dict[str, Any] | None) -> CognitiveStateGraph | None:
        raw = (md or {}).get("cognitive_state_graph")
        if not isinstance(raw, dict):
            return None
        try:
            return cls.model_validate(raw)
        except Exception:
            return None


def apply_contribution_to_graph(
    graph: CognitiveStateGraph,
    contribution: RuntimeContribution,
    *,
    phase: str = "executing",
) -> CognitiveStateGraph:
    """Append contribution into Goal → Evidence → Memory → World chain."""
    gid = graph.root_goal_id or contribution.task_id
    goal_node_id = f"goal:{gid}"
    if goal_node_id not in graph.nodes:
        graph.add_node(
            CognitiveStateNode(
                node_id=goal_node_id,
                kind="goal",
                ref_id=gid,
                payload={"phase": phase},
                confidence=contribution.confidence,
            )
        )

    prev = goal_node_id
    for i, ev in enumerate(contribution.evidence):
        nid = f"evidence:{ev.evidence_id or i}"
        graph.add_node(
            CognitiveStateNode(
                node_id=nid,
                kind="evidence",
                ref_id=ev.evidence_id,
                payload={"capability_type": contribution.capability_type},
                confidence=ev.confidence,
            )
        )
        graph.link(prev, nid)
        prev = nid

    for j, mem in enumerate(contribution.memory_updates):
        nid = f"memory:{gid}:{j}"
        graph.add_node(
            CognitiveStateNode(
                node_id=nid,
                kind="memory",
                ref_id=",".join(mem.memory_keys[:8]),
                payload={
                    "should_persist": mem.should_persist,
                    "salience": mem.salience,
                },
                confidence=mem.salience,
            )
        )
        graph.link(prev, nid)
        prev = nid

    for k, world in enumerate(contribution.world_updates):
        nid = f"world:{graph.session_id}:{k}"
        graph.add_node(
            CognitiveStateNode(
                node_id=nid,
                kind="world",
                ref_id=world.projection_hint or "current",
                payload=dict(world.variable_updates),
                confidence=0.6,
            )
        )
        graph.link(prev, nid)
        prev = nid

    return graph


def graph_from_context(ctx: Any) -> CognitiveStateGraph:
    md = dict(getattr(ctx, "metadata", None) or {})
    existing = CognitiveStateGraph.from_metadata(md)
    sid = str(getattr(ctx, "session_id", "") or "")
    rid = str(getattr(ctx, "request_id", "") or "")
    gg = md.get("goal_graph") or {}
    root = str(gg.get("root_goal_id") or md.get("goal_id") or rid)
    if existing:
        existing.session_id = existing.session_id or sid
        existing.request_id = existing.request_id or rid
        existing.root_goal_id = existing.root_goal_id or root
        return existing
    return CognitiveStateGraph(session_id=sid, request_id=rid, root_goal_id=root)


def persist_graph_on_context(ctx: Any, graph: CognitiveStateGraph) -> None:
    md = dict(getattr(ctx, "metadata", None) or {})
    md.update(graph.to_metadata_dict())
    crs = md.get("cognitive_runtime_state") or {}
    if isinstance(crs, dict):
        crs["cognitive_state_graph_version"] = graph.version
        crs["evidence_ids"] = [
            n.ref_id
            for n in graph.nodes.values()
            if n.kind == "evidence" and n.ref_id
        ]
        md["cognitive_runtime_state"] = crs
    ctx.metadata = md