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
from dataclasses import asdict, dataclass, field
from typing import Any, AsyncIterator, Optional

from infra.config.settings import settings
from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.cognition.self_model import SelfModel
from kernel.cognition.types import CapabilityLevel, TaskDomain
from kernel.identity.system_identity import CANONICAL_IDENTITY_RESPONSE, is_identity_user_query
from memory.working_memory.working_memory import (
    cache_identity_answer,
    get_cached_identity_answer,
)

logger = get_logger(__name__)
tracer = get_tracer(__name__)


@dataclass
class KernelRequest:
    query: str
    session_id: str = ""
    user_id: str = ""
    history: list[dict[str, str]] = field(default_factory=list)
    stream: bool = False
    web_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


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
            from memory.memory_router.router import MemoryRouter
            self._memory_router = MemoryRouter()
        return self._memory_router

    def _get_prompt_engine(self):
        from kernel.prompt_engine.cognitive_prompt import get_prompt_engine
        return get_prompt_engine()

    def _get_gateway(self):
        from model.model_gateway.gateway import get_model_gateway
        return get_model_gateway()

    # ── Main entry point ──────────────────────────────────────────────
    async def run(self, request: KernelRequest) -> KernelResponse:
        """同步执行：支持 v1/v2 编排器分流。"""
        from kernel.orchestrator import CognitiveOrchestrator, OrchestratorRequest

        t0 = time.monotonic()
        with tracer.start_as_current_span("cognitive_kernel.run") as span:
            sid = request.session_id
            if sid and is_identity_user_query(request.query):
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
                    history=request.history,
                    metadata={
                        **request.metadata,
                        "web_enabled": request.web_enabled,
                        "identity_prompt": identity_prompt,
                    },
                )
            )

            if sid and is_identity_user_query(request.query) and resp.content:
                cache_identity_answer(sid, request.query, resp.content)

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
            )

    # ── Streaming ─────────────────────────────────────────────────────
    async def stream(self, request: KernelRequest) -> AsyncIterator[dict[str, Any]]:
        """SSE 路径：统一走稳定 V4。"""
        sid = request.session_id
        if sid and is_identity_user_query(request.query):
            cached = get_cached_identity_answer(sid)
            if cached:
                yield {"type": "reasoning_step", "data": {"id": "identity_reason", "stage": "REASON", "content": "命中身份记忆，直接返回缓存答案", "node_id": "node_identity", "status": "done"}}
                yield {"type": "final_answer", "data": {"content": cached}}
                return

        from kernel.orchestrator_v4 import CognitiveOrchestratorV4, OrchestratorV4Request

        try:
            orchestrator = CognitiveOrchestratorV4(
                timeout_sec=int(settings.kernel_agent_timeout_sec),
                max_parallel=int(settings.kernel_agent_max_parallel),
            )
            resp_v2 = await orchestrator.process(
                OrchestratorV4Request(
                    query=request.query,
                    session_id=request.session_id,
                    user_id=request.user_id,
                    history=request.history,
                    metadata={
                        **request.metadata,
                        "web_enabled": request.web_enabled,
                    },
                )
            )
            adaptive_profile = (resp_v2.metadata or {}).get("adaptive_profile") or {}
            if adaptive_profile:
                yield {"type": "adaptive_profile", "data": adaptive_profile}
            force_mode = (resp_v2.metadata or {}).get("force_mode")
            if force_mode:
                yield {"type": "force_mode", "data": {"mode": force_mode}}
            for st in resp_v2.metadata.get("plan", {}).get("subtasks", []):
                agent_type = str(st.get("agent_type", "agent"))
                q = str(st.get("query", ""))
                node_id = f"{agent_type}_{abs(hash(q)) % 100000}"
                yield {"type": "dag_node_start", "data": {"node_id": node_id, "agent_type": agent_type, "depends_on": st.get("depends_on", [])}}
                yield {"type": "agent_start", "data": {"agent_type": agent_type, "task_id": node_id, "query": q}}
            for st in resp_v2.metadata.get("plan", {}).get("subtasks", []):
                agent_type = str(st.get("agent_type", "agent"))
                q = str(st.get("query", ""))
                yield {"type": "agent_progress", "data": {"agent_type": agent_type, "task_id": f"{agent_type}_{abs(hash(q)) % 100000}", "progress": 50, "message": "执行中"}}
            for ar in resp_v2.metadata.get("agent_results", []):
                agent_type = str(ar.get("agent_type", "agent"))
                task_id = str(ar.get("task_id", ""))
                yield {"type": "dag_node_complete", "data": {"node_id": task_id, "agent_type": agent_type, "status": str(ar.get("status", "success")), "preview": str(ar.get("content", ""))[:200]}}
                yield {"type": "agent_complete", "data": {"agent_type": agent_type, "task_id": task_id, "status": str(ar.get("status", "success")), "preview": str(ar.get("content", ""))[:200]}}
            conflict_summary = None
            for ann in (resp_v2.metadata or {}).get("annotations", []):
                if isinstance(ann, dict) and ann.get("id") == "conflict_summary":
                    conflict_summary = ann
                    break
            if conflict_summary:
                yield {"type": "conflict_summary", "data": conflict_summary}
            for p in resp_v2.metadata.get("phases", []):
                yield {"type": "reasoning_step", "data": {"id": f"v4_{p.get('phase', 'STEP')}", "stage": str(p.get("phase", "STEP")), "content": str(p), "node_id": None, "status": "done"}}
            answer_draft = str((resp_v2.metadata or {}).get("answer_draft", "")).strip()
            if answer_draft:
                yield {"type": "answer_draft", "data": {"content": answer_draft}}
            content = (resp_v2.content or answer_draft or str((resp_v2.metadata or {}).get("fusion", {}).get("context", "")).strip() or "").strip()
            if not content:
                content = "我已经完成了推理，但当前没有生成可展示的最终文本。请稍后重试，或尝试换一种更明确的问法。"
            if content:
                step = 24
                for i in range(0, len(content), step):
                    yield {"type": "delta", "data": {"text": content[i : i + step]}}
            yield {"type": "final_answer", "data": {"content": content, "execution_graph": (resp_v2.metadata or {}).get("execution_graph"), "citations": (resp_v2.metadata or {}).get("citations", []), "annotations": (resp_v2.metadata or {}).get("annotations", []), "metadata": resp_v2.metadata}}
        except Exception as exc:  # noqa: BLE001
            if is_identity_user_query(request.query):
                yield {"type": "final_answer", "data": {"content": CANONICAL_IDENTITY_RESPONSE, "execution_graph": None, "citations": [], "annotations": []}}
                return
            yield {"type": "error", "data": {"message": str(exc)}}
        return

        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

        async def emit(event: dict[str, Any]) -> None:
            await queue.put(event)

        async def run_orchestrator() -> None:
            try:
                orchestrator = CognitiveOrchestrator(
                    intent_engine=self._get_intent_engine(),
                    policy_engine=self._get_policy_engine(),
                    reasoning_engine=self._get_reasoning_engine(),
                    meta_cognition=self._get_meta_cognition(),
                    stream_event_cb=emit,
                )
                resp = await orchestrator.process(
                    OrchestratorRequest(
                        query=request.query,
                        session_id=request.session_id,
                        user_id=request.user_id,
                        history=request.history,
                        metadata={
                            **request.metadata,
                            "web_enabled": request.web_enabled,
                        },
                    )
                )

                if sid and is_identity_user_query(request.query) and resp.content:
                    cache_identity_answer(sid, request.query, resp.content)

                await queue.put(
                    {
                        "type": "final_answer",
                        "data": {
                            "content": resp.content,
                            "execution_graph": (resp.metadata or {}).get("execution_graph"),
                        },
                    }
                )
            except Exception as exc:  # noqa: BLE001
                await queue.put({"type": "error", "data": {"message": str(exc)}})
            finally:
                await queue.put(None)

        task = asyncio.create_task(run_orchestrator())
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                if event.get("type") == "reasoning_step":
                    data = event.get("data") or {}
                    content = str(data.get("content", "")).strip()
                    if content:
                        yield {"type": "thinking", "data": {"content": content}}
                    yield event
                    continue
                if event.get("type") == "final_answer":
                    data = event.get("data") or {}
                    content = str(data.get("content", ""))
                    if content:
                        step = 24
                        for i in range(0, len(content), step):
                            yield {"type": "delta", "data": {"text": content[i : i + step]}}
                    yield event
                    continue
                yield event
        finally:
            await task

    # ── Helpers ───────────────────────────────────────────────────────
    def _classify_intent_domain(self, query: str) -> TaskDomain:
        q = (query or "").lower()
        if any(k in q for k in ["查询", "统计", "报表", "销量", "订单", "sql", "数据库"]):
            return TaskDomain.DATA_QUERY
        if any(k in q for k in ["文档", "手册", "pdf", "doc", "附件", "总结文档", "根据文档"]):
            return TaskDomain.DOCUMENT_RETRIEVAL
        if any(k in q for k in ["最新", "新闻", "今天", "实时", "联网", "搜索", "weather"]):
            return TaskDomain.WEB_SEARCH
        if any(k in q for k in ["执行", "工具", "调用", "计算", "时间", "天气"]):
            return TaskDomain.TOOL_EXECUTION
        return TaskDomain.GENERAL_QA

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
