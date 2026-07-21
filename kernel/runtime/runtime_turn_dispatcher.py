"""
Runtime turn dispatch — lookup, lifecycle, execute, artifact return.

Used by RuntimeGateway after CognitiveSupervisor.prepare_run.
Does not build GoalGraph or run planning-phase governance (Supervisor owns that).
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import AsyncIterator
from typing import Any

from infra.observability.logger import get_logger
from kernel.identity.system_identity import finalize_assistant_content

logger = get_logger(__name__)

_STREAM_DELAY = 0.0


class RuntimeTurnDispatcher:
    """Runtime lookup → dispatch → KernelResponse / stream events."""

    async def run_turn(self, request: Any, prepared: Any, *, t0: float | None = None) -> Any:
        from kernel.cognitive_kernel import KernelResponse
        from kernel.cognitive_supervisor.run_outcomes import (
            executive_result_to_kernel_response,
            multi_question_to_kernel_response,
        )
        from kernel.runtime.registry import dispatch_runtime, ensure_runtimes_registered

        if not prepared.governance_meta.get("allowed", True):
            elapsed = int((time.monotonic() - (t0 or time.monotonic())) * 1000)
            route_hint = str(getattr(prepared, "route_hint", "") or "")
            route = (
                "control_plane_denied"
                if route_hint == "control_plane_denied"
                else "runtime_governance_denied"
            )
            meta = {
                "violations": prepared.governance_meta.get("violations", []),
                "control_plane": prepared.governance_meta.get("control_plane"),
            }
            return KernelResponse(
                content="请求未通过运行时治理检查，请调整参数后重试。",
                session_id=request.session_id,
                route=route,
                validation_score=1.0,
                passed_validation=False,
                hallucination_risk=0.0,
                intent_category="blocked",
                intent_complexity="guarded",
                total_latency_ms=elapsed,
                metadata=meta,
            )

        request.metadata = dict(request.metadata or {})
        request.metadata["goal_graph"] = prepared.goal_graph_dict
        request.metadata.setdefault("semantic_observability", {}).update(
            prepared.semantic_observability
        )

        runtime_name = self.resolve_runtime_name(request, prepared)
        if runtime_name == "multi_goal":
            mq = await self._try_multi_question(request)
            if mq is not None:
                total_ms = int((time.monotonic() - (t0 or time.monotonic())) * 1000)
                return multi_question_to_kernel_response(mq, request, total_ms)

        ensure_runtimes_registered()
        ctx = prepared.ctx
        result = await dispatch_runtime(
            runtime_name,
            request=request,
            ctx=ctx,
            query=request.query,
        )
        total_ms = int((time.monotonic() - (t0 or time.monotonic())) * 1000)
        if getattr(result, "route", None) == "registry_dispatch_denied":
            return result
        if ctx and ctx.metadata and ctx.metadata.get("governance"):
            request.metadata["governance"] = ctx.metadata["governance"]
        if runtime_name == "multi_goal" and hasattr(result, "content"):
            return multi_question_to_kernel_response(result, request, total_ms)
        return executive_result_to_kernel_response(result, request, total_ms, ctx=ctx)

    async def stream_turn(
        self, request: Any, prepared: Any
    ) -> AsyncIterator[dict[str, Any]]:
        from kernel.cognitive_supervisor.run_outcomes import multi_question_to_kernel_response

        if not prepared.governance_meta.get("allowed", True):
            yield {
                "type": "error",
                "data": {
                    "message": "control plane or runtime governance denied",
                    "violations": prepared.governance_meta.get("violations", []),
                    "control_plane": prepared.governance_meta.get("control_plane"),
                },
            }
            return

        request.metadata = dict(request.metadata or {})
        request.metadata["goal_graph"] = prepared.goal_graph_dict

        runtime_name = self.resolve_runtime_name(request, prepared)
        if runtime_name == "multi_goal":
            mq = await self._try_multi_question(request)
            if mq is not None:
                subs = (mq.metadata or {}).get("sub_questions") or []
                yield {
                    "type": "reasoning_step",
                    "data": {
                        "id": "multi_question_v2",
                        "stage": "ROUTE",
                        "content": f"多问题分解 ({len(subs)} 个子目标)",
                        "node_id": "node_multi_question",
                        "status": "done",
                    },
                }
                kr = multi_question_to_kernel_response(mq, request, 0)
                text = kr.content or ""
                if text:
                    yield {"type": "delta", "data": {"text": text}}
                mq_meta = dict(kr.metadata or {})
                mq_final: dict[str, Any] = {
                    "content": text,
                    "route": kr.route,
                    "validation_score": kr.validation_score,
                    "passed_validation": kr.passed_validation,
                    "metadata": mq_meta,
                    "state_patch": kr.state_patch,
                    "result_refs": kr.result_refs,
                }
                for key in (
                    "control_plane",
                    "shared_world_state",
                    "capabilities_used",
                    "prompt_tokens",
                    "completion_tokens",
                    "citations",
                    "evidence_refs",
                    "knowledge_operations",
                    "confidence",
                    "confidence_level",
                    "uncertainty",
                    "trace_id",
                ):
                    if key in mq_meta:
                        mq_final[key] = mq_meta[key]
                obs = mq_meta.get("semantic_observability") or {}
                if isinstance(obs, dict) and obs.get("enterprise_telemetry"):
                    mq_final["enterprise_telemetry"] = obs["enterprise_telemetry"]
                yield {"type": "final_answer", "data": mq_final}
                return

        ctx = prepared.ctx
        memory_context = request.metadata.get("memory_context") or []
        if memory_context and ctx and not getattr(ctx, "memory_context", None):
            ctx.memory_context = "\n".join(
                m.get("content", "") for m in memory_context[:8]
            )

        yield {
            "type": "reasoning_step",
            "data": {
                "id": "runtime_v2",
                "stage": "ROUTE",
                "content": f"Runtime: {runtime_name}",
                "node_id": "node_runtime_gateway",
                "status": "running",
            },
        }

        # Runtime capabilities report progress through an async callback. Run
        # the executive in a task and drain that callback queue immediately so
        # clients see tool/plan progress while the runtime is still working.
        pending: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        async def _collect(event: dict[str, Any]) -> None:
            await pending.put(event)

        execution = asyncio.create_task(
            self._stream_executive(request, prepared, runtime_name, _collect),
            name=f"runtime-stream:{getattr(request, 'session_id', 'unknown')}",
        )
        try:
            while not execution.done() or not pending.empty():
                if pending.empty():
                    await asyncio.wait({execution}, timeout=0.05)
                    continue
                yield await pending.get()
            content, stream_meta = await execution
        finally:
            if not execution.done():
                execution.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await execution
        content = finalize_assistant_content(content or "", getattr(request, "query", "") or "")
        if content:
            yield {"type": "delta", "data": {"text": content}}
        stream_meta.setdefault("cognitive_runtime_v2", True)
        stream_meta.setdefault("runtime_name", runtime_name)
        final_data: dict[str, Any] = {
            "content": content,
            "route": stream_meta.get("route", "cognitive_runtime_v2"),
            "validation_score": stream_meta.get("validation_score", 0.9),
            "passed_validation": stream_meta.get("passed_validation", True),
            "metadata": stream_meta,
        }
        for key in (
            "control_plane",
            "shared_world_state",
            "capabilities_used",
            "prompt_tokens",
            "completion_tokens",
            "goal_participation",
            "agent_runtime_v3",
            "cognitive_runtime_p3",
            "world_projection",
            "data_intelligence",
            "citations",
            "evidence_refs",
            "knowledge_operations",
            "confidence",
            "confidence_level",
            "uncertainty",
            "trace_id",
        ):
            if key in stream_meta:
                final_data[key] = stream_meta[key]
            elif key in (stream_meta.get("metadata") or {}):
                final_data[key] = stream_meta["metadata"][key]
        obs = stream_meta.get("semantic_observability") or {}
        if isinstance(obs, dict) and obs.get("enterprise_telemetry"):
            final_data["enterprise_telemetry"] = obs["enterprise_telemetry"]
        yield {"type": "final_answer", "data": final_data}

    def resolve_runtime_name(self, request: Any, prepared: Any) -> str:
        strategy = (request.metadata or {}).get("strategy_projection") or {}
        preferred = strategy.get("preferred_runtime", "cognitive_executive")
        lock = (request.metadata or {}).get("intent_lock") or {}
        allowed = set(lock.get("allowed_capabilities") or [])
        disallowed = set(lock.get("disallowed_capabilities") or [])
        data_ok = (
            ("data.query" in allowed or "data_query" in allowed)
            and "data.query" not in disallowed
            and "data_query" not in disallowed
        )
        if preferred == "data_intelligence" and not data_ok:
            preferred = "cognitive_executive"
            request.metadata = dict(request.metadata or {})
            request.metadata["strategy_projection"] = {
                **strategy,
                "preferred_runtime": "cognitive_executive",
                "data_intelligence_skipped": "intent_lock_disallows_data",
            }
        if preferred == "data_intelligence":
            return "data_intelligence"
        if preferred == "multi_goal":
            return "multi_goal"
        graph = prepared.goal_graph_dict or {}
        goals = graph.get("goals") if isinstance(graph, dict) else []
        if isinstance(goals, list) and len(goals) > 2:
            return "multi_goal"
        return "cognitive_executive"

    async def _try_multi_question(self, request: Any) -> Any | None:
        from kernel.runtime.multi_question_runtime import run_multi_question

        return await run_multi_question(request)

    async def _stream_executive(
        self,
        request: Any,
        prepared: Any,
        runtime_name: str,
        event_cb: Any,
    ) -> tuple[str, dict[str, Any]]:
        from kernel.cognitive_supervisor.run_outcomes import (
            build_runtime_artifact,
            build_stream_final_metadata,
        )
        from kernel.runtime.registry import dispatch_runtime, ensure_runtimes_registered

        ensure_runtimes_registered()
        ctx = prepared.ctx
        result = await dispatch_runtime(
            runtime_name,
            request=request,
            ctx=ctx,
            query=request.query,
            event_cb=event_cb,
        )
        if hasattr(result, "content"):
            text = (result.content or "").strip()
            meta = dict(getattr(result, "metadata", None) or {})
            try:
                from kernel.agent_runtime.stream_metadata import merge_agent_runtime_v3_into_metadata

                merge_agent_runtime_v3_into_metadata(meta, ctx=ctx, result_metadata=meta)
            except Exception as exc:
                from kernel.runtime.governance_hooks import degrade_ctx

                degrade_ctx(ctx, subsystem="stream_metadata", detail="merge_agent_runtime_v3", exc=exc)
            return text or "无法生成回答。", meta
        content = (getattr(result, "answer", None) or "").strip()
        if not content:
            content = "无法生成回答，请重试或补充信息。"
        if ctx and ctx.metadata and ctx.metadata.get("governance"):
            request.metadata["governance"] = ctx.metadata["governance"]
        artifact = build_runtime_artifact(result, request, ctx=ctx)
        stream_meta = build_stream_final_metadata(result, request, ctx, artifact)
        stream_meta["runtime_name"] = runtime_name
        return content, stream_meta


def get_runtime_turn_dispatcher() -> RuntimeTurnDispatcher:
    if not hasattr(get_runtime_turn_dispatcher, "_instance"):
        get_runtime_turn_dispatcher._instance = RuntimeTurnDispatcher()  # type: ignore[attr-defined]
    return get_runtime_turn_dispatcher._instance  # type: ignore[attr-defined]
