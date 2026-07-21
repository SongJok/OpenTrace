"""认知域协议 — 规划、目标、约束（不执行工具）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CognitionPhase(str, Enum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    DECOMPOSE = "decompose"
    REFLECT = "reflect"
    CONSTRAINT = "constraint"


@dataclass
class CognitionEnvelope:
    """Message envelope between cognitive modules."""

    phase: CognitionPhase
    session_id: str
    request_id: str
    payload: dict[str, Any] = field(default_factory=dict)
    version: str = "cognition_protocol_v1"


@dataclass
class PlanningArtifact:
    """Output of cognitive planning — consumed by Strategy / Runtime projection only."""

    goal_graph: dict[str, Any] = field(default_factory=dict)
    protected_intent: str = ""
    task_type: str = "general_qa"
    constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)