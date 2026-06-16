"""V5 fast-path routing (L0 / semantic cache / L1) — extracted from CognitiveKernel."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger
from kernel.identity.system_identity import (
    is_canonical_identity_response,
    is_identity_user_query,
)

logger = get_logger(__name__)


def _v5_answer_allowed(query: str, content: str | None, route: str) -> bool:
    """Block canned identity text on non-identity user queries (except explicit identity route)."""
    if not content:
        return False
    if route == "identity":
        return True
    if is_canonical_identity_response(content) and not is_identity_user_query(query):
        logger.warning(
            "v5_fast_path_identity_blocked",
            route=route,
            query_preview=(query or "")[:80],
        )
        return False
    return True


@dataclass
class V5FastPathResult:
    hit: bool
    content: str = ""
    route: str = ""
    metadata: dict[str, Any] | None = None
    force_mode: str | None = None


class V5RoutingFacade:
    def __init__(self, kernel: Any) -> None:
        self._kernel = kernel

    def should_skip_v5(
        self,
        *,
        force_mode: str | None,
        has_attachments: bool,
    ) -> bool:
        return bool(force_mode or has_attachments)

    async def try_fast_path(
        self,
        request: Any,
        *,
        session_id: str,
        is_multi: bool,
        context_hash_fn: Any,
        t0: float,
    ) -> V5FastPathResult | None:
        """Return V5FastPathResult on hit; None to continue to RuntimeGateway."""
        if not settings.kernel_v5_routing_enabled:
            return None
        k = self._kernel
        query = request.query

        if settings.kernel_l0_rule_router_enabled:
            l0 = await k._get_l0_router().route(
                query,
                session_id,
                is_multi=is_multi,
                conversation_history=request.history,
            )
            if l0.hit and l0.answer is not None:
                if l0.route == "force_mode":
                    return V5FastPathResult(
                        hit=True,
                        content=l0.answer or query,
                        route="force_mode",
                        metadata=dict(l0.metadata or {}),
                        force_mode=l0.force_mode,
                    )
                if (
                    l0.route == "identity"
                    and settings.kernel_enriched_identity_enabled
                ):
                    try:
                        from kernel.identity.enriched_identity import (
                            generate_enriched_identity,
                        )
                        from memory.working_memory.working_memory import (
                            get_or_create_session_memory,
                        )

                        wm_turns = []
                        if session_id:
                            wm_turns = get_or_create_session_memory(session_id).to_messages()
                        l0.answer = await generate_enriched_identity(
                            query=query,
                            user_id=request.user_id,
                            user_preferences=request.metadata.get("user_preferences", []),
                            recent_history=wm_turns or request.history,
                        )
                        l0.metadata = dict(l0.metadata or {})
                        l0.metadata["enriched"] = True
                    except Exception as exc:
                        logger.debug("Enriched identity failed", error=str(exc))
                if not _v5_answer_allowed(query, l0.answer, l0.route):
                    pass  # fall through to RuntimeGateway
                else:
                    return V5FastPathResult(
                        hit=True,
                        content=l0.answer,
                        route=l0.route,
                        metadata=dict(l0.metadata or {}),
                    )

        if (
            settings.kernel_semantic_cache_enabled
            and not is_multi
            and not is_identity_user_query(query)
            and request.metadata.get("task_type")
            not in ("weather", "time", "data_query", "web_search")
        ):
            ctx_hash = context_hash_fn(request.history)
            cached = await k._get_semantic_cache().lookup(query, ctx_hash)
            if cached and cached.answer and _v5_answer_allowed(
                query, cached.answer, "semantic_cache"
            ):
                return V5FastPathResult(
                    hit=True,
                    content=cached.answer,
                    route="semantic_cache",
                    metadata={"cache_hit": True, "cache_hits": cached.hit_count},
                )

        if settings.kernel_l1_tiny_router_enabled and not is_multi:
            complexity = k._get_complexity_engine().assess(
                query,
                conversation_context={
                    "history_length": len(request.history),
                    "session_id": session_id,
                },
            )
            if complexity.recommended_pipeline in ("L0", "L1"):
                l1 = await k._get_tiny_router().route(
                    query,
                    request.history,
                    intent_lock=request.metadata.get("intent_lock"),
                )
                if l1.route != "complex" and l1.answer:
                    route_name = f"l1_{l1.route}"
                    if not _v5_answer_allowed(query, l1.answer, route_name):
                        pass
                    else:
                        meta = {**l1.metadata, "complexity": complexity.level}
                        return V5FastPathResult(
                            hit=True,
                            content=l1.answer,
                            route=route_name,
                            metadata=meta,
                        )
        return None


def get_v5_routing_facade(kernel: Any) -> V5RoutingFacade:
    return V5RoutingFacade(kernel)


async def stream_v5_fast_path_from_result(
    fp: V5FastPathResult,
    request: Any,
):
    """Yield SSE events for an already-resolved V5 fast path."""
    from kernel.cognitive_kernel import KernelRequest, _emit_streaming_answer
    from kernel.runtime_gateway import get_runtime_gateway

    if fp.route == "force_mode" and fp.force_mode:
        from kernel.cognitive_controls import classify_intent
        from kernel.fast_tool_path import should_use_tool_fast_path, stream_tool_fast_path

        force_req = KernelRequest(
            query=fp.content or request.query,
            session_id=request.session_id,
            user_id=request.user_id,
            history=request.history,
            metadata={
                **request.metadata,
                "web_enabled": request.web_enabled,
                "force_mode": fp.force_mode,
            },
            trace_ctx=request.trace_ctx,
            conversation_state=request.conversation_state,
        )
        conv_state = getattr(request, "conversation_state", None)
        lock = classify_intent(
            force_req.query,
            fp.force_mode,
            prior_intent=getattr(conv_state, "active_intent", None) if conv_state else None,
            prior_domain=getattr(conv_state, "active_domain", None) if conv_state else None,
            conversation_phase=getattr(conv_state, "conversation_phase", None) if conv_state else None,
        )
        force_req.metadata["intent_lock"] = lock.to_dict()
        force_req.metadata["task_type"] = lock.task_type
        if should_use_tool_fast_path(lock, force_mode=fp.force_mode):
            async for event in stream_tool_fast_path(force_req):
                yield event
            return
        yield {
            "type": "reasoning_step",
            "data": {
                "id": "l0_slash",
                "stage": "ROUTE",
                "content": f"L0 斜杠命令 (Runtime V2): {fp.force_mode}",
                "node_id": "node_l0",
                "status": "done",
            },
        }
        async for event in get_runtime_gateway().stream(force_req):
            yield event
        return

    label = fp.route
    if fp.route == "semantic_cache":
        label = "语义缓存命中"
    elif fp.route.startswith("l1_"):
        label = f"L1 路由: {fp.route}"
    else:
        label = f"L0 规则匹配: {fp.route}"

    async for event in _emit_streaming_answer(
        fp.content,
        reasoning_step={
            "type": "reasoning_step",
            "data": {
                "id": "v5_fast_path",
                "stage": "ROUTE",
                "content": label,
                "node_id": "node_v5",
                "status": "done",
            },
        },
    ):
        yield event