from __future__ import annotations

from agents.base import BaseAgent


class AgentRegistry:
    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.agent_type] = agent

    def get_agent(self, agent_type: str) -> BaseAgent:
        key = (agent_type or "").lower()
        if key not in self._agents:
            raise KeyError(f"agent not found: {agent_type}")
        return self._agents[key]

    def has_agent(self, agent_type: str) -> bool:
        return (agent_type or "").lower() in self._agents
