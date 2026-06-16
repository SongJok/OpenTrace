"""Data V2 cognitive DAG must align with agent_topology_manifest tier-2 keys."""

from __future__ import annotations

from agents.data_agent_v2.dag_builder import (
    build_cognitive_dag,
    get_enabled_agents,
    validate_dag_against_manifest,
    validate_dag_spec,
)
from kernel.agent_runtime.manifest import reload_manifest


def test_default_cognitive_dag_validates_against_manifest():
    reload_manifest()
    enabled = get_enabled_agents()
    spec = build_cognitive_dag("各渠道销售额", enabled=enabled, parallel=True)
    assert validate_dag_spec(spec) == []
    assert validate_dag_against_manifest(spec) == []


def test_semantic_deps_match_manifest_topology():
    reload_manifest()
    enabled = {k: False for k in get_enabled_agents()}
    enabled["intent"] = True
    enabled["entity"] = True
    enabled["semantic"] = True
    spec = build_cognitive_dag("test", enabled=enabled, parallel=False)
    assert validate_dag_against_manifest(spec) == []