"""Register built-in agents on the API process CapabilityRegistry.

Agent Worker registers the same set for Redis bus execution; the cognitive
runtime also invokes agents in-process via capability_registry.get_agent().

Tier-1 agent list is defined in kernel/agent_runtime/agent_topology_manifest.yaml.
"""

from __future__ import annotations

from typing import Callable

from infra.observability.logger import get_logger

logger = get_logger(__name__)

_bootstrapped = False

_BUILTIN_FACTORIES: dict[str, Callable[[], object]] = {}


def _load_factories() -> dict[str, Callable[[], object]]:
    if _BUILTIN_FACTORIES:
        return _BUILTIN_FACTORIES
    from agents.data_agent import DataAgent
    from agents.rag_agent import RagAgent
    from agents.rule_engine_agent import RuleEngineAgent
    from agents.skills_agent import SkillsAgent
    from agents.tool_agent import ToolAgent
    from agents.vision_agent import VisionAgent
    from agents.web_intelligence_agent import WebIntelligenceAgent

    _BUILTIN_FACTORIES.update(
        {
            "data": DataAgent,
            "rag": RagAgent,
            "web_intelligence": WebIntelligenceAgent,
            "tool": ToolAgent,
            "vision": VisionAgent,
            "skills": SkillsAgent,
            "rules": RuleEngineAgent,
        }
    )
    return _BUILTIN_FACTORIES


def expected_builtin_agent_types() -> tuple[str, ...]:
    from kernel.agent_runtime.manifest import get_manifest

    return get_manifest().bootstrap_agent_types


def instantiate_builtin_agents() -> dict[str, object]:
    """Create tier-1 agent instances keyed by agent_type (manifest-driven)."""
    from kernel.agent_runtime.manifest import get_manifest

    manifest = get_manifest()
    factories = _load_factories()
    agents: dict[str, object] = {}
    for agent_type in manifest.bootstrap_agent_types:
        factory = factories.get(agent_type)
        if factory is None:
            raise RuntimeError(f"missing builtin factory for manifest agent: {agent_type}")
        agent = factory()
        agents[agent.agent_type] = agent
    return agents


def register_builtin_agents(*, force: bool = False) -> None:
    global _bootstrapped
    if _bootstrapped and not force:
        return

    from kernel.agent_runtime.sync import sync_manifest_to_runtime
    from kernel.runtime.capability import capability_registry

    sync_manifest_to_runtime()

    for agent in instantiate_builtin_agents().values():
        if capability_registry.has_agent(agent.agent_type):
            continue
        capability_registry.register_agent(agent)
        logger.info("builtin agent registered", agent_type=agent.agent_type)

    _bootstrapped = True