"""Optional hooks to publish execution slices to cross-process world (Data V2 / DI runtime)."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


async def maybe_publish_execution_slice(
    *,
    session_id: str,
    metadata: dict[str, Any] | None = None,
    writer_id: str = "data_intelligence",
) -> None:
    """Publish execution slice when cross-process world is enabled."""
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_world_model_cross_process_enabled", False)):
            return
    except Exception as exc:
        logger.debug("world_slice_hook_flag_skipped", error=str(exc))
        return

    md = dict(metadata or {})
    payload = {
        "phase": str(md.get("phase") or "data_turn"),
        "sql_hash": str(md.get("sql_hash") or ""),
        "row_count": int(md.get("row_count") or 0),
    }
    try:
        from world.cross_process_world import get_cross_process_world

        await get_cross_process_world().publish_slice(
            session_id,
            "execution",
            payload,
            writer_id=writer_id,
        )
    except Exception as exc:
        logger.warning("world_slice_publish_failed", session_id=session_id, error=str(exc))


async def maybe_publish_data_slice(
    *,
    session_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    md = dict(metadata or {})
    dto = md.get("data_turn_outcomes") or md.get("cognitive_context") or {}
    if not dto and md.get("route") not in ("data", "data_intelligence", "data_query"):
        if "compiled_sql" not in md and "sql" not in md:
            return
    sql = str(dto.get("compiled_sql") or md.get("compiled_sql") or md.get("sql") or "")
    row_count = int(dto.get("row_count") or md.get("row_count") or 0)
    await maybe_publish_execution_slice(
        session_id=session_id,
        metadata={
            "phase": "data_turn",
            "sql_hash": str(hash(sql)) if sql else "",
            "row_count": row_count,
        },
        writer_id="data_v2",
    )


async def maybe_publish_rag_slice(
    *,
    session_id: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    md = dict(metadata or {})
    intel = md.get("rag_evidence_intelligence") or {}
    if not intel and md.get("route") not in ("rag", "document_qa"):
        return
    cg = intel.get("chunk_graph") or {}
    payload = {
        "phase": "rag_turn",
        "node_count": int(cg.get("node_count") or 0),
        "contradiction_count": int(cg.get("contradiction_count") or 0),
    }
    try:
        from infra.config.settings import settings

        if not bool(getattr(settings, "kernel_world_model_cross_process_enabled", False)):
            return
        from world.cross_process_world import get_cross_process_world

        await get_cross_process_world().publish_slice(
            session_id,
            "rag_evidence",
            payload,
            writer_id="rag",
        )
    except Exception as exc:
        logger.debug("rag_slice_publish_skipped", error=str(exc))