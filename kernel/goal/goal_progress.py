"""Goal progress persistence — portfolio + cognitive state alignment."""

from __future__ import annotations

from typing import Any

from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
from kernel.protocol.runtime_contract import Goal, GoalGraph


def sync_goal_lifecycle_from_metadata(
    ctx: Any,
    *,
    target_state: GoalLifecycleState | None = None,
) -> dict[str, Any]:
    """Apply lifecycle transitions to root goal in ctx.metadata goal_graph."""
    md = dict(getattr(ctx, "metadata", None) or {})
    gg = md.get("goal_graph")
    if not isinstance(gg, dict):
        return {"updated": False}

    goals_raw = gg.get("goals") or []
    root_id = str(gg.get("root_goal_id") or "")
    if not root_id or not goals_raw:
        return {"updated": False}

    goals: list[Goal] = []
    for raw in goals_raw:
        if not isinstance(raw, dict):
            continue
        goals.append(
            Goal(
                goal_id=str(raw.get("goal_id", "")),
                description=str(raw.get("description", "")),
                priority=int(raw.get("priority", 0) or 0),
                parent_id=raw.get("parent_id"),
                success_criteria=str(raw.get("success_criteria", "") or ""),
                metadata=dict(raw.get("metadata") or {}),
            )
        )
    graph = GoalGraph(
        root_goal_id=root_id,
        goals=goals,
        intent_category=str(gg.get("intent_category", "general") or "general"),
        protected_intent=str(gg.get("protected_intent", "") or ""),
    )

    root_goal: Goal | None = None
    for g in graph.goals:
        if g.goal_id == root_id:
            root_goal = g
            break
    if root_goal is None and graph.goals:
        root_goal = graph.goals[0]

    if root_goal is None:
        return {"updated": False}

    inferred = target_state
    if inferred is None:
        rc = md.get("runtime_contribution_turn") or {}
        status = str(rc.get("status", "") or "")
        if status in ("error", "timeout", "failed"):
            inferred = GoalLifecycleState.FAILED
        elif md.get("policy_denied"):
            inferred = GoalLifecycleState.BLOCKED
        else:
            inferred = GoalLifecycleState.COMPLETED

    final = transition_goal_state(root_goal, inferred)
    gg_out = graph.to_dict()
    gg_out["goals"] = [
        {
            **{
                "goal_id": g.goal_id,
                "description": g.description,
                "priority": g.priority,
                "parent_id": g.parent_id,
                "success_criteria": g.success_criteria,
            },
            "metadata": dict(g.metadata or {}),
        }
        for g in graph.goals
    ]
    md["goal_graph"] = gg_out
    md["goal_progress"] = {
        "root_goal_id": root_id,
        "lifecycle_state": final.value,
        "evidence_count": len(md.get("runtime_contribution_turn", {}).get("evidence") or []),
    }
    ctx.metadata = md
    return {"updated": True, "lifecycle_state": final.value}


async def persist_goal_progress(ctx: Any) -> None:
    """Flush goal progress slice to Redis when cognitive state persist is enabled."""
    sync_goal_lifecycle_from_metadata(ctx)
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_cognitive_state_persist_enabled", False)):
            return
        from kernel.runtime.cognitive_state.persistence import flush_runtime_state
        from kernel.runtime.cognitive_state.store import get_or_create_runtime_state

        rid = str(getattr(ctx, "request_id", "") or "")
        sid = str(getattr(ctx, "session_id", "") or "")
        md = getattr(ctx, "metadata", None) or {}
        gp = md.get("goal_progress") or {}
        rs = get_or_create_runtime_state(rid, sid, goal_id=str(gp.get("root_goal_id", "")))
        rs.metrics["goal_progress"] = 1.0
        rs.world_state_snapshot["goal_progress"] = dict(gp)
        graph = md.get("cognitive_state_graph")
        if isinstance(graph, dict):
            rs.world_state_snapshot["cognitive_state_graph"] = graph
        await flush_runtime_state(rs)
    except Exception:
        pass