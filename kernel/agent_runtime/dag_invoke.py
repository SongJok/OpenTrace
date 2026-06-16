"""Unified DAG agent resolution + Agent Runtime V3 invoke (tier-1 / tier-2)."""

from __future__ import annotations

import asyncio
from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from infra.config.settings import settings
from infra.observability.logger import get_logger
from kernel.runtime.objects import Evidence

logger = get_logger(__name__)


def _v3_enabled() -> bool:
    return bool(getattr(settings, "kernel_agent_runtime_v3_enabled", True))


def resolve_agent(
    agent_type: str,
    capability_registry: Any | None,
) -> BaseAgent | None:
    """Resolve tier-1 (CapabilityRegistry) then tier-2 (Data V2 nodes)."""
    key = (agent_type or "").lower()
    if capability_registry:
        try:
            return capability_registry.get_agent(key)
        except KeyError:
            pass
    try:
        from kernel.agent_runtime.tier2_registry import tier2_registry

        if tier2_registry.has_agent(key):
            return tier2_registry.get_agent(key)
    except Exception as exc:
        logger.debug("tier2 resolve skipped", agent_type=key, error=str(exc))
    return None


def execution_context_from_runtime(ctx: Any | None) -> dict[str, str]:
    md = dict(getattr(ctx, "metadata", None) or {}) if ctx else {}
    goal_id = ""
    gg = md.get("goal_graph") or {}
    if isinstance(gg, dict):
        goal_id = str(gg.get("root_goal_id") or "")
    if not goal_id:
        goal_id = str(md.get("root_goal_id") or md.get("goal_id") or "")
    return {
        "session_id": str(getattr(ctx, "session_id", "") or "") if ctx else "",
        "user_id": str(getattr(ctx, "user_id", "") or "") if ctx else "",
        "goal_id": goal_id,
        "goal_description": str(md.get("protected_intent") or getattr(ctx, "query", "") or ""),
        "trace_id": str(md.get("request_id") or md.get("trace_id") or ""),
    }


async def invoke_agent_message(
    agent: BaseAgent,
    msg: TaskMessage,
    *,
    timeout_sec: float,
    ctx: Any | None = None,
    capability_type: str = "",
    evidence_bus: Any | None = None,
) -> AgentResult:
    """Execute agent with optional V3 contribution wrapping."""
    exec_ctx = execution_context_from_runtime(ctx)

    async def _run() -> AgentResult:
        if _v3_enabled():
            from kernel.agent_runtime.executor import agent_runtime_executor

            contrib = await agent_runtime_executor.execute_task(
                agent,
                msg,
                goal_id=exec_ctx["goal_id"],
                goal_description=exec_ctx["goal_description"],
                capability_type=capability_type,
                trace_id=exec_ctx["trace_id"],
                evidence_bus=evidence_bus,
            )
            return agent_runtime_executor.contribution_to_agent_result(contrib)
        return await agent.execute(msg)

    try:
        return await asyncio.wait_for(_run(), timeout=timeout_sec)
    except TimeoutError:
        return AgentResult(
            task_id=msg.task_id,
            agent_type=msg.agent_type,
            status="timeout",
            content="",
            error="timeout",
        )


async def invoke_capability_mode(
    agent: BaseAgent,
    msg: TaskMessage,
    *,
    timeout_sec: float,
    capability_name: str,
    ctx: Any | None = None,
) -> AgentResult:
    """execute_as_capability → AgentResult (Evidence list) with V3 metadata."""
    exec_ctx = execution_context_from_runtime(ctx)
    try:
        evidence_list: list[Evidence] = await asyncio.wait_for(
            agent.execute_as_capability(msg),
            timeout=timeout_sec,
        )
    except TimeoutError:
        return AgentResult(
            task_id=msg.task_id,
            agent_type=msg.agent_type,
            status="timeout",
            content="",
            error="timeout",
        )
    content = "\n\n".join(e.content for e in evidence_list if e.content) if evidence_list else ""
    result = AgentResult(
        task_id=msg.task_id,
        agent_type=msg.agent_type,
        status="success",
        content=content,
        confidence=(max(e.credibility_score for e in evidence_list) if evidence_list else 0.0),
        evidence_objects=evidence_list,
        metadata={
            "capability_name": capability_name,
            "evidence_count": len(evidence_list),
            "goal_id": exec_ctx["goal_id"],
            "request_id": exec_ctx["trace_id"],
        },
    )
    if _v3_enabled():
        from kernel.agent_runtime.contribution import contribution_from_agent_result
        from kernel.agent_runtime.executor import agent_runtime_executor

        contrib = contribution_from_agent_result(
            result,
            goal_id=exec_ctx["goal_id"],
            goal_description=exec_ctx["goal_description"],
            trace_id=exec_ctx["trace_id"],
        )
        return agent_runtime_executor.contribution_to_agent_result(contrib)
    return result


async def invoke_dag_agent(
    *,
    task_id: str,
    agent_type: str,
    query: str,
    params: dict[str, Any],
    capability_registry: Any | None,
    ctx: Any | None,
    timeout_sec: float,
    capability_executor_mode: bool = False,
    capability_name: str = "",
    evidence_bus: Any | None = None,
) -> AgentResult:
    """Single entry for DAG graph task functions."""
    exec_ctx = execution_context_from_runtime(ctx)
    merged_params = dict(params or {})
    if ctx is not None:
        try:
            from kernel.turn_enrichment import runtime_agent_params_from_context

            merged_params = {**runtime_agent_params_from_context(ctx), **merged_params}
        except Exception as exc:
            logger.debug("dag_invoke_enrichment_params_skipped", error=str(exc))
    merged_params.setdefault("session_id", exec_ctx["session_id"])
    merged_params.setdefault("user_id", exec_ctx["user_id"])
    if exec_ctx["goal_id"]:
        merged_params.setdefault("goal_id", exec_ctx["goal_id"])

    agent = resolve_agent(agent_type, capability_registry)
    if agent is None:
        return AgentResult(
            task_id=task_id,
            agent_type=agent_type,
            status="error",
            content="",
            error=f"agent not found: {agent_type}",
        )

    msg = TaskMessage(
        task_id=task_id,
        agent_type=agent_type,
        query=query,
        params=merged_params,
        session_id=exec_ctx["session_id"] or None,
        user_id=exec_ctx["user_id"] or None,
    )

    cap_name = capability_name or agent_type
    if capability_executor_mode and hasattr(agent, "execute_as_capability"):
        return await invoke_capability_mode(
            agent,
            msg,
            timeout_sec=timeout_sec,
            capability_name=cap_name,
            ctx=ctx,
        )

    from kernel.agent_runtime.manifest import get_manifest

    ctype = get_manifest().capability_type_for_agent(agent_type)
    return await invoke_agent_message(
        agent,
        msg,
        timeout_sec=timeout_sec,
        ctx=ctx,
        capability_type=ctype,
        evidence_bus=evidence_bus,
    )