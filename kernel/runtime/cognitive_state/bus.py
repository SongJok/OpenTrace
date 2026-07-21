"""Cognitive runtime state bus — single write path for phase / evidence / memory."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


def _schedule_graph_redis_flush(graph: Any) -> None:
    """Best-effort async Redis persist for CognitiveStateGraph (single write path: bus)."""
    try:
        import asyncio

        from kernel.runtime.cognitive_state.persistence import flush_cognitive_state_graph

        async def _run() -> None:
            await flush_cognitive_state_graph(graph)

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            asyncio.run(_run())
    except Exception as exc:
        logger.debug("cognitive_state_graph_flush_schedule_skipped", error=str(exc))


from kernel.runtime.cognitive_state.store import (
    CognitiveRuntimeState,
    get_or_create_runtime_state,
)


def bind_state_to_context(ctx: Any, state: CognitiveRuntimeState | None = None) -> CognitiveRuntimeState:
    """Mirror runtime state into ctx.metadata['cognitive_runtime_state'] (authoritative view)."""
    rid = str(getattr(ctx, "request_id", "") or "")
    sid = str(getattr(ctx, "session_id", "") or "")
    md = getattr(ctx, "metadata", None) or {}
    gg = md.get("goal_graph") or {}
    root = str(gg.get("root_goal_id", "") or rid)
    rs = state or get_or_create_runtime_state(rid, sid, goal_id=root)
    if root and not rs.goal_id:
        rs.goal_id = root
    payload = {
        "phase": rs.phase,
        "goal_id": rs.goal_id,
        "evidence_ids": list(rs.evidence_ids),
        "memory_bindings": list(rs.memory_bindings),
        "reasoning_notes": list(rs.reasoning_notes)[-32:],
        "metrics": dict(rs.metrics),
        "world_state_snapshot": dict(rs.world_state_snapshot),
    }
    md["cognitive_runtime_state"] = payload
    ctx.metadata = md
    return rs


def record_evidence_on_bus(ctx: Any, evidence_ids: list[str]) -> None:
    rs = bind_state_to_context(ctx)
    for eid in evidence_ids:
        if eid and eid not in rs.evidence_ids:
            rs.evidence_ids.append(eid)
    bind_state_to_context(ctx, rs)


def record_memory_binding(ctx: Any, memory_id: str) -> None:
    rs = bind_state_to_context(ctx)
    if memory_id and memory_id not in rs.memory_bindings:
        rs.memory_bindings.append(memory_id)
    bind_state_to_context(ctx, rs)


def apply_runtime_contribution_to_bus(ctx: Any, contribution: Any) -> None:
    """Unified contribution → cognitive state graph + evidence/memory bindings."""
    from kernel.agent_runtime.runtime_contribution import RuntimeContribution
    from kernel.runtime.cognitive_state.cognitive_state_graph import (
        apply_contribution_to_graph,
        graph_from_context,
        persist_graph_on_context,
    )

    if not isinstance(contribution, RuntimeContribution):
        return
    graph = graph_from_context(ctx)
    apply_contribution_to_graph(graph, contribution)
    persist_graph_on_context(ctx, graph)
    _schedule_graph_redis_flush(graph)
    record_evidence_on_bus(ctx, [e.evidence_id for e in contribution.evidence if e.evidence_id])
    for mem in contribution.memory_updates:
        for key in mem.memory_keys:
            record_memory_binding(ctx, key)


async def hydrate_state_from_store(ctx: Any) -> None:
    """Load persisted slice into in-process state when enabled."""
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_cognitive_state_persist_enabled", False)):
            return
        from kernel.runtime.cognitive_state.persistence import load_runtime_state

        sid = str(getattr(ctx, "session_id", "") or "")
        rid = str(getattr(ctx, "request_id", "") or "")
        blob = await load_runtime_state(sid, rid)
        if blob:
            rs = bind_state_to_context(ctx)
            rs.phase = str(blob.get("phase", rs.phase))
            rs.goal_id = str(blob.get("goal_id", rs.goal_id))
            rs.evidence_ids = list(blob.get("evidence_ids") or rs.evidence_ids)
            rs.world_state_snapshot = dict(blob.get("world_state_snapshot") or rs.world_state_snapshot)
            rs.metrics.update(dict(blob.get("metrics") or {}))
            bind_state_to_context(ctx, rs)

        from kernel.runtime.cognitive_state.cognitive_state_graph import (
            CognitiveStateGraph,
            persist_graph_on_context,
        )
        from kernel.runtime.cognitive_state.persistence import load_cognitive_state_graph

        graph_blob = await load_cognitive_state_graph(sid, rid)
        if graph_blob:
            try:
                graph = CognitiveStateGraph.model_validate(graph_blob)
                persist_graph_on_context(ctx, graph)
            except Exception as exc:
                logger.warning("cognitive_state_graph_hydrate_skipped", error=str(exc))
    except Exception as exc:
        logger.warning("cognitive_state_hydrate_skipped", error=str(exc))