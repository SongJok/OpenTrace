from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DagNode:
    node_id: str
    agent_type: str
    query: str
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)


@dataclass
class DagPlan:
    nodes: list[DagNode] = field(default_factory=list)
    speculative_execution: bool = False
