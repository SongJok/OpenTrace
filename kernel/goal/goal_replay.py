"""目标维度的回放快照，用于确定性追踪对齐。"""

from __future__ import annotations

from typing import Any


def snapshot_goal_for_replay(ctx: Any) -> dict[str, Any]:
    md = getattr(ctx, "metadata", None) or {}
    return {
        "goal_graph": md.get("goal_graph"),
        "goal_world_projection": md.get("goal_world_projection"),
        "cognitive_runtime_state": md.get("cognitive_runtime_state"),
        "capability_governance": md.get("capability_governance"),
    }