"""Memory Fabric read path — goal-scoped recall before legacy bucket retrieval."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


def retrieve_goal_scoped_memory(
    *,
    session_id: str,
    goal_id: str = "",
    query: str = "",
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Return memory chunks ranked by fabric relations + salience."""
    out: list[dict[str, Any]] = []
    if not session_id:
        return out
    try:
        import asyncio

        from memory.fabric.memory_graph import ensure_memory_graph_hydrated
        from memory.fabric.router_singleton import get_memory_fabric_router

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(ensure_memory_graph_hydrated(session_id))
        except RuntimeError:
            logger.debug("memory_graph_hydrate_sync_context", session_id=session_id)

        router = get_memory_fabric_router()
        if goal_id:
            for rel in router.query_by_goal(goal_id):
                out.append(
                    {
                        "content": rel.metadata.get("query_preview")
                        or rel.metadata.get("answer_preview")
                        or rel.memory_id,
                        "score": rel.salience,
                        "source": "memory_fabric",
                        "memory_id": rel.memory_id,
                    }
                )
        snap = router.graph_snapshot(session_id)
        for node in (snap.get("nodes") or [])[: top_k * 2]:
            if not isinstance(node, dict):
                continue
            nid = str(node.get("id", ""))
            if nid and not any(c.get("memory_id") == nid for c in out):
                out.append(
                    {
                        "content": str(node.get("metadata", {}).get("query_preview", nid)),
                        "score": float(node.get("weight", 0.5) or 0.5),
                        "source": "memory_graph",
                        "memory_id": nid,
                    }
                )
    except Exception as exc:
        logger.warning(
            "memory_fabric_retrieval_failed",
            session_id=session_id,
            goal_id=goal_id,
            error=str(exc),
        )
        return []
    if query:
        q = query.lower()
        out.sort(
            key=lambda c: (
                float(c.get("score", 0)),
                1.0 if q in str(c.get("content", "")).lower() else 0.0,
            ),
            reverse=True,
        )
    return out[:top_k]


async def merge_fabric_with_legacy_retrieve(
    *,
    session_id: str,
    goal_id: str,
    query: str,
    episodic_chunks: list[str],
    keyword_chunks: list[str],
    top_k: int = 8,
) -> list[dict[str, Any]]:
    """Fabric-first merge; fall back to MemoryRouter when fabric is sparse."""
    fabric_hits = retrieve_goal_scoped_memory(
        session_id=session_id,
        goal_id=goal_id,
        query=query,
        top_k=top_k,
    )
    try:
        from infra.config.settings import settings

        if bool(getattr(settings, "kernel_memory_fabric_primary_only", False)):
            return fabric_hits[:top_k]
    except Exception as exc:
        from infra.observability.logger import get_logger

        get_logger(__name__).warning("memory_fabric_primary_only_flag_skipped", error=str(exc))
    if len(fabric_hits) >= max(2, top_k // 2):
        return fabric_hits
    try:
        from memory.memory_router.router import get_memory_router

        memory_chunks = await get_memory_router().retrieve(
            query=query,
            episodic_chunks=episodic_chunks,
            keyword_chunks=keyword_chunks,
            top_k=top_k,
        )
        legacy = [
            {"content": c.content, "score": c.score, "source": c.source}
            for c in memory_chunks
        ]
        seen = {h.get("memory_id") or h.get("content") for h in fabric_hits}
        for item in legacy:
            key = item.get("content")
            if key not in seen:
                fabric_hits.append(item)
        return fabric_hits[:top_k]
    except Exception as exc:
        logger.warning("memory_legacy_router_merge_failed", error=str(exc))
        return fabric_hits[:top_k]