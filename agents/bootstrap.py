"""Register built-in agents on the API process CapabilityRegistry.

Agent Worker registers the same set for Redis bus execution; the cognitive
runtime also invokes agents in-process via capability_registry.get_agent().

Tier-1 agent list is defined in kernel/agent_runtime/agent_topology_manifest.yaml.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from infra.observability.logger import get_logger

logger = get_logger(__name__)

_bootstrapped = False


class BuiltinAgent(Protocol):
    agent_type: str


_BUILTIN_FACTORIES: dict[str, Callable[[], BuiltinAgent]] = {}

_PROFILE_AGENT_TYPES: dict[str, frozenset[str]] = {
    "core": frozenset(),
    "data": frozenset({"data"}),
    "knowledge": frozenset({"rag"}),
    "data_knowledge": frozenset({"data", "rag"}),
}


def agent_types_for_profile(profile: str) -> frozenset[str]:
    """返回受支持 Profile 的确定性 Agent 集合。"""
    return _PROFILE_AGENT_TYPES.get(profile, frozenset())


def is_builtin_agent_enabled(agent_type: str) -> bool:
    """统一解释全局及分 Agent 开关，供 Responses 与 Worker 共用。"""
    from infra.config.settings import settings

    if not bool(getattr(settings, "kernel_agent_enabled", True)):
        return False
    profile = str(getattr(settings, "capability_profile", "data_knowledge"))
    if agent_type not in agent_types_for_profile(profile):
        return False
    setting_name = {
        "data": "kernel_agent_data_enabled",
        "rag": "kernel_agent_rag_enabled",
        "web_intelligence": "kernel_agent_web_enabled",
        "tool": "kernel_agent_tool_enabled",
        "vision": "kernel_agent_vision_enabled",
    }.get(agent_type)
    return setting_name is None or bool(getattr(settings, setting_name, True))


def _load_factories() -> dict[str, Callable[[], BuiltinAgent]]:
    if _BUILTIN_FACTORIES:
        return _BUILTIN_FACTORIES
    from agents.data_agent import DataAgent
    from agents.rag_agent import RagAgent

    _BUILTIN_FACTORIES.update(
        {
            "data": DataAgent,
            "rag": RagAgent,
        }
    )
    return _BUILTIN_FACTORIES


def expected_builtin_agent_types() -> tuple[str, ...]:
    from kernel.agent_runtime.manifest import get_manifest

    return get_manifest().bootstrap_agent_types


def instantiate_builtin_agents() -> dict[str, BuiltinAgent]:
    """Create tier-1 agent instances keyed by agent_type (manifest-driven)."""
    from kernel.agent_runtime.manifest import get_manifest

    manifest = get_manifest()
    factories = _load_factories()
    agents: dict[str, BuiltinAgent] = {}
    for agent_type in manifest.bootstrap_agent_types:
        if not is_builtin_agent_enabled(agent_type):
            continue
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
