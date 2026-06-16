"""Cognitive Agent loop — perception → reasoning → planning → execution → reflection → learning."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage


@dataclass
class CognitivePhaseTrace:
    perception: dict[str, Any] = field(default_factory=dict)
    reasoning: dict[str, Any] = field(default_factory=dict)
    planning: dict[str, Any] = field(default_factory=dict)
    execution: dict[str, Any] = field(default_factory=dict)
    reflection: dict[str, Any] = field(default_factory=dict)
    learning: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "perception": dict(self.perception),
            "reasoning": dict(self.reasoning),
            "planning": dict(self.planning),
            "execution": dict(self.execution),
            "reflection": dict(self.reflection),
            "learning": dict(self.learning),
        }


class CognitiveAgent(BaseAgent, ABC):
    """Enterprise agent contract beyond request→execute→result."""

    async def perception(self, task: TaskMessage) -> dict[str, Any]:
        return {"query": task.query, "params": dict(task.params or {})}

    async def reasoning(self, task: TaskMessage, perception: dict[str, Any]) -> dict[str, Any]:
        return {"hypothesis": perception.get("query", "")[:200], "confidence": 0.6}

    async def planning(self, task: TaskMessage, reasoning: dict[str, Any]) -> dict[str, Any]:
        return {"steps": ["execute_core"], "reasoning_confidence": reasoning.get("confidence", 0.5)}

    async def reflection(
        self, task: TaskMessage, result: AgentResult, trace: CognitivePhaseTrace
    ) -> dict[str, Any]:
        ok = result.status == "success"
        return {"passed": ok, "adjust_confidence": result.confidence if ok else 0.2}

    async def learning(
        self,
        task: TaskMessage,
        result: AgentResult,
        reflection: dict[str, Any],
    ) -> dict[str, Any]:
        hints: dict[str, Any] = {
            "memory_hints": [],
            "skill_updates": [],
            "confidence_delta": 0.05 if reflection.get("passed") else -0.1,
            "learning_hook": "cognitive_agent_default",
        }
        try:
            from kernel.agent_runtime.learning_hook import record_agent_learning_signal

            hints["runtime_learning"] = await record_agent_learning_signal(
                agent_type=self.agent_type,
                task_id=task.task_id,
                session_id=str(task.session_id or ""),
                passed=bool(reflection.get("passed")),
                confidence=float(result.confidence or 0.0),
            )
        except Exception:
            hints["runtime_learning"] = {"skipped": True}
        return hints

    @abstractmethod
    async def execute_core(self, task: TaskMessage, plan: dict[str, Any]) -> AgentResult:
        pass

    async def execute(self, task: TaskMessage) -> AgentResult:
        trace = CognitivePhaseTrace()
        trace.perception = await self.perception(task)
        trace.reasoning = await self.reasoning(task, trace.perception)
        trace.planning = await self.planning(task, trace.reasoning)
        result = await self.execute_core(task, trace.planning)
        trace.execution = {
            "status": result.status,
            "confidence": result.confidence,
        }
        trace.reflection = await self.reflection(task, result, trace)
        trace.learning = await self.learning(task, result, trace.reflection)
        result.agent_trace = trace.to_dict()
        result.metadata = dict(result.metadata or {})
        result.metadata["cognitive_agent"] = True
        return result


class PassthroughCognitiveAgent(CognitiveAgent):
    """Wraps a simple handler for tests and gradual migration."""

    def __init__(self, agent_type: str, handler: Any = None) -> None:
        super().__init__(agent_type)
        self._handler = handler

    async def execute_core(self, task: TaskMessage, plan: dict[str, Any]) -> AgentResult:
        content = f"[{self.agent_type}] {task.query}"
        if self._handler:
            content = str(await self._handler(task, plan))
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content=content,
            confidence=float(plan.get("reasoning_confidence", 0.6)),
        )