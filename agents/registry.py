"""
AgentRegistry — 已弃用，对 CapabilityRegistry 的薄封装。

注册与查找均经 kernel.runtime.capability.CapabilityRegistry；
本模块仅为直接 import AgentRegistry 的旧调用方保留兼容。
"""

from __future__ import annotations

from agents.base import BaseAgent
from kernel.runtime.capability import capability_registry


class AgentRegistry:
    """Deprecated — resolves tier-1 via CapabilityRegistry, tier-2 via tier2_registry."""

    def __init__(self) -> None:
        self._agents: dict[str, BaseAgent] = {}

    def register(self, agent: BaseAgent) -> None:
        self._agents[agent.agent_type] = agent
        capability_registry.register_agent(agent)

    def get_agent(self, agent_type: str) -> BaseAgent:
        key = (agent_type or "").lower()
        if key in self._agents:
            return self._agents[key]
        if capability_registry.has_agent(key):
            return capability_registry.get_agent(key)
        try:
            from kernel.agent_runtime.tier2_registry import tier2_registry

            if tier2_registry.has_agent(key):
                return tier2_registry.get_agent(key)
        except Exception:
            pass
        raise KeyError(f"agent not found: {agent_type}")

    def has_agent(self, agent_type: str) -> bool:
        key = (agent_type or "").lower()
        if key in self._agents:
            return True
        if capability_registry.has_agent(key):
            return True
        try:
            from kernel.agent_runtime.tier2_registry import tier2_registry

            return tier2_registry.has_agent(key)
        except Exception:
            return False
