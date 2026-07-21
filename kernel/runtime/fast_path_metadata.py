"""Shared governance envelope for Tier-0 / tool fast paths (kernel + gateway)."""

from __future__ import annotations

from typing import Any

from kernel.agent_runtime.manifest import get_manifest


def build_fast_path_governance_envelope(
    *,
    route: str,
    capability_type: str,
    registry_agent: str,
    request_id: str,
    session_id: str,
    tier: str = "tier0",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    m = get_manifest()
    meta: dict[str, Any] = {
        "fast_path": True,
        "runtime_tier": tier,
        "route": route,
        "capability_type": capability_type,
        "registry_agent": registry_agent,
        "manifest_version": m.version,
        "trace_id": request_id,
        "session_id": session_id,
        "semantic_observability": {"degradations": []},
    }
    if extra:
        meta.update(extra)
    return meta