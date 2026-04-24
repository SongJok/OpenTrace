"""任务模型：维护假设、事实与待解问题。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from kernel.cognition.types import Hypothesis


@dataclass
class TaskState:
    hypotheses: list[Hypothesis] = field(default_factory=list)
    confirmed_facts: dict[str, Any] = field(default_factory=dict)
    open_questions: list[str] = field(default_factory=list)
    last_updated_at: datetime = field(default_factory=datetime.now)


class TaskModel:
    def __init__(self) -> None:
        self.state = TaskState()

    def init_from_query(self, query: str) -> None:
        self.state.open_questions = [query]
        self.state.last_updated_at = datetime.now()

    def add_hypothesis(self, statement: str, confidence: float = 0.6, source: str = "inference") -> None:
        hid = f"h_{len(self.state.hypotheses)+1}"
        self.state.hypotheses.append(
            Hypothesis(id=hid, statement=statement, confidence=confidence, source=source)
        )
        self.state.last_updated_at = datetime.now()

    def update_from_agent_result(self, agent_result: dict[str, Any]) -> None:
        key = str(agent_result.get("task_id") or f"fact_{len(self.state.confirmed_facts)+1}")
        self.state.confirmed_facts[key] = {
            "agent_type": agent_result.get("agent_type"),
            "status": agent_result.get("status"),
            "content": str(agent_result.get("content", ""))[:500],
        }
        self.state.last_updated_at = datetime.now()
