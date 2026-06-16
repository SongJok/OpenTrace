"""
RuntimeGateway — 瘦运行时路由层（V2）。

主路径：Kernel → CognitiveSupervisor.prepare_run → RuntimeGateway → RuntimeTurnDispatcher
       → runtime.registry → Runtime。

本模块仅负责：prepare 委托、运行时查找与调度、流式事件转发。
GoalGraph、治理打包、Artifact 组装由 kernel.cognitive_supervisor 与 run_outcomes 负责。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from infra.observability.logger import get_logger
from kernel.cognitive_supervisor.prepare_dispatch import (
    build_runtime_context_from_kernel_request,
    runtime_task_from_request,
)

logger = get_logger(__name__)


@dataclass
class Tier0ChatContext:
    """Gateway-injected deps for tier0 database direct (kernel must not import gateway)."""

    db: Any
    current_user: Any
    data_query_fn: Callable[..., Any]
    data_query_request_factory: Callable[..., Any]


__all__ = [
    "RuntimeGateway",
    "get_runtime_gateway",
    "build_runtime_context_from_kernel_request",
    "runtime_task_from_request",
    "Tier0ChatContext",
]


class RuntimeGateway:
    """Runtime lookup, lifecycle, dispatch only."""

    async def _ensure_turn_enrichment(self, request: Any) -> None:
        """Preference / memory / fabric (+ multi-turn when not done in Kernel)."""
        md = dict(getattr(request, "metadata", None) or {})
        if md.get("turn_enrichment_applied"):
            return
        skip_mt = bool(md.get("multi_turn_resolution"))
        try:
            from kernel.turn_enrichment import enrich_turn_before_dispatch

            await enrich_turn_before_dispatch(request, skip_multi_turn=skip_mt)
            md = dict(getattr(request, "metadata", None) or {})
            md["turn_enrichment_applied"] = True
            request.metadata = md
        except Exception as exc:
            logger.debug("runtime_gateway_turn_enrichment_skipped", error=str(exc))

    async def try_tier0_chat(
        self,
        *,
        query: str,
        session_id: str,
        request_id: str,
        tier0_ctx: Tier0ChatContext | None = None,
        force_database: bool = False,
        data_source_id: str | None = None,
    ) -> Any:
        """SQL retrieval or forced DB query before full supervisor dispatch."""
        from kernel.runtime.tier0_paths import (
            run_database_direct_tier0,
            run_sql_retrieval_tier0,
        )

        if not tier0_ctx:
            return None
        sql_out = await run_sql_retrieval_tier0(
            query=query,
            session_id=session_id,
            request_id=request_id,
            db=tier0_ctx.db,
        )
        if sql_out and sql_out.handled:
            return sql_out
        if force_database and data_source_id:
            return await run_database_direct_tier0(
                query=query,
                data_source_id=str(data_source_id),
                session_id=session_id,
                request_id=request_id,
                current_user=tier0_ctx.current_user,
                db=tier0_ctx.db,
                data_query_fn=tier0_ctx.data_query_fn,
                data_query_request_factory=tier0_ctx.data_query_request_factory,
            )
        return None

    async def try_tool_fast_path(self, request: Any) -> Any | None:
        """Tier-0 tool dispatch (weather/time/tool) before full supervisor."""
        from kernel.fast_tool_path import run_tool_fast_path, should_use_tool_fast_path

        force_mode = (request.metadata or {}).get("force_mode")
        lock_dict = (request.metadata or {}).get("intent_lock")
        if not should_use_tool_fast_path(lock_dict, force_mode=force_mode):
            return None
        return await run_tool_fast_path(request)

    async def stream_tool_fast_path(self, request: Any):
        from kernel.fast_tool_path import stream_tool_fast_path

        async for event in stream_tool_fast_path(request):
            yield event

    async def run(self, request: Any) -> Any:
        from kernel.cognitive_supervisor import get_cognitive_supervisor
        from kernel.runtime.runtime_turn_dispatcher import get_runtime_turn_dispatcher

        await self._ensure_turn_enrichment(request)
        t0 = time.monotonic()
        supervisor = get_cognitive_supervisor()
        prepared = supervisor.prepare_run(request)
        response = await get_runtime_turn_dispatcher().run_turn(
            request, prepared, t0=t0
        )
        if hasattr(response, "total_latency_ms"):
            response.total_latency_ms = int((time.monotonic() - t0) * 1000)
        try:
            from kernel.runtime.finalize_turn import post_turn_enterprise_accounting

            post_turn_enterprise_accounting(request, response)
        except Exception as exc:
            logger.debug("runtime_gateway_finalize_turn_skipped", error=str(exc))
        return response

    async def stream(self, request: Any) -> AsyncIterator[dict[str, Any]]:
        from kernel.cognitive_supervisor import get_cognitive_supervisor
        from kernel.runtime.runtime_turn_dispatcher import get_runtime_turn_dispatcher

        await self._ensure_turn_enrichment(request)
        supervisor = get_cognitive_supervisor()
        prepared = supervisor.prepare_run(request)
        if not prepared.governance_meta.get("allowed", True):
            yield {
                "type": "error",
                "data": {
                    "message": "runtime governance denied",
                    "violations": prepared.governance_meta.get("violations", []),
                },
            }
            return

        async for event in get_runtime_turn_dispatcher().stream_turn(request, prepared):
            yield event


def get_runtime_gateway() -> RuntimeGateway:
    if not hasattr(get_runtime_gateway, "_instance"):
        get_runtime_gateway._instance = RuntimeGateway()  # type: ignore[attr-defined]
    return get_runtime_gateway._instance  # type: ignore[attr-defined]