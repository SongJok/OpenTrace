"""Post-execution bindings for multi-goal runs."""

from __future__ import annotations

from typing import Any

from kernel.goal.goal_evidence_binding import extract_evidence_ids, stamp_evidence_goal_ids
from kernel.goal.state_machine import GoalLifecycleState, transition_goal_state
from kernel.protocol.runtime_contract import Goal, GoalGraph


def build_sub_goal_bindings(
    execution_graph: list[Any],
    sub_questions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Map each sub-goal to execution node ids."""
    by_sq: dict[str, dict[str, Any]] = {}
    for sq in sub_questions:
        sq_id = str(sq.get("id") or sq.get("sub_question_id") or "")
        gid = str(sq.get("goal_id") or "")
        if sq_id or gid:
            by_sq[sq_id or gid] = {
                "sub_question_id": sq_id,
                "goal_id": gid,
                "node_ids": [],
                "text_preview": (sq.get("text") or "")[:80],
            }

    for node in execution_graph or []:
        params = getattr(node, "params", None) or {}
        sq_id = str(params.get("sub_question_id") or "")
        gid = str(getattr(node, "goal_id", "") or params.get("goal_id") or "")
        nid = str(getattr(node, "node_id", "") or "")
        key = sq_id or gid
        if key not in by_sq and gid:
            by_sq[gid] = {
                "sub_question_id": sq_id,
                "goal_id": gid,
                "node_ids": [],
                "text_preview": "",
            }
            key = gid
        if key in by_sq and nid:
            by_sq[key]["node_ids"].append(nid)
            if gid and not by_sq[key].get("goal_id"):
                by_sq[key]["goal_id"] = gid

    return list(by_sq.values())


def evolve_sub_goals_after_multi_execution(
    goal_graph: GoalGraph | None,
    *,
    session_id: str,
    request_id: str,
    execution_graph: list[Any],
    agent_results: list[Any],
    sub_goal_bindings: list[dict[str, Any]],
) -> dict[str, Any]:
    """Per sub-goal lifecycle + memory/evidence hooks."""
    if not goal_graph:
        return {"sub_goals": []}

    root_id = goal_graph.root_goal_id
    children = {
        g.goal_id: g
        for g in goal_graph.goals
        if g.parent_id == root_id and g.goal_id != root_id
    }
    outcomes: list[dict[str, Any]] = []

    # Group results by sub_question_id / goal_id from graph nodes
    results_by_goal: dict[str, list[Any]] = {}
    for i, node in enumerate(execution_graph or []):
        params = getattr(node, "params", None) or {}
        gid = str(getattr(node, "goal_id", "") or params.get("goal_id") or "")
        if not gid:
            continue
        res = agent_results[i] if i < len(agent_results) else None
        if res is not None:
            results_by_goal.setdefault(gid, []).append(res)

    for binding in sub_goal_bindings:
        gid = str(binding.get("goal_id") or "")
        goal = children.get(gid)
        if goal:
            ok = all(
                getattr(r, "status", "") != "error"
                for r in results_by_goal.get(gid, [])
            ) if results_by_goal.get(gid) else True
            transition_goal_state(
                goal,
                GoalLifecycleState.COMPLETED if ok else GoalLifecycleState.FAILED,
            )
        evidence_objs: list[Any] = []
        for r in results_by_goal.get(gid, []):
            if hasattr(r, "evidence_objects") and r.evidence_objects:
                evidence_objs.extend(r.evidence_objects)
        stamp_evidence_goal_ids(
            evidence_objs, root_goal_id=gid or root_id, request_id=request_id
        )
        eids = extract_evidence_ids(evidence_objs)
        try:
            from kernel.goal.goal_memory_binding import bind_goal_turn_to_memory_fabric

            bind_goal_turn_to_memory_fabric(
                session_id=session_id,
                request_id=f"{request_id}:{gid or 'sub'}",
                goal_id=gid or root_id,
                route="multi_question_runtime_v2",
            )
        except Exception:
            pass
        try:
            from memory.fabric.router_singleton import get_memory_fabric_router

            router = get_memory_fabric_router()
            for eid in eids:
                router.bind(
                    f"{session_id}:{request_id}:ev:{eid}",
                    goal_id=gid or root_id,
                    evidence_id=eid,
                    salience=0.65,
                    metadata={"session_id": session_id},
                )
        except Exception:
            pass
        outcomes.append(
            {
                "goal_id": gid,
                "node_ids": list(binding.get("node_ids") or []),
                "evidence_ids": eids,
                "lifecycle": (goal.metadata or {}).get("lifecycle_state") if goal else "",
            }
        )

    try:
        from kernel.goal.state_machine import transition_goal_state

        root = next((g for g in goal_graph.goals if g.goal_id == root_id), None)
        if root:
            all_ok = all(o.get("lifecycle") == GoalLifecycleState.COMPLETED.value for o in outcomes)
            transition_goal_state(
                root,
                GoalLifecycleState.COMPLETED if all_ok and outcomes else GoalLifecycleState.FUSED,
            )
    except Exception:
        pass

    return {"root_goal_id": root_id, "sub_goals": outcomes}