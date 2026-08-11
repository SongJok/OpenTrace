"""CapabilityRegistry routing must align with agent_topology_manifest.yaml."""

from __future__ import annotations

from agents.bootstrap import register_builtin_agents
from kernel.agent_runtime.manifest import get_manifest, reload_manifest
from kernel.runtime.capability import capability_registry


def test_registry_resolve_matches_manifest_for_tier1_bootstrap():
    reload_manifest()
    register_builtin_agents(force=True)
    m = get_manifest()
    for agent_type in m.bootstrap_agent_types:
        ent = m.get(agent_type)
        assert ent is not None
        resolved_ct = capability_registry.resolve_capability_type(agent_type)
        assert resolved_ct == ent.capability_type, agent_type
        exec_agent = capability_registry.resolve_execution_agent(ent.capability_type)
        assert capability_registry.has_agent(exec_agent), f"{ent.capability_type} -> {exec_agent}"


def test_removed_web_alias_is_not_registered_as_an_execution_agent():
    reload_manifest()
    register_builtin_agents(force=True)
    assert not capability_registry.has_agent("web_intelligence")
    assert not capability_registry.has_agent("web")
