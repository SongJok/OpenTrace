"""
认知节点 — 为类型化 DAG 任务提供工厂辅助。

CognitiveNode 封装以下之一：
  reasoning — ReasoningEngine（Direct / CoT / ToT）
  tool      — ToolRouter 调度
  agent     — AgentRuntime 子运行
  model     — ModelGateway 原始调用
"""
from __future__ import annotations

from typing import Any, Optional

from execution.dag_engine.graph import NodeType, ResourceType, Task


def reasoning_node(
    task_id: str,
    query: str,
    strategy: str = "COT",
    context: str = "",
    deps: Optional[list[str]] = None,
    retries: int = 1,
    timeout: float = 60.0,
    priority: int = 0,
) -> Task:
    """DAG task that runs ReasoningEngine with dep-result context injection."""
    _q, _s, _c = query, strategy, context

    async def _fn(task: Task, ctx: dict[str, Any]) -> str:
        from kernel.reasoning.engine import ReasoningEngine
        merged = _c
        for dep in (deps or []):
            val = ctx.get(dep, "")
            if val:
                merged += f"\n[{dep}]: {str(val)[:400]}"
        result = await ReasoningEngine().run(query=_q, context=merged, strategy=_s)
        return result.answer

    return Task(
        task_id=task_id, fn=_fn, deps=deps or [],
        retries=retries, timeout=timeout, priority=priority,
        resource=ResourceType.CPU, node_type=NodeType.REASONING, task_type="reasoning",
    )


def tool_node(
    task_id: str,
    intent: str,
    deps: Optional[list[str]] = None,
    retries: int = 2,
    timeout: float = 30.0,
    priority: int = 0,
    **tool_kwargs: Any,
) -> Task:
    """DAG task that dispatches to ToolRouter."""
    _intent = intent
    _kwargs = tool_kwargs

    async def _fn(task: Task, ctx: dict[str, Any]) -> Optional[str]:
        from execution.tool_router.router import ToolRouter
        # Inject dep results as context kwargs
        merged_kwargs = dict(_kwargs)
        for dep in (deps or []):
            val = ctx.get(dep, "")
            if val:
                merged_kwargs.setdefault("context", str(val)[:400])
        return await ToolRouter().execute(intent=_intent, **merged_kwargs)

    return Task(
        task_id=task_id, fn=_fn, deps=deps or [],
        retries=retries, timeout=timeout, priority=priority,
        resource=ResourceType.IO, node_type=NodeType.TOOL, task_type="tool",
    )


def agent_node(
    task_id: str,
    query: str,
    deps: Optional[list[str]] = None,
    retries: int = 1,
    timeout: float = 120.0,
    priority: int = 0,
) -> Task:
    """DAG task that runs a full AgentRuntime sub-execution."""
    _q = query

    async def _fn(task: Task, ctx: dict[str, Any]) -> str:
        from agent_runtime.agent_runtime import AgentRuntime, RuntimeRequest
        dep_context = "\n".join(
            f"[{dep}]: {str(ctx.get(dep, ''))[:300]}"
            for dep in (deps or []) if ctx.get(dep)
        )
        req = RuntimeRequest(query=_q, context=dep_context)
        result = await AgentRuntime().run(req)
        return result.final_answer

    return Task(
        task_id=task_id, fn=_fn, deps=deps or [],
        retries=retries, timeout=timeout, priority=priority,
        resource=ResourceType.CPU, node_type=NodeType.AGENT, task_type="agent",
    )


def model_node(
    task_id: str,
    prompt: str,
    system: str = "",
    role: str = "query",
    deps: Optional[list[str]] = None,
    retries: int = 2,
    timeout: float = 30.0,
    priority: int = 0,
    temperature: float = 0.2,
    max_tokens: int = 1024,
) -> Task:
    """DAG task that calls ModelGateway directly."""
    _prompt, _system, _role = prompt, system, role
    _temp, _max_tok = temperature, max_tokens

    async def _fn(task: Task, ctx: dict[str, Any]) -> str:
        from model.llm_adapter.base import LLMMessage
        from model.model_gateway.gateway import LLMRole, get_model_gateway
        gw = get_model_gateway()
        messages = []
        if _system:
            messages.append(LLMMessage(role="system", content=_system))
        # Inject dep results
        for dep in (deps or []):
            val = ctx.get(dep, "")
            if val:
                messages.append(LLMMessage(role="user", content=f"[{dep}]: {str(val)[:400]}"))
        messages.append(LLMMessage(role="user", content=_prompt))
        try:
            llm_role = LLMRole(_role.lower())
        except ValueError:
            llm_role = LLMRole.QUERY
        resp = await gw.complete(messages=messages, role=llm_role,
                                  temperature=_temp, max_tokens=_max_tok)
        return resp.content

    return Task(
        task_id=task_id, fn=_fn, deps=deps or [],
        retries=retries, timeout=timeout, priority=priority,
        resource=ResourceType.CPU, node_type=NodeType.MODEL, task_type="model",
    )


def dynamic_node(
    task_id: str,
    fn: Any,
    deps: Optional[list[str]] = None,
    retries: int = 1,
    timeout: float = 60.0,
    priority: int = 0,
    resource: ResourceType = ResourceType.CPU,
) -> Task:
    """
    Dynamic DAG node — fn may return list[Task] to inject new tasks.
    The engine will automatically add returned tasks to the running DAG.
    """
    return Task(
        task_id=task_id, fn=fn, deps=deps or [],
        retries=retries, timeout=timeout, priority=priority,
        resource=resource, node_type=NodeType.GENERIC,
        task_type="dynamic", dynamic=True,
    )
