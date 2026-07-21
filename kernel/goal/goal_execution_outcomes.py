"""Record per-node execution outcomes keyed by goal_id."""

from __future__ import annotations

from typing import Any


def record_goal_execution_outcomes(
    ctx: Any,
    execution_graph: list[Any] | None,
    agent_results: list[Any],
) -> dict[str, Any]:
    """Map each ExecutionNode goal_id to agent result status for replay/audit."""
    if not execution_graph:
        return {}

    outcomes: dict[str, list[dict[str, Any]]] = {}
    for i, node in enumerate(execution_graph):
        params = getattr(node, "params", None) or {}
        gid = str(getattr(node, "goal_id", "") or params.get("goal_id") or "")
        if not gid:
            continue
        res = agent_results[i] if i < len(agent_results) else None
        entry = {
            "node_id": str(getattr(node, "node_id", "") or ""),
            "capability": str(
                getattr(node, "capability_name", "")
                or getattr(node, "capability_type", "")
                or ""
            ),
            "status": str(getattr(res, "status", "unknown") if res else "missing"),
            "error": str(getattr(res, "error", "") or "")[:200] if res else "",
        }
        outcomes.setdefault(gid, []).append(entry)

    ctx.metadata = ctx.metadata or {}
    ctx.metadata["goal_execution_outcomes"] = outcomes
    return outcomes