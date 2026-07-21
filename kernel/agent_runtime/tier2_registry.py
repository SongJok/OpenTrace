"""Tier-2 node registry — Data V2 DAG agents (not CapabilityRegistry tier-1)."""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent
from kernel.agent_runtime.manifest import get_manifest

_tier2_classes: dict[str, type[BaseAgent]] = {}
_initialized = False


def register_tier2_class(agent_type: str, cls: type[BaseAgent]) -> None:
    key = (agent_type or "").lower()
    _tier2_classes[key] = cls
    manifest = get_manifest()
    if not manifest.get(key):
        raise ValueError(f"tier2 agent {key} missing from agent_topology_manifest.yaml")


def get_tier2_agent(agent_type: str) -> BaseAgent:
    _ensure_initialized()
    key = (agent_type or "").lower()
    cls = _tier2_classes.get(key)
    if cls is None:
        raise KeyError(f"tier2 agent not found: {agent_type}")
    return cls()


def has_tier2_agent(agent_type: str) -> bool:
    _ensure_initialized()
    return (agent_type or "").lower() in _tier2_classes


def list_tier2_agent_types() -> list[str]:
    _ensure_initialized()
    return sorted(_tier2_classes.keys())


def _ensure_initialized() -> None:
    global _initialized
    if _initialized:
        return
    _register_data_v2_nodes()
    _initialized = True


def _register_data_v2_nodes() -> None:
    from agents.data_agent_v2.entity_agent import EntityAgent
    from agents.data_agent_v2.intent_agent import IntentAgent
    from agents.data_agent_v2.join_agent import JoinAgent
    from agents.data_agent_v2.knowledge_retriever import KnowledgeRetrieverAgent
    from agents.data_agent_v2.metric_agent import MetricAgent
    from agents.data_agent_v2.planner_agent import PlannerAgent
    from agents.data_agent_v2.business_semantic_agent import BusinessSemanticAgent
    from agents.data_agent_v2.semantic_agent import SemanticAgent
    from agents.data_agent_v2.sql_compiler_agent import SQLCompilerAgent
    from agents.data_agent_v2.time_reasoning_agent import TimeReasoningAgent
    from agents.data_agent_v2.verification_agent import VerificationAgent

    mapping: dict[str, type[BaseAgent]] = {
        "data_knowledge": KnowledgeRetrieverAgent,
        "data_intent": IntentAgent,
        "data_entity": EntityAgent,
        "data_metric": MetricAgent,
        "data_time": TimeReasoningAgent,
        "data_join": JoinAgent,
        "data_semantic": SemanticAgent,
        "data_business_semantic": BusinessSemanticAgent,
        "data_planner": PlannerAgent,
        "data_compiler": SQLCompilerAgent,
        "data_verification": VerificationAgent,
    }
    manifest = get_manifest()
    for key, cls in mapping.items():
        if manifest.get(key):
            _tier2_classes[key] = cls


class Tier2AgentRegistry:
    """Explicit tier-2 executor registry (replaces agents.registry bridge for V2)."""

    def get_agent(self, agent_type: str) -> BaseAgent:
        return get_tier2_agent(agent_type)

    def has_agent(self, agent_type: str) -> bool:
        return has_tier2_agent(agent_type)


tier2_registry = Tier2AgentRegistry()