from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field


class TaskMessage(BaseModel):
    task_id: str
    agent_type: str
    query: str
    params: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    user_id: str | None = None


class AgentResult(BaseModel):
    task_id: str
    agent_type: str
    status: str  # success | error | timeout
    content: str
    confidence: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class BaseAgent(ABC):
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type

    @abstractmethod
    async def execute(self, task: TaskMessage) -> AgentResult:
        pass
