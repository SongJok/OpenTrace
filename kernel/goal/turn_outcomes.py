"""Shared turn-close: goal lifecycle, evolution, memory fabric (all Tier-1 runtimes)."""

from __future__ import annotations

from typing import Any


def apply_turn_goal_and_memory_outcomes(
    *,
    request: Any,
    ctx: Any | None,
    answer: str,
    route: str,
    critic_passed: bool | None,
    artifact_id: str = "",
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """
    Finalize GoalGraph, evolve goals, bind memory fabric.
    Returns dict suitable for merging into KernelResponse.metadata.
    """
    out: dict[str, Any] = {}
    gg_raw = (request.metadata or {}).get("goal_graph")
    if not isinstance(gg_raw, dict) or not gg_raw.get("goals"):
        return out

    try:
        from kernel.goal.goal_evolution import evolve_goals_after_execution
        from kernel.goal.goal_lifecycle import finalize_turn_goal_lifecycle
        from kernel.protocol.runtime_contract import Goal, GoalGraph

        goals = [
            Goal(
                goal_id=g["goal_id"],
                description=g.get("description", ""),
                priority=int(g.get("priority", 0)),
                parent_id=g.get("parent_id"),
                metadata=dict(g.get("metadata") or {}),
            )
            for g in gg_raw["goals"]
            if isinstance(g, dict)
        ]
        graph = GoalGraph(
            root_goal_id=gg_raw.get("root_goal_id", ""),
            goals=goals,
            intent_category=gg_raw.get("intent_category", "general"),
        )
        lc = finalize_turn_goal_lifecycle(
            graph,
            critic_passed=critic_passed,
            policy_denied=bool((getattr(ctx, "metadata", None) or {}).get("policy_denied")),
        )
        out["goal_lifecycle"] = lc
        out["goal_graph"] = lc.get("goal_graph") or gg_raw
        request.metadata["goal_graph"] = out["goal_graph"]

        out["goal_evolution"] = evolve_goals_after_execution(
            graph,
            request_id=str((request.metadata or {}).get("request_id", "")),
            session_id=getattr(request, "session_id", ""),
            artifact_id=artifact_id,
            evidence_ids=list(evidence_ids or []),
        )
    except Exception:
        pass

    try:
        from kernel.goal.goal_memory_binding import bind_goal_turn_to_memory_fabric

        gg = out.get("goal_graph") or gg_raw
        root = str(gg.get("root_goal_id", "") or (request.metadata or {}).get("request_id", ""))
        bind_goal_turn_to_memory_fabric(
            session_id=getattr(request, "session_id", ""),
            request_id=str((request.metadata or {}).get("request_id", "")),
            goal_id=root,
            query_preview=(getattr(request, "query", "") or "")[:120],
            answer_preview=(answer or "")[:500],
            route=route,
        )
    except Exception:
        pass

    try:
        fm = str((request.metadata or {}).get("force_mode") or "")
        if fm in ("data_query", "data_analysis") or "data" in route:
            from services.data_intelligence_runtime import enrich_data_turn_outcomes

            md = getattr(ctx, "metadata", None) or {} if ctx else {}
            out.update(
                enrich_data_turn_outcomes(
                    query=getattr(request, "query", "") or "",
                    sql=str(md.get("executed_sql") or ""),
                    row_count=int(md.get("row_count") or 0),
                    metric_names=list(md.get("metric_names") or []),
                )
            )
    except Exception:
        pass

    try:
        fabric = ((getattr(ctx, "metadata", None) or {}) if ctx else {}).get("fabric_graph_live") or {}
        nodes = fabric.get("nodes") if isinstance(fabric, dict) else []
        if isinstance(nodes, list) and len(nodes) > 64:
            from memory.fabric.memory_compression import plan_memory_maintenance

            mems = [
                {"id": n.get("id"), "confidence": n.get("confidence", 0.5)}
                for n in nodes
                if isinstance(n, dict)
            ]
            plan = plan_memory_maintenance(mems)
            out["memory_maintenance_plan"] = plan.to_dict()
            if plan.summarize or plan.archive_ids or plan.forget_ids:
                try:
                    import asyncio

                    from memory.fabric.tms_bridge import run_session_memory_maintenance

                    async def _tms() -> dict[str, Any]:
                        return await run_session_memory_maintenance(mems)

                    try:
                        loop = asyncio.get_running_loop()
                        # Schedule; merge hint synchronously from plan only
                        loop.create_task(_tms())
                        out["memory_tms_scheduled"] = True
                    except RuntimeError:
                        out["memory_tms"] = asyncio.run(_tms())
                except Exception:
                    pass
    except Exception:
        pass

    return out