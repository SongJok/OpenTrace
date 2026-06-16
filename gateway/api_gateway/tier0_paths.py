"""Gateway re-exports — tier0 SSOT lives in kernel.runtime.tier0_paths."""

from __future__ import annotations

from typing import Any, Callable

from kernel.runtime.tier0_paths import (  # noqa: F401
    SQL_RETRIEVAL_KEYWORDS,
    Tier0SyncOutcome,
    get_previous_turn_sql,
    is_sql_retrieval_intent,
    run_database_direct_tier0 as _run_database_direct_tier0,
    run_sql_retrieval_tier0,
    sse_database_direct_events,
    sse_sql_retrieval_events,
    stream_tier0_events,
    tier0_governance_envelope,
)


async def run_database_direct_tier0(
    *,
    query: str,
    data_source_id: str,
    session_id: str,
    request_id: str,
    current_user: Any,
    db: Any,
    data_query_fn: Callable[..., Any],
) -> Tier0SyncOutcome | None:
    from gateway.api_gateway.routers.data import DataQueryRequest

    return await _run_database_direct_tier0(
        query=query,
        data_source_id=data_source_id,
        session_id=session_id,
        request_id=request_id,
        current_user=current_user,
        db=db,
        data_query_fn=data_query_fn,
        data_query_request_factory=DataQueryRequest,
    )

__all__ = [
    "SQL_RETRIEVAL_KEYWORDS",
    "Tier0SyncOutcome",
    "get_previous_turn_sql",
    "is_sql_retrieval_intent",
    "run_database_direct_tier0",
    "run_sql_retrieval_tier0",
    "sse_database_direct_events",
    "sse_sql_retrieval_events",
    "stream_tier0_events",
    "tier0_governance_envelope",
]