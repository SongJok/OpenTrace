"""Resume a paused turn via RuntimeGateway (replays last user query from TraceLog)."""

from __future__ import annotations

import json
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


async def load_resume_context_from_trace(
    db: Any,
    *,
    session_id: str,
    step_index: int,
) -> tuple[str, dict[str, Any]]:
    """Load query and execution_graph slice for resume from TraceLog."""
    from sqlalchemy import select

    from infra.storage.models import TraceLog

    res = await db.execute(
        select(TraceLog)
        .where(TraceLog.session_id == session_id)
        .order_by(TraceLog.created_at.desc())
        .limit(max(1, step_index + 1))
    )
    logs = list(res.scalars().all())
    if not logs:
        raise ValueError("No trace log for session")
    log = logs[min(step_index, len(logs) - 1)]
    query = (log.query or "").strip()
    if not query:
        raise ValueError("Resume target turn has no query")
    graph: dict[str, Any] = {}
    if log.execution_graph_json:
        try:
            parsed = json.loads(log.execution_graph_json)
            if isinstance(parsed, dict):
                graph = parsed
        except (json.JSONDecodeError, TypeError) as exc:
            logger.warning("resume_graph_parse_failed", error=str(exc))
    return query, graph


async def resume_turn_via_gateway(
    db: Any,
    *,
    session_id: str,
    user_id: str,
    step_index: int = 0,
) -> Any:
    """Re-run last (or indexed) turn through CognitiveKernel → RuntimeGateway."""
    from kernel.cognitive_kernel import KernelRequest
    from kernel.runtime_gateway import get_runtime_gateway

    query, prior_graph = await load_resume_context_from_trace(
        db, session_id=session_id, step_index=step_index
    )
    metadata: dict[str, Any] = {
        "resume": True,
        "resume_step_index": step_index,
        "prior_execution_graph": prior_graph,
    }
    request = KernelRequest(
        query=query,
        session_id=session_id,
        user_id=user_id,
        history=[],
        stream=False,
        metadata=metadata,
    )
    try:
        from kernel.turn_bootstrap import bootstrap_turn_intent

        await bootstrap_turn_intent(request, apply_multi_turn=False)
    except Exception as exc:
        logger.debug("resume_turn_bootstrap_skipped", error=str(exc))
    return await get_runtime_gateway().run(request)