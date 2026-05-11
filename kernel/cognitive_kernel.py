"""
Cognitive Kernel — 系统唯一中枢入口（认知内核 v2，生产级）

核心原则:
  1. 所有输出必须由认知内核生成
  2. 所有插件返回的数据只是「候选认知材料」
  3. LLM 不是回答器，而是「认知执行器」
  4. Prompt 不是模板，而是「认知协议（Cognitive Protocol）」

多 Prompt 链执行流程:
  Step 1: intent_prompt  — 意图识别（PLANNING 小模型，<100ms）
  Step 2: plan_prompt    — 任务规划（PLANNING 小模型）
  Step 3: tool_select    — 工具选择（PLANNING 小模型）
          + asyncio.gather(memory, doc, web) 并行执行插件
  Step 4: reasoning      — 推理生成（QUERY 大模型，五层 Prompt）
  Step 5: reflection     — 反思优化（QUERY 大模型）
  Step 6: meta_cognition — 质量门控（三级）
  Step 7: memory.store() — 异步写回（不阻塞响应）
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Optional

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.observability.runtime_metrics import runtime_metrics_store
from infra.observability.tracer import get_tracer
from kernel.cognition.self_model import SelfModel
from kernel.cognition.types import CapabilityLevel, TaskDomain
from kernel.identity.system_identity import CANONICAL_IDENTITY_RESPONSE, is_identity_user_query
from kernel.protocol.events import trace_context_for_request
from memory.working_memory.working_memory import (
    cache_identity_answer,
    get_cached_identity_answer,
    get_or_create_session_memory,
)

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_STREAM_CHUNK_SIZE = 16
_STREAM_DELAY = 0.015


async def _emit_streaming_answer(
    content: str,
    reasoning_step: dict | None = None,
    execution_graph: dict | None = None,
    citations: list | None = None,
    annotations: list | None = None,
    state_patch: dict | None = None,
    result_refs: list | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yield delta chunks followed by final_answer for a streaming effect."""
    if reasoning_step:
        yield reasoning_step

    text = content or ""
    for i in range(0, len(text), _STREAM_CHUNK_SIZE):
        yield {"type": "delta", "data": {"text": text[i : i + _STREAM_CHUNK_SIZE]}}
        await asyncio.sleep(_STREAM_DELAY)

    final_data: dict[str, Any] = {"content": text}
    if execution_graph is not None:
        final_data["execution_graph"] = execution_graph
    if citations is not None:
        final_data["citations"] = citations
    if annotations is not None:
        final_data["annotations"] = annotations
    if state_patch is not None:
        final_data["state_patch"] = state_patch
    if result_refs is not None:
        final_data["result_refs"] = result_refs
    yield {"type": "final_answer", "data": final_data}


@dataclass
class KernelRequest:
    query: str
    session_id: str = ""
    user_id: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    stream: bool = False
    web_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    trace_ctx: Any = None
    conversation_state: Any = None  # ConversationState | None


@dataclass
class KernelResponse:
    content: str
    session_id: str = ""
    route: str = "direct"
    validation_score: float = 1.0
    passed_validation: bool = True
    hallucination_risk: float = 0.0
    intent_category: str = "qa"
    intent_complexity: str = "simple"
    context_latency_ms: int = 0
    total_latency_ms: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    state_patch: dict[str, Any] | None = None
    result_refs: list[dict[str, Any]] = field(default_factory=list)


class CognitiveKernel:
    """
    认知内核 — 系统唯一中枢。
    所有能力（Memory / Document / Web / Tool / RAG）均为被调度的插件。
    核心逻辑是「多 Prompt 链 + 并行插件执行」。
    """

    def __init__(
        self,
        intent_engine=None,
        policy_engine=None,
        reasoning_engine=None,
        meta_cognition=None,
        memory_router=None,
    ) -> None:
        self._intent_engine = intent_engine
        self._policy_engine = policy_engine
        self._reasoning_engine = reasoning_engine
        self._meta_cognition = meta_cognition
        self._memory_router = memory_router
        self.self_model = SelfModel()

    # ── Lazy singletons ───────────────────────────────────────────────
    def _get_intent_engine(self):
        if self._intent_engine is None:
            from kernel.intent_engine.engine import IntentEngine
            self._intent_engine = IntentEngine()
        return self._intent_engine

    def _get_policy_engine(self):
        if self._policy_engine is None:
            from kernel.policy.engine import PolicyEngine
            self._policy_engine = PolicyEngine()
        return self._policy_engine

    def _get_reasoning_engine(self):
        if self._reasoning_engine is None:
            from kernel.reasoning.engine import ReasoningEngine
            self._reasoning_engine = ReasoningEngine()
        return self._reasoning_engine

    def _get_meta_cognition(self):
        if self._meta_cognition is None:
            from kernel.meta_cognition.meta_cognition import MetaCognition
            self._meta_cognition = MetaCognition()
        return self._meta_cognition

    def _get_memory_router(self):
        if self._memory_router is None:
            from memory.memory_router.router import get_memory_router
            self._memory_router = get_memory_router()
        return self._memory_router

    def _get_prompt_engine(self):
        from kernel.prompt_engine.cognitive_prompt import get_prompt_engine
        return get_prompt_engine()

    def _get_gateway(self):
        from model.model_gateway.gateway import get_model_gateway
        return get_model_gateway()

    # ── V5 Routing Tier lazy singletons ───────────────────────────────
    def _get_l0_router(self):
        if not hasattr(self, "_l0_router") or self._l0_router is None:
            from kernel.query_router_v2 import L0RuleRouter
            self._l0_router = L0RuleRouter()
        return self._l0_router

    def _get_semantic_cache(self):
        if not hasattr(self, "_semantic_cache") or self._semantic_cache is None:
            from kernel.semantic_cache import SemanticCache
            self._semantic_cache = SemanticCache()
        return self._semantic_cache

    def _get_complexity_engine(self):
        if not hasattr(self, "_complexity_engine") or self._complexity_engine is None:
            from kernel.complexity_engine import ComplexityEngine
            self._complexity_engine = ComplexityEngine()
        return self._complexity_engine

    def _get_tiny_router(self):
        if not hasattr(self, "_tiny_router") or self._tiny_router is None:
            from kernel.tiny_router import TinyRouter
            self._tiny_router = TinyRouter()
        return self._tiny_router

    def _get_context_composer(self):
        if not hasattr(self, "_context_composer") or self._context_composer is None:
            from kernel.context_composer import ContextComposer
            self._context_composer = ContextComposer()
        return self._context_composer

    # ── Main entry point ──────────────────────────────────────────────
    async def run(self, request: KernelRequest) -> KernelResponse:
        """同步执行：支持 v1/v2 编排器分流。"""
        from kernel.orchestrator import CognitiveOrchestrator, OrchestratorRequest

        t0 = time.monotonic()
        with tracer.start_as_current_span("cognitive_kernel.run") as span:
            sid = request.session_id
            trace_ctx = request.trace_ctx or trace_context_for_request(
                request_id=request.metadata.get("request_id", sid),
                session_id=sid,
                user_id=request.user_id,
            )
            is_multi = self._is_multi_question(request.query)

            # ── Working memory identity cache (fastest path) ──────────
            if sid and is_identity_user_query(request.query) and not is_multi:
                cached = get_cached_identity_answer(sid)
                if cached:
                    total_ms = int((time.monotonic() - t0) * 1000)
                    span.set_attribute("total.latency_ms", total_ms)
                    span.set_attribute("identity.cache_hit", True)
                    return KernelResponse(
                        content=cached,
                        session_id=sid,
                        route="working_memory",
                        validation_score=1.0,
                        passed_validation=True,
                        hallucination_risk=0.0,
                        intent_category="identity",
                        intent_complexity="loop",
                        context_latency_ms=0,
                        total_latency_ms=total_ms,
                        metadata={"identity_cache": True},
                    )

            # ── V5 Routing Tier ───────────────────────────────────────
            # Skip V5 routing when force_mode is explicitly set (slash commands like /rag)
            # or when the request includes attachment contexts. L0/L1 routers can't handle
            # attachment content and would return canned identity/FAQ/knowledge answers.
            force_mode_from_meta: str | None = request.metadata.get("force_mode")
            has_attachments = bool(request.metadata.get("attachment_contexts"))
            if force_mode_from_meta or has_attachments:
                if force_mode_from_meta:
                    span.set_attribute("routing.force_mode", force_mode_from_meta)
                if has_attachments:
                    span.set_attribute("routing.has_attachments", True)
                span.set_attribute("routing.skip_v5", True)
            elif settings.kernel_v5_routing_enabled:
                # L0: Rule Router (zero-LLM, <1ms)
                if settings.kernel_l0_rule_router_enabled:
                    l0_result = await self._get_l0_router().route(
                        request.query, sid, is_multi=is_multi
                    )
                    if l0_result.hit and l0_result.answer is not None:
                        if l0_result.route == "force_mode":
                            identity_prompt = self.self_model.get_identity_prompt()
                            from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request
                            orchestrator_v4 = CognitiveOrchestratorV4(
                                timeout_sec=int(settings.kernel_agent_timeout_sec),
                                max_parallel=int(settings.kernel_agent_max_parallel),
                            )
                            resp = await orchestrator_v4.process(
                                OrchestratorV4Request(
                                    query=l0_result.answer,
                                    session_id=request.session_id,
                                    user_id=request.user_id,
                                    history=request.history,
                                    metadata={
                                        **request.metadata,
                                        "web_enabled": request.web_enabled,
                                        "force_mode": l0_result.force_mode,
                                    },
                                    trace_ctx=trace_ctx,
                                    conversation_state=request.conversation_state,
                                )
                            )
                            total_ms = int((time.monotonic() - t0) * 1000)
                            return KernelResponse(
                                content=resp.content,
                                session_id=request.session_id,
                                route=resp.route,
                                validation_score=resp.validation_score,
                                passed_validation=resp.passed_validation,
                                hallucination_risk=resp.hallucination_risk,
                                intent_category=resp.intent_category,
                                intent_complexity="loop",
                                context_latency_ms=0,
                                total_latency_ms=total_ms,
                                state_patch=resp.state_patch,
                                result_refs=resp.result_refs or [],
                                metadata=resp.metadata or {},
                            )

                        # ── Enriched identity via MinShort 0.6B ──────────
                        if l0_result.route == "identity" and settings.kernel_enriched_identity_enabled:
                            try:
                                from kernel.identity.enriched_identity import generate_enriched_identity
                                wm_turns = []
                                if sid:
                                    try:
                                        wm_turns = get_or_create_session_memory(sid).to_messages()
                                    except Exception:
                                        pass
                                enriched = await generate_enriched_identity(
                                    query=request.query,
                                    user_id=request.user_id,
                                    user_preferences=request.metadata.get("user_preferences", []),
                                    recent_history=wm_turns or request.history,
                                )
                                l0_result.answer = enriched
                                l0_result.metadata["enriched"] = True
                            except Exception as exc:
                                logger.debug("Enriched identity failed, using canned", error=str(exc))

                        if l0_result.route in ("identity", "faq") and sid:
                            cache_identity_answer(sid, request.query, l0_result.answer)
                        total_ms = int((time.monotonic() - t0) * 1000)
                        return KernelResponse(
                            content=l0_result.answer,
                            session_id=request.session_id,
                            route=l0_result.route,
                            validation_score=1.0,
                            passed_validation=True,
                            hallucination_risk=0.0,
                            intent_category=l0_result.route,
                            intent_complexity="simple",
                            context_latency_ms=0,
                            total_latency_ms=total_ms,
                            metadata=l0_result.metadata,
                        )

                # L0.5: Semantic Cache
                if settings.kernel_semantic_cache_enabled and not is_multi:
                    cached = await self._get_semantic_cache().lookup(request.query)
                    if cached and cached.answer:
                        total_ms = int((time.monotonic() - t0) * 1000)
                        return KernelResponse(
                            content=cached.answer,
                            session_id=request.session_id,
                            route="semantic_cache",
                            validation_score=1.0,
                            passed_validation=True,
                            hallucination_risk=0.0,
                            intent_category="cached",
                            intent_complexity="simple",
                            context_latency_ms=0,
                            total_latency_ms=total_ms,
                            metadata={"cache_hit": True, "cache_hits": cached.hit_count},
                        )

                # L1: Complexity Engine + Tiny Router
                if settings.kernel_l1_tiny_router_enabled and not is_multi:
                    complexity = self._get_complexity_engine().assess(request.query)
                    if complexity.recommended_pipeline in ("L0", "L1"):
                        l1_result = await self._get_tiny_router().route(
                            request.query, request.history
                        )
                        if l1_result.route != "complex" and l1_result.answer:
                            total_ms = int((time.monotonic() - t0) * 1000)
                            return KernelResponse(
                                content=l1_result.answer,
                                session_id=request.session_id,
                                route=f"l1_{l1_result.route}",
                                validation_score=1.0,
                                passed_validation=True,
                                hallucination_risk=0.0,
                                intent_category=l1_result.route,
                                intent_complexity=l1_result.difficulty,
                                context_latency_ms=0,
                                total_latency_ms=total_ms,
                                metadata={**l1_result.metadata, "complexity": complexity.level},
                            )
            # ── End V5 Routing Tier ────────────────────────────────────

            # ── Memory Context Injection ─────────────────────────────────
            memory_context: list[dict[str, Any]] = []
            if settings.kernel_memory_context_enabled and sid:
                episodic_chunks: list[str] = []
                keyword_chunks: list[str] = []

                # Episodic memory (Redis-backed, best-effort)
                try:
                    from memory.episodic_memory.episodic_memory import EpisodicMemory

                    episodic = EpisodicMemory(sid)
                    episodic_events = await episodic.recall(last_n=20)
                    # Format episodic events as readable Q&A pairs instead of raw JSON
                    for e in episodic_events:
                        try:
                            inner = json.loads(e.get("content", "{}"))
                            if isinstance(inner, dict):
                                q = inner.get("q", "")
                                a = inner.get("a", "")
                                if q and a:
                                    episodic_chunks.append(f"Q: {q}\nA: {a[:300]}")
                                else:
                                    episodic_chunks.append(e.get("content", "")[:500])
                            else:
                                episodic_chunks.append(str(inner)[:500])
                        except (json.JSONDecodeError, TypeError):
                            episodic_chunks.append(str(e.get("content", ""))[:500])
                except Exception:
                    pass

                # Working memory turns (in-process, always available)
                try:
                    wm = get_or_create_session_memory(sid)
                    keyword_chunks = [
                        f"user: {t.content}" if t.role == "user" else f"assistant: {t.content}"
                        for t in wm.get_turns(last_n=8)
                    ] + request.metadata.get("user_preferences", [])
                except Exception:
                    pass

                # Semantic memory retrieval (combines all sources)
                if episodic_chunks or keyword_chunks:
                    try:
                        memory_chunks = await self._get_memory_router().retrieve(
                            query=request.query,
                            episodic_chunks=episodic_chunks,
                            keyword_chunks=keyword_chunks,
                            top_k=8,
                        )
                        memory_context = [
                            {"content": c.content, "score": c.score, "source": c.source}
                            for c in memory_chunks
                        ]
                        span.set_attribute("memory_context.hits", len(memory_context))
                    except Exception as exc:
                        logger.debug("MemoryRouter.retrieve failed", error=str(exc))
            # ── End Memory Context Injection ─────────────────────────────

            intent = self._classify_intent_domain(request.query)
            assessment = self.self_model.introspect(request.query, intent)
            span.set_attribute("cognition.intent_domain", intent.value)
            span.set_attribute("cognition.capability_level", assessment.level.value)

            if assessment.level == CapabilityLevel.UNAVAILABLE:
                total_ms = int((time.monotonic() - t0) * 1000)
                if is_identity_user_query(request.query):
                    return KernelResponse(
                        content=CANONICAL_IDENTITY_RESPONSE,
                        session_id=request.session_id,
                        route="self_model_guard",
                        validation_score=1.0,
                        passed_validation=True,
                        hallucination_risk=0.0,
                        intent_category="identity",
                        intent_complexity="guarded",
                        context_latency_ms=0,
                        total_latency_ms=total_ms,
                        metadata={"capability_assessment": asdict(assessment), "identity_guard": True},
                    )
                return KernelResponse(
                    content=(
                        "抱歉，我目前无法处理这类请求。"
                        f"{assessment.reasoning}\n\n"
                        f"建议: {assessment.fallback_strategy or '请尝试换一种描述。'}"
                    ),
                    session_id=request.session_id,
                    route="self_model_guard",
                    validation_score=1.0,
                    passed_validation=True,
                    hallucination_risk=0.0,
                    intent_category=intent.value,
                    intent_complexity="guarded",
                    context_latency_ms=0,
                    total_latency_ms=total_ms,
                    metadata={"capability_assessment": asdict(assessment)},
                )

            identity_prompt = self.self_model.get_identity_prompt()

            # ── Feature ①: ContextComposer — compress long histories ──
            composed_ctx = None
            if bool(settings.kernel_context_composer_enabled) and request.history:
                try:
                    composer = self._get_context_composer()
                    composed_ctx = await composer.compose(
                        history=request.history,
                        current_query=request.query,
                        session_id=request.session_id,
                    )
                except Exception:
                    composed_ctx = None
            effective_history = composed_ctx.recent_turns if (composed_ctx and composed_ctx.compressed) else request.history
            memory_injection_query = composed_ctx.memory_injection_query if composed_ctx else request.query
            # ── End ContextComposer ────────────────────────────────────────

            from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

            orchestrator_v4 = CognitiveOrchestratorV4(
                timeout_sec=int(settings.kernel_agent_timeout_sec),
                max_parallel=int(settings.kernel_agent_max_parallel),
            )
            resp = await orchestrator_v4.process(
                OrchestratorV4Request(
                    query=request.query,
                    session_id=request.session_id,
                    user_id=request.user_id,
                    history=effective_history,
                    metadata={
                        **request.metadata,
                        "web_enabled": request.web_enabled,
                        "memory_injection_query": memory_injection_query,
                        "composed_context": composed_ctx.__dict__ if composed_ctx else None,
                        "identity_prompt": identity_prompt,
                        "memory_context": memory_context,
                    },
                    trace_ctx=trace_ctx,
                    conversation_state=request.conversation_state,
                )
            )

            if sid and is_identity_user_query(request.query) and resp.content:
                cache_identity_answer(sid, request.query, resp.content)

            # Store in semantic cache for future hits
            if settings.kernel_semantic_cache_enabled and resp.content:
                await self._get_semantic_cache().store(request.query, resp.content)

            # ── Save turns to WorkingMemory + EpisodicMemory ────────────
            if settings.kernel_memory_context_enabled and sid and resp.content:
                try:
                    wm = get_or_create_session_memory(sid)
                    wm.add_turn("user", request.query)
                    wm.add_turn("assistant", resp.content)
                except Exception:
                    pass
                try:
                    from memory.episodic_memory.episodic_memory import EpisodicMemory
                    episodic = EpisodicMemory(sid)
                    await episodic.record(
                        "turn",
                        json.dumps({"q": request.query, "a": resp.content[:500]}, ensure_ascii=False),
                    )
                except Exception:
                    pass
                # Async semantic write-back (non-blocking, fire-and-forget)
                try:
                    router = self._get_memory_router()
                    await router.store(
                        session_id=sid,
                        query=request.query,
                        answer=resp.content[:2000],
                        metadata={"user_id": request.user_id, "route": resp.route},
                    )
                except Exception:
                    pass
            # ── End turn saving ──────────────────────────────────────────

            # ── Feature ③: Active Memory Detection ─────────────────────
            if sid and request.user_id:
                memory_intent = self._detect_active_memory_intent(request.query)
                if memory_intent:
                    asyncio.create_task(
                        self._persist_active_memory(request.user_id, memory_intent, sid)
                    )
            # ── End Active Memory Detection ───────────────────────────

            total_ms = int((time.monotonic() - t0) * 1000)
            span.set_attribute("total.latency_ms", total_ms)
            span.set_attribute("validation.score", resp.validation_score)

            resp_metadata = resp.metadata or {}
            execution_graph = resp_metadata.get("execution_graph")
            return KernelResponse(
                content=resp.content,
                session_id=request.session_id,
                route=resp.route,
                validation_score=resp.validation_score,
                passed_validation=resp.passed_validation,
                hallucination_risk=resp.hallucination_risk,
                intent_category=resp.intent_category,
                intent_complexity="loop",
                context_latency_ms=0,
                total_latency_ms=total_ms,
                metadata={
                    **resp_metadata,
                    "execution_graph": execution_graph,
                },
                state_patch=resp.state_patch,
                result_refs=resp.result_refs,
            )

    # ── Streaming ─────────────────────────────────────────────────────
    async def stream(self, request: KernelRequest) -> AsyncIterator[dict[str, Any]]:
        """SSE 路径：统一走稳定 V4。"""
        sid = request.session_id
        is_multi = self._is_multi_question(request.query)

        if sid and is_identity_user_query(request.query) and not is_multi:
            cached = get_cached_identity_answer(sid)
            if cached:
                async for event in _emit_streaming_answer(
                    cached,
                    reasoning_step={"type": "reasoning_step", "data": {"id": "identity_reason", "stage": "REASON", "content": "命中身份记忆，直接返回缓存答案", "node_id": "node_identity", "status": "done"}},
                ):
                    yield event
                return

        trace_ctx = request.trace_ctx or trace_context_for_request(
            request_id=request.metadata.get("request_id", sid),
            session_id=sid,
            user_id=request.user_id,
        )

        # ── V5 Routing Tier (streaming) ──────────────────────────────────
        force_mode_from_meta: str | None = request.metadata.get("force_mode")
        has_stream_attachments = bool(request.metadata.get("attachment_contexts"))
        if force_mode_from_meta:
            pass  # Skip V5 — explicit force_mode from slash command
        elif has_stream_attachments:
            pass  # Skip V5 — attachment contexts require full orchestrator
        elif settings.kernel_v5_routing_enabled:
            # L0: Rule Router
            if settings.kernel_l0_rule_router_enabled:
                l0_result = await self._get_l0_router().route(
                    request.query, sid, is_multi=is_multi
                )
                if l0_result.hit and l0_result.answer is not None:
                    if l0_result.route == "force_mode":
                        # Slash command — re-enter as force_mode via orchestrator
                        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request
                        orchestrator = CognitiveOrchestratorV4(
                            timeout_sec=int(settings.kernel_agent_timeout_sec),
                            max_parallel=int(settings.kernel_agent_max_parallel),
                        )
                        yield {"type": "reasoning_step", "data": {"id": "l0_slash", "stage": "ROUTE", "content": f"L0 斜杠命令: {l0_result.force_mode}", "node_id": "node_l0", "status": "done"}}
                        async for event in orchestrator.stream(
                            OrchestratorV4Request(
                                query=l0_result.answer,
                                session_id=request.session_id,
                                user_id=request.user_id,
                                history=request.history,
                                metadata={
                                    **request.metadata,
                                    "web_enabled": request.web_enabled,
                                    "force_mode": l0_result.force_mode,
                                },
                                trace_ctx=trace_ctx,
                                conversation_state=request.conversation_state,
                            ),
                        ):
                            yield event
                        return

                    # ── Enriched identity via MinShort 0.6B (streaming) ──
                    if l0_result.route == "identity" and settings.kernel_enriched_identity_enabled:
                        try:
                            from kernel.identity.enriched_identity import generate_enriched_identity
                            wm_turns = []
                            if sid:
                                try:
                                    wm_turns = get_or_create_session_memory(sid).to_messages()
                                except Exception:
                                    pass
                            enriched = await generate_enriched_identity(
                                query=request.query,
                                user_id=request.user_id,
                                user_preferences=request.metadata.get("user_preferences", []),
                                recent_history=wm_turns or request.history,
                            )
                            l0_result.answer = enriched
                            l0_result.metadata["enriched"] = True
                        except Exception as exc:
                            logger.debug("Enriched identity failed (stream), using canned", error=str(exc))

                    async for event in _emit_streaming_answer(
                        l0_result.answer,
                        reasoning_step={"type": "reasoning_step", "data": {"id": "l0_route", "stage": "ROUTE", "content": f"L0 规则匹配: {l0_result.route}", "node_id": "node_l0", "status": "done"}},
                    ):
                        yield event
                    return

            # L0.5: Semantic Cache
            if settings.kernel_semantic_cache_enabled and not is_multi:
                cached = await self._get_semantic_cache().lookup(request.query)
                if cached and cached.answer:
                    async for event in _emit_streaming_answer(
                        cached.answer,
                        reasoning_step={"type": "reasoning_step", "data": {"id": "cache_hit", "stage": "ROUTE", "content": "语义缓存命中", "node_id": "node_cache", "status": "done"}},
                    ):
                        yield event
                    return

            # L1: Tiny Router
            if settings.kernel_l1_tiny_router_enabled and not is_multi:
                complexity = self._get_complexity_engine().assess(request.query)
                if complexity.recommended_pipeline in ("L0", "L1"):
                    l1_result = await self._get_tiny_router().route(request.query, request.history)
                    if l1_result.route != "complex" and l1_result.answer:
                        async for event in _emit_streaming_answer(
                            l1_result.answer,
                            reasoning_step={"type": "reasoning_step", "data": {"id": "l1_route", "stage": "ROUTE", "content": f"L1 路由: {l1_result.route}", "node_id": "node_l1", "status": "done"}},
                        ):
                            yield event
                        return
        # ── End V5 Routing Tier ──────────────────────────────────────────

        # ── Memory Context Injection (streaming) ──────────────────────────
        memory_context_stream: list[dict[str, Any]] = []
        if settings.kernel_memory_context_enabled and sid:
            episodic_chunks_stream: list[str] = []
            keyword_chunks_stream: list[str] = []

            # Episodic memory (Redis-backed, best-effort)
            try:
                from memory.episodic_memory.episodic_memory import EpisodicMemory

                episodic = EpisodicMemory(sid)
                episodic_events = await episodic.recall(last_n=20)
                for e in episodic_events:
                    try:
                        inner = json.loads(e.get("content", "{}"))
                        if isinstance(inner, dict):
                            q = inner.get("q", "")
                            a = inner.get("a", "")
                            if q and a:
                                episodic_chunks_stream.append(f"Q: {q}\nA: {a[:300]}")
                            else:
                                episodic_chunks_stream.append(e.get("content", "")[:500])
                        else:
                            episodic_chunks_stream.append(str(inner)[:500])
                    except (json.JSONDecodeError, TypeError):
                        episodic_chunks_stream.append(str(e.get("content", ""))[:500])
            except Exception:
                pass

            # Working memory turns (in-process, always available)
            try:
                wm = get_or_create_session_memory(sid)
                keyword_chunks_stream = [
                    f"user: {t.content}" if t.role == "user" else f"assistant: {t.content}"
                    for t in wm.get_turns(last_n=8)
                ] + request.metadata.get("user_preferences", [])
            except Exception:
                pass

            # Semantic memory retrieval
            if episodic_chunks_stream or keyword_chunks_stream:
                try:
                    memory_chunks = await self._get_memory_router().retrieve(
                        query=request.query,
                        episodic_chunks=episodic_chunks_stream,
                        keyword_chunks=keyword_chunks_stream,
                        top_k=8,
                    )
                    memory_context_stream = [
                        {"content": c.content, "score": c.score, "source": c.source}
                        for c in memory_chunks
                    ]
                except Exception as exc:
                    logger.debug("MemoryRouter.retrieve failed (stream)", error=str(exc))
        # ── End Memory Context Injection ─────────────────────────────────

        # ── Feature ①: ContextComposer — compress long histories (stream path) ──
        composed_ctx_stream = None
        if bool(settings.kernel_context_composer_enabled) and request.history:
            try:
                composer = self._get_context_composer()
                composed_ctx_stream = await composer.compose(
                    history=request.history,
                    current_query=request.query,
                    session_id=request.session_id,
                )
            except Exception:
                composed_ctx_stream = None
        effective_history_stream = composed_ctx_stream.recent_turns if (composed_ctx_stream and composed_ctx_stream.compressed) else request.history
        memory_injection_query_stream = composed_ctx_stream.memory_injection_query if composed_ctx_stream else request.query
        # ── End ContextComposer ────────────────────────────────────────────

        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        try:
            orchestrator = CognitiveOrchestratorV4(
                timeout_sec=int(settings.kernel_agent_timeout_sec),
                max_parallel=int(settings.kernel_agent_max_parallel),
            )
            final_content = None
            async for event in orchestrator.stream(
                OrchestratorV4Request(
                    query=request.query,
                    session_id=request.session_id,
                    user_id=request.user_id,
                    history=effective_history_stream,
                    metadata={
                        **request.metadata,
                        "web_enabled": request.web_enabled,
                        "memory_context": memory_context_stream,
                        "memory_injection_query": memory_injection_query_stream,
                        "composed_context": composed_ctx_stream.__dict__ if composed_ctx_stream else None,
                    },
                    trace_ctx=trace_ctx,
                    conversation_state=request.conversation_state,
                ),
            ):
                if event.get("type") == "final_answer":
                    data = event.get("data", {})
                    final_content = data.get("content") if isinstance(data, dict) else None
                    # state_patch / result_refs flow through in the event data,
                    # persistence is handled by the caller (chat.py)
                yield event

            # Store in semantic cache after streaming completes
            if settings.kernel_semantic_cache_enabled and final_content:
                await self._get_semantic_cache().store(request.query, final_content)

            # ── Save turns to WorkingMemory + EpisodicMemory ────────────
            if settings.kernel_memory_context_enabled and sid and final_content:
                try:
                    wm = get_or_create_session_memory(sid)
                    wm.add_turn("user", request.query)
                    wm.add_turn("assistant", final_content)
                except Exception:
                    pass
                try:
                    from memory.episodic_memory.episodic_memory import EpisodicMemory
                    episodic = EpisodicMemory(sid)
                    await episodic.record(
                        "turn",
                        json.dumps({"q": request.query, "a": final_content[:500]}, ensure_ascii=False),
                    )
                except Exception:
                    pass
                # Async semantic write-back (non-blocking, fire-and-forget)
                try:
                    router = self._get_memory_router()
                    await router.store(
                        session_id=sid,
                        query=request.query,
                        answer=final_content[:2000],
                        metadata={"user_id": request.user_id},
                    )
                except Exception:
                    pass
            # ── End turn saving ──────────────────────────────────────────

            # ── Feature ③: Active Memory Detection (stream path) ──────
            if sid and request.user_id:
                memory_intent = self._detect_active_memory_intent(request.query)
                if memory_intent:
                    asyncio.create_task(
                        self._persist_active_memory(request.user_id, memory_intent, sid)
                    )
            # ── End Active Memory Detection ───────────────────────────
        except Exception as exc:  # noqa: BLE001
            if is_identity_user_query(request.query):
                async for event in _emit_streaming_answer(CANONICAL_IDENTITY_RESPONSE):
                    yield event
                return
            yield {"type": "error", "data": {"message": str(exc)}}
        return

    # ── Active Memory Detection ──────────────────────────────────────
    _ACTIVE_MEMORY_PATTERNS = [
        "记住", "记下", "记录下来", "别忘了", "提醒我",
        "我更喜欢", "我喜欢", "我偏好", "我习惯", "我常用",
        "保存下来", "存下来", "记录下来",
    ]

    def _detect_active_memory_intent(self, query: str) -> str | None:
        """Detect explicit memory-write requests like "记住，我更喜欢简洁的回答".

        Returns the extracted memory content or None.
        """
        q = (query or "").strip()
        if not any(p in q for p in self._ACTIVE_MEMORY_PATTERNS):
            return None
        # Extract the content after memory keywords
        for kw in ["记住，", "记住,", "记住 ", "记住", "记下，", "记下,", "记下 "]:
            if kw in q:
                idx = q.index(kw) + len(kw)
                content = q[idx:].strip().rstrip("。，,.!！？?")
                if content:
                    return content
        return q if len(q) > 5 else None

    async def _persist_active_memory(
        self, user_id: str, content: str, session_id: str
    ) -> None:
        """Write a user memory fact to the database."""
        try:
            from infra.storage.database import AsyncSessionLocal
            from infra.storage.models import UserMemory

            async with AsyncSessionLocal() as db:
                memory = UserMemory(
                    id=str(uuid.uuid4()),
                    user_id=user_id,
                    memory_type="semantic",
                    kind="preference",
                    title=(content[:64] + ("…" if len(content) > 64 else "")),
                    content=content,
                    enabled=True,
                    pinned=False,
                    score=0.7,  # Explicitly written memories start higher
                    access_count=1,
                    last_accessed_at=__import__("datetime").datetime.utcnow(),
                )
                db.add(memory)
                await db.commit()
                logger.debug("Active memory persisted", user_id=user_id, content=content[:80])
        except Exception as exc:
            logger.debug("Active memory persist failed", error=str(exc))

    # ── Helpers ───────────────────────────────────────────────────────
    def _classify_intent_domain(self, query: str) -> TaskDomain:
        q = (query or "").lower()
        # SQL generation intent (user wants to *write* SQL, not execute)
        if any(k in q for k in ["帮我写一段sql", "帮我写个sql", "帮我写sql", "写一个sql", "写一段sql", "写sql", "生成sql", "sql语句", "sql代码"]):
            return TaskDomain.GENERAL_QA
        if any(k in q for k in ["查询", "统计", "报表", "销量", "订单", "数据库"]):
            return TaskDomain.DATA_QUERY
        if any(k in q for k in ["文档", "手册", "pdf", "doc", "附件", "总结文档", "根据文档"]):
            return TaskDomain.DOCUMENT_RETRIEVAL
        if any(k in q for k in ["最新", "新闻", "今天", "实时", "联网", "搜索", "weather"]):
            return TaskDomain.WEB_SEARCH
        if any(k in q for k in ["执行", "工具", "调用", "计算", "时间", "天气"]):
            return TaskDomain.TOOL_EXECUTION
        return TaskDomain.GENERAL_QA

    # ── Multi-question detection ────────────────────────────────────────
    _MULTI_Q_HINTS = [
        "第一个", "第二个", "第三个", "第一", "第二", "第三",
        "并告诉我", "同时告诉我", "另外", "此外", "还有",
        "再分析", "再查询", "再告诉我",
    ]
    _DOMAIN_DATA_KW = ["查询", "统计", "报表", "销量", "订单", "数据库", "sql", "表", "字段", "列", "聚合", "分组", "金额", "收入", "分布", "图表"]
    _DOMAIN_RAG_KW = ["文档", "手册", "知识库", "总结", "归纳", "pdf", "doc", "附件", "政策", "规范", "记忆", "读取", ".pdf", ".doc", ".docx"]
    _DOMAIN_WEB_KW = ["最新", "新闻", "今天", "实时", "联网", "搜索", "weather", "气温", "降雨", "资讯"]
    _DOMAIN_TOOL_KW = ["时间", "几点", "天气", "计算", "代码", "执行", "翻译", "画图"]
    _FACTUAL_Q_PATTERNS = ["首都", "国家", "哪里", "是谁", "哪个", "什么时候", "多少", "多大", "多远", "什么", "位于", "属于"]

    def _classify_sub_question_domain(self, text: str) -> str:
        t = (text or "").lower()
        scores = {"data_query": 0, "document_retrieval": 0, "web_search": 0, "tool_execution": 0, "general_qa": 0}
        for kw in self._DOMAIN_DATA_KW:
            if kw in t:
                scores["data_query"] += 1
        for kw in self._DOMAIN_RAG_KW:
            if kw in t:
                scores["document_retrieval"] += 1
        for kw in self._DOMAIN_WEB_KW:
            if kw in t:
                scores["web_search"] += 1
        for kw in self._DOMAIN_TOOL_KW:
            if kw in t:
                scores["tool_execution"] += 1
        # Factual/trivia patterns: if the question looks like a factual query
        # AND no document/data signals are present, boost web_search.
        has_factual = any(p in t for p in self._FACTUAL_Q_PATTERNS)
        if has_factual and scores["document_retrieval"] == 0 and scores["data_query"] == 0:
            scores["web_search"] = max(scores["web_search"], 2)
        best = max(scores, key=scores.get)
        return best if scores[best] > 0 else "general_qa"

    def _is_multi_question(self, query: str) -> bool:
        """Detect whether a query contains multiple sub-questions."""
        q = (query or "").strip()

        # Strongest signal: multiple question marks — check before length filter
        qm_count = q.count("？") + q.count("?")
        if qm_count >= 2:
            return True

        # Length filter: very short queries can't be multi-question
        if len(q) < 15:
            return False

        # Check hints (并告诉我, 同时, 另外, etc.)
        if any(hint in q for hint in self._MULTI_Q_HINTS):
            return True

        # Check IntentEngine's multi_step flag
        try:
            intent = self._get_intent_engine().parse(q)
            if intent.multi_step:
                return True
        except Exception:
            pass

        return False

    def _split_by_syntax(self, query: str) -> list[str] | None:
        """Attempt syntax-based splitting. Returns list of sub-question texts or None."""
        q = (query or "").strip()

        # Try question marks first — the most explicit delimiter
        qm_parts = re.split(r"[？?]\s*", q)
        qm_parts = [s.strip() for s in qm_parts if s.strip() and len(s.strip()) > 2]
        if len(qm_parts) >= 2:
            return qm_parts

        # Try numbered patterns: "1. xxx 2. xxx" or "第一... 第二..."
        numbered = re.split(r"(?:^|\n)\s*(?:\d+[\.\、\)]|第[一二三四五六七八九])", q)
        numbered = [s.strip() for s in numbered if s.strip() and len(s.strip()) > 5]
        if len(numbered) >= 2:
            return numbered

        # Try Chinese semicolons
        if "；" in q:
            parts = [s.strip() for s in q.split("；") if s.strip() and len(s.strip()) > 5]
            if len(parts) >= 2:
                return parts

        # Try "并" / "同时" / "另外" as logical connectors between questions
        logical_split = re.split(r"[，,]\s*(?:并|同时|另外|此外|还有)\s*", q)
        logical_split = [s.strip() for s in logical_split if s.strip() and len(s.strip()) > 8]
        if len(logical_split) >= 2:
            return logical_split

        return None

    async def _split_by_llm(self, query: str) -> list[dict[str, str]] | None:
        """Use PLANNING LLM to split a complex query into sub-questions."""
        from model.llm_adapter.base import LLMMessage
        from model.model_gateway.gateway import LLMRole

        prompt = (
            "你是一个问题分解器。将用户的复合问题拆分为独立的子问题列表，输出 JSON。\n"
            "规则：\n"
            "- 每个子问题应是一个独立、可单独回答的完整问题。\n"
            "- domain 必须从以下选项中选择：\n"
            "  · data_query — 数据库查询、统计、报表等\n"
            "  · document_retrieval — 文档检索、知识库、总结归纳\n"
            "  · web_search — 联网搜索、新闻、实时信息\n"
            "  · tool_execution — 时间、天气、计算、代码执行\n"
            "  · general_qa — 通用问答、分析、建议\n"
            "- 如果用户只提了一个问题，返回包含该问题的单元素数组。\n"
            '- 输出格式：{"questions": [{"id": "q1", "text": "...", "domain": "..."}]}\n'
            f"用户输入：{query}"
        )
        try:
            gw = self._get_gateway()
            resp = await gw.complete(
                [LLMMessage(role="user", content=prompt)],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=400,
            )
            text = (resp.content or "").strip()
            m = re.search(r"\{.*\}", text, re.DOTALL)
            if not m:
                return None
            data = json.loads(m.group(0))
            questions = data.get("questions", [])
            if isinstance(questions, list) and len(questions) >= 2:
                # Apply keyword heuristic to validate/override LLM domains
                result = []
                for i, q_data in enumerate(questions):
                    if isinstance(q_data, dict):
                        text_val = q_data.get("text", "")
                        llm_domain = q_data.get("domain", "general_qa")
                        heuristic_domain = self._classify_sub_question_domain(text_val)
                        final_domain = heuristic_domain if heuristic_domain != "general_qa" else llm_domain
                        result.append({
                            "id": q_data.get("id", f"q{i+1}"),
                            "text": text_val,
                            "domain": final_domain,
                        })
                return result if len(result) >= 2 else None
        except Exception:
            pass
        return None

    async def _split_questions(self, query: str) -> list[dict[str, str]] | None:
        """Split a multi-question query into sub-questions. Returns None for single questions."""
        # Try syntax-based first
        parts = self._split_by_syntax(query)
        if parts and len(parts) >= 2:
            return [
                {"id": f"q{i+1}", "text": t, "domain": self._classify_sub_question_domain(t)}
                for i, t in enumerate(parts)
            ]

        # Fall back to LLM
        return await self._split_by_llm(query)

    def _map_complexity(self, complexity) -> str:
        """将 IntentEngine 的 complexity（float 或 str）统一为 simple/medium/complex。"""
        if isinstance(complexity, float):
            if complexity >= 0.7:
                return "complex"
            if complexity >= 0.4:
                return "medium"
            return "simple"
        return str(complexity)

    async def _select_tools(
        self, query: str, complexity: str, web_enabled: bool
    ) -> list[str]:
        """Step 3: 工具选择（PLANNING 小模型）。失败时回退到启发式规则。"""
        from model.llm_adapter.base import LLMMessage
        from model.model_gateway.gateway import LLMRole

        prompt = self._get_prompt_engine().build_tool_selection_prompt(
            query=query, complexity=complexity
        )
        try:
            resp = await self._get_gateway().complete(
                messages=[LLMMessage(role="user", content=prompt)],
                role=LLMRole.PLANNING,
                temperature=0.0,
                max_tokens=100,
            )
            m = re.search(r"\{.*?\}", resp.content, re.DOTALL)
            if m:
                data = json.loads(m.group(0))
                tools = data.get("tools", [])
                if isinstance(tools, list):
                    out = [str(t) for t in tools if t]
                    if web_enabled and "web_search" not in out:
                        out.append("web_search")
                    return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("Tool selection model fallback", error=str(exc))

        # Heuristic fallback
        out: list[str] = []
        q = query.lower()
        if web_enabled:
            out.append("web_search")
        if any(k in q for k in ["计算", "math", "+", "-", "*", "/", "计算器"]):
            out.append("calculator")
        if any(k in q for k in ["时间", "time", "日期", "date"]):
            out.append("datetime")
        if complexity == "complex" and "planner" not in out:
            out.append("planner")
        return out

    async def _reflect(self, query: str, answer: str) -> str:
        """Step 5: 反思优化。"""
        from model.llm_adapter.base import LLMMessage
        from model.model_gateway.gateway import LLMRole

        reflect_prompt = self._get_prompt_engine().build_reflection_prompt(
            query=query,
            answer=answer,
        )
        try:
            resp = await self._get_gateway().complete(
                messages=[LLMMessage(role="user", content=reflect_prompt)],
                role=LLMRole.QUERY,
                temperature=0.2,
                max_tokens=4096,
            )
            return resp.content.strip() or answer
        except Exception as exc:  # noqa: BLE001
            logger.debug("Reflection fallback to draft", error=str(exc))
            return answer

    async def _execute_plugins(self, plugins: list[Any], query: str, ctx: Any) -> list[Any]:
        """Use DAG engine for plugin parallelism with fallback."""
        try:
            from execution.dag_engine.engine import DAGEngine
            from execution.dag_engine.graph import Task, ResourceType

            tasks: list[Task] = []
            for p in plugins:
                pid = f"plugin_{getattr(p, 'name', 'unknown')}"

                async def _fn(task, runtime_ctx, plugin=p):
                    return await plugin.execute(query, ctx)

                tasks.append(
                    Task(
                        task_id=pid,
                        fn=_fn,
                        deps=[],
                        timeout=20.0,
                        retries=0,
                        resource=ResourceType.IO,
                        task_type="plugin",
                    )
                )

            results = await DAGEngine().execute(tasks, context={})
            out = [v for k, v in results.items() if not k.startswith("__err_") and hasattr(v, "content")]
            return out
        except Exception as exc:  # noqa: BLE001
            logger.debug("DAG plugin execution fallback", error=str(exc))
            plugin_results = await asyncio.gather(
                *[p.execute(query, ctx) for p in plugins],
                return_exceptions=True,
            )
            return [
                r for r in plugin_results
                if not isinstance(r, Exception) and hasattr(r, "content")
            ]

    async def _publish_event(self, channel: str, payload: dict[str, Any]) -> None:
        """Publish async event to message bus; best effort only."""
        try:
            from infra.message_bus.bus import bus

            await bus.publish(channel, payload)
        except Exception as exc:  # noqa: BLE001
            logger.debug("Event publish skipped", channel=channel, error=str(exc))
