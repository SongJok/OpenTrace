"""Attach control plane, world state, and enterprise telemetry to turn metadata."""

from __future__ import annotations

from typing import Any


def enrich_turn_enterprise_metadata(
    *,
    request: Any,
    ctx: Any | None,
    result: Any,
    critic_passed: bool | None,
    meta_out: dict[str, Any],
) -> None:
    """Best-effort enterprise planes — never raises."""
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_agent_runtime_v3_enabled", True)) and ctx is not None:
            from kernel.agent_runtime.world_projection import build_projection_bundle_from_context

            bundle = build_projection_bundle_from_context(ctx)
            meta_out.update(bundle.to_metadata_dict())
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(
            meta_out, subsystem="agent_runtime_projection", detail="world_projection_bundle", exc=exc
        )
    try:
        from control_plane.control_plane import get_enterprise_control_plane
        from tenant.tenant_context import resolve_tenant_context

        md = (getattr(ctx, "metadata", None) or {}) if ctx else {}
        req_md = getattr(request, "metadata", None) or {}
        merged = {**req_md, **md}
        try:
            from infra.observability.turn_metering import get_turn_tokens, merge_turn_tokens_into_metadata

            merged = merge_turn_tokens_into_metadata(merged)
            tok = get_turn_tokens()
            if tok.get("prompt_tokens") or tok.get("completion_tokens"):
                if ctx is not None:
                    ctx.metadata = ctx.metadata or {}
                    ctx.metadata.update(tok)
        except Exception as exc:
            from infra.observability.runtime_degraded import record_runtime_degradation

            record_runtime_degradation(meta_out, subsystem="turn_metering", detail="token_merge", exc=exc)
        cp = get_enterprise_control_plane()
        decision = cp.evaluate_turn(
            user_id=getattr(request, "user_id", None),
            session_id=getattr(request, "session_id", None),
            tenant_id=merged.get("tenant_id"),
            org_id=merged.get("org_id"),
            workspace_id=merged.get("workspace_id"),
            capability_type=str(merged.get("capability_type") or ""),
            estimated_cost=float(merged.get("estimated_cost") or 0.0),
            pii_detected=bool(merged.get("pii_detected")),
            data_region=str(merged.get("data_residency") or ""),
            metadata=merged,
        )
        meta_out["control_plane"] = decision.to_dict()
        try:
            import asyncio

            from kernel.governance.compliance_audit_store import record_compliance_event

            comp = decision.compliance or {}

            async def _audit() -> None:
                await record_compliance_event(
                    tenant_id=str(merged.get("tenant_id") or "default"),
                    session_id=str(getattr(request, "session_id", "") or ""),
                    user_id=str(getattr(request, "user_id", "") or ""),
                    frameworks=list(
                        comp.get("frameworks_evaluated")
                        or merged.get("compliance_frameworks")
                        or []
                    ),
                    violations=list(decision.violations or []),
                    allowed=bool(decision.allowed),
                    payload={
                        "control_plane": True,
                        "pii_detected": bool(merged.get("pii_detected")),
                    },
                )

            try:
                asyncio.get_running_loop().create_task(_audit())
            except RuntimeError:
                asyncio.run(_audit())
        except Exception as exc:
            from infra.observability.runtime_degraded import record_runtime_degradation

            record_runtime_degradation(meta_out, subsystem="compliance_audit", detail="async_record", exc=exc)
        if decision.allowed:
            tctx = resolve_tenant_context(
                user_id=getattr(request, "user_id", None),
                session_id=getattr(request, "session_id", None),
                goal_id=str(
                    ((request.metadata or {}).get("goal_graph") or {}).get("root_goal_id", "")
                ),
                metadata=merged,
            )
            try:
                from tenant.billing_runtime import apply_billing_to_metadata, resolve_turn_cost

                merged = apply_billing_to_metadata(
                    merged,
                    capability_type=str(merged.get("capability_type") or ""),
                    goal_id=tctx.goal_id,
                )
                meta_out["billing_attribution"] = merged.get("billing_attribution")
                est = resolve_turn_cost(merged)
            except Exception as bill_exc:
                from infra.observability.runtime_degraded import record_runtime_degradation

                record_runtime_degradation(
                    meta_out, subsystem="billing_runtime", detail="quota_cost", exc=bill_exc
                )
                est = float(merged.get("estimated_cost") or 0.0)
            cp.consume_turn_quota(tctx, cost=est)
            cap = str(merged.get("capability_type") or "")
            if cap and est > 0:
                cp.record_turn_cost(tctx, capability_type=cap, actual_cost=est, goal_id=tctx.goal_id)
            try:
                from tenant.usage_metering import get_usage_metering

                pt = int(merged.get("prompt_tokens") or 0)
                ct = int(merged.get("completion_tokens") or 0)
                get_usage_metering().record_turn(
                    tctx,
                    session_id=str(getattr(request, "session_id", "") or ""),
                    goal_id=tctx.goal_id,
                    capability_type=cap,
                    prompt_tokens=pt,
                    completion_tokens=ct,
                    extra_cost=est if not cap else 0.0,
                )
            except Exception as exc:
                from infra.observability.runtime_degraded import record_runtime_degradation

                record_runtime_degradation(meta_out, subsystem="usage_metering", detail="record_turn", exc=exc)
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="control_plane", detail="evaluate_turn", exc=exc)

    try:
        if ctx is not None:
            from world.world_runtime import build_shared_world_state

            sws = build_shared_world_state(ctx)
            meta_out["shared_world_state"] = sws.to_dict()
            try:
                import asyncio

                from world.world_state_redis import save_session_world_state

                sid = str(getattr(ctx, "session_id", "") or "")
                if sid:
                    coro = save_session_world_state(sid, sws.grounding)
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(coro)
                    except RuntimeError:
                        asyncio.run(coro)
            except Exception as exc:
                from infra.observability.runtime_degraded import record_runtime_degradation

                record_runtime_degradation(
                    meta_out, subsystem="world_state_redis", detail="save_session", exc=exc
                )
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="world_runtime", detail="shared_world_state", exc=exc)

    try:
        from observability.enterprise_telemetry import get_enterprise_telemetry

        gkw_md = meta_out.get("governance") or {}
        replanned = bool((getattr(ctx, "metadata", None) or {}).get("refine_replan"))
        tel = get_enterprise_telemetry().record_turn(
            success=critic_passed is not False,
            replanned=replanned,
            fallback=bool((getattr(ctx, "metadata", None) or {}).get("fallback")),
            goal_id=str(
                ((request.metadata or {}).get("goal_graph") or {}).get("root_goal_id", "")
            ),
            tenant_id=str((request.metadata or {}).get("tenant_id") or "default"),
            capability_types=list((getattr(ctx, "metadata", None) or {}).get("capabilities_used") or []),
            cost=float((getattr(ctx, "metadata", None) or {}).get("estimated_cost") or 0.0),
            blocked_goals=int(
                ((request.metadata or {}).get("goal_graph") or {}).get("blocked_count") or 0
            ),
            memory_ref_count=len(
                list(
                    ((meta_out.get("shared_world_state") or {}).get("memory", {}) or {}).get(
                        "fabric_refs", []
                    )
                )
            ),
        )
        obs = meta_out.setdefault("semantic_observability", {})
        if isinstance(obs, dict):
            obs["enterprise_telemetry"] = tel
        try:
            from observability.prometheus_export import record_enterprise_turn_metrics

            cog = tel.get("cognitive") or {}
            record_enterprise_turn_metrics(
                tenant_id=str((request.metadata or {}).get("tenant_id") or "default"),
                success=critic_passed is not False,
                goal_stability=float(cog.get("goal_stability") or 1.0),
                cost=float((getattr(ctx, "metadata", None) or {}).get("estimated_cost") or 0.0),
                capability_types=list(
                    (getattr(ctx, "metadata", None) or {}).get("capabilities_used") or []
                ),
            )
        except Exception as exc:
            from infra.observability.runtime_degraded import record_runtime_degradation

            record_runtime_degradation(meta_out, subsystem="prometheus", detail="enterprise_turn", exc=exc)
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="enterprise_telemetry", detail="record_turn", exc=exc)

    try:
        gg = (request.metadata or {}).get("goal_graph")
        if gg:
            from kernel.goal.goal_portfolio import GoalPortfolio
            from kernel.protocol.runtime_contract import Goal, GoalGraph

            goals = []
            for g in gg.get("goals") or []:
                if isinstance(g, dict):
                    goals.append(
                        Goal(
                            goal_id=str(g.get("goal_id", "")),
                            description=str(g.get("description", "")),
                            metadata=dict(g.get("metadata") or {}),
                        )
                    )
            graph = GoalGraph(root_goal_id=str(gg.get("root_goal_id", "")), goals=goals)
            portfolio = GoalPortfolio()
            meta_out["goal_portfolio"] = portfolio.bind_goal_graph(graph)
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(meta_out, subsystem="goal_portfolio", detail="bind_goal_graph", exc=exc)

    try:
        from infra.observability.runtime_degraded import merge_degradations_into_context

        merge_degradations_into_context(ctx, meta_out)
    except Exception as exc:
        from infra.observability.runtime_degraded import record_runtime_degradation

        record_runtime_degradation(
            meta_out, subsystem="semantic_observability", detail="merge_degradations", exc=exc
        )
        pass