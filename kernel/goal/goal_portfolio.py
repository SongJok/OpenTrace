"""Goal Portfolio — Program → Initiative → Task hierarchy for long-running work."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from kernel.protocol.runtime_contract import Goal, GoalGraph


class PortfolioLevel(str, Enum):
    PROGRAM = "program"
    INITIATIVE = "initiative"
    TASK = "task"
    SESSION_GOAL = "session_goal"


@dataclass
class PortfolioNode:
    node_id: str
    level: PortfolioLevel
    title: str = ""
    parent_id: str = ""
    horizon: str = "session"  # session | quarter | annual
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "level": self.level.value,
            "title": self.title,
            "parent_id": self.parent_id,
            "horizon": self.horizon,
            "metadata": dict(self.metadata),
        }


@dataclass
class GoalPortfolio:
    program_id: str = ""
    nodes: list[PortfolioNode] = field(default_factory=list)

    def add(self, node: PortfolioNode) -> None:
        self.nodes.append(node)
        if node.level == PortfolioLevel.PROGRAM and not self.program_id:
            self.program_id = node.node_id

    def bind_goal_graph(self, graph: GoalGraph, *, initiative_id: str = "") -> dict[str, Any]:
        """Attach runtime GoalGraph leaves as TASK nodes under an initiative."""
        root = graph.root_goal_id
        parent = initiative_id or f"init:{root}"
        if not any(n.node_id == parent for n in self.nodes):
            self.add(
                PortfolioNode(
                    node_id=parent,
                    level=PortfolioLevel.INITIATIVE,
                    title=f"Initiative for {root}",
                    parent_id=self.program_id or f"prog:{root}",
                    horizon="quarter",
                )
            )
        if self.program_id == "":
            self.program_id = f"prog:{root}"
            self.add(
                PortfolioNode(
                    node_id=self.program_id,
                    level=PortfolioLevel.PROGRAM,
                    title="Session Program",
                    horizon="annual",
                )
            )
        for g in graph.goals:
            gid = g.goal_id
            self.add(
                PortfolioNode(
                    node_id=f"task:{gid}",
                    level=PortfolioLevel.TASK,
                    title=(g.description or gid)[:120],
                    parent_id=parent,
                    horizon="session",
                    metadata={"goal_id": gid, "lifecycle": (g.metadata or {}).get("lifecycle_state")},
                )
            )
        return self.to_dict()

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "nodes": [n.to_dict() for n in self.nodes],
        }


def goal_from_portfolio_task(node: PortfolioNode) -> Goal:
    gid = str((node.metadata or {}).get("goal_id") or node.node_id.replace("task:", ""))
    return Goal(goal_id=gid, description=node.title)