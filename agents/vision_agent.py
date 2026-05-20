"""Vision analysis agent stub."""

from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage


class VisionAgent(BaseAgent):
    agent_type = "vision"

    def __init__(self) -> None:
        super().__init__(agent_type=self.agent_type)

    async def execute(self, task: TaskMessage) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_type=self.agent_type,
            status="success",
            content="",
        )
