"""
Planner — decomposes a complex intent into a DAG of subtasks.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

PLANNER_SYSTEM = """\
You are a task planner. Decompose the user request into a list of atomic subtasks.
Each subtask has: id, description, deps (list of ids it depends on).
Respond ONLY with valid JSON array:
[
  {"id": "t1", "description": "...", "deps": []},
  {"id": "t2", "description": "...", "deps": ["t1"]}
]
"""


@dataclass
class SubTask:
    task_id: str
    description: str
    deps: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Plan:
    goal: str
    subtasks: list[SubTask]
    metadata: dict[str, Any] = field(default_factory=dict)


class Planner:
    """
    LLM-based task planner that produces a dependency DAG.
    """

    def __init__(self) -> None:
        self._gateway = get_model_gateway()

    async def create_plan(self, goal: str, context: str = "") -> Plan:
        with tracer.start_as_current_span("planner.create_plan") as span:
            span.set_attribute("goal.length", len(goal))

            messages = [
                LLMMessage(role="system", content=PLANNER_SYSTEM),
            ]
            if context:
                messages.append(
                    LLMMessage(role="user", content=f"Context:\n{context}")
                )
            messages.append(LLMMessage(role="user", content=f"Goal: {goal}"))

            resp = await self._gateway.complete(
                messages=messages,
                role=LLMRole.PLANNING,
                temperature=0.1,
                max_tokens=2048,
            )

            subtasks = self._parse_plan(resp.content)
            span.set_attribute("plan.subtasks", len(subtasks))
            logger.info("Plan created", goal=goal[:80], subtasks=len(subtasks))

            return Plan(goal=goal, subtasks=subtasks)

    def _parse_plan(self, text: str) -> list[SubTask]:
        import re
        # Extract JSON array from response
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            # Fallback: single task
            return [SubTask(task_id="t1", description=text.strip()[:200])]
        try:
            raw = json.loads(match.group(0))
            return [
                SubTask(
                    task_id=item.get("id", f"t{i}"),
                    description=item.get("description", ""),
                    deps=item.get("deps", []),
                )
                for i, item in enumerate(raw)
            ]
        except json.JSONDecodeError:
            return [SubTask(task_id="t1", description=text.strip()[:200])]
