"""Capability registry execution agent resolution."""

from __future__ import annotations

from agents.bootstrap import register_builtin_agents
from kernel.runtime.capability import capability_registry


def test_web_routes_to_web_intelligence_when_registered():
    register_builtin_agents(force=True)
    assert capability_registry.has_agent("web_intelligence")
    assert capability_registry.resolve_execution_agent("web") == "web_intelligence"
    assert capability_registry.resolve_capability_type("web") == "web_search"
    assert capability_registry.resolve_capability_type("web_intelligence") == "web_search"