"""Merge Agent Runtime V3 fields into chat stream / final_answer metadata."""

from __future__ import annotations

from typing import Any

_V3_STREAM_KEYS = (
    "agent_runtime_v3",
    "goal_participation",
    "goal_participation_version",
    "cognitive_runtime_p3",
    "cognitive_state_graph",
    "cognitive_runtime_state",
    "world_projection",
    "world_projection_version",
    "data_intelligence",
    "data_intelligence_turn",
    "route",
)


def merge_agent_runtime_v3_into_metadata(
    target: dict[str, Any],
    *,
    ctx: Any | None = None,
    result_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Copy V3 keys from ctx.metadata and executive result metadata."""
    sources: list[dict[str, Any]] = []
    if ctx is not None:
        md = getattr(ctx, "metadata", None) or {}
        if isinstance(md, dict):
            sources.append(md)
    if result_metadata:
        sources.append(dict(result_metadata))
    for src in sources:
        for key in _V3_STREAM_KEYS:
            if key in src and src[key] is not None:
                target[key] = src[key]
    if target.get("goal_participation") and not target.get("agent_runtime_v3"):
        target["agent_runtime_v3"] = True
    return target