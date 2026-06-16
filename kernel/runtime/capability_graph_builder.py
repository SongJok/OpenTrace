"""
CapabilityGraphBuilder — 将 ExecutionPlan 转换为可执行的 ExecutionGraph。

通过 CapabilityRegistry 将 capability_type 映射到具体执行器，
优化拓扑（并行化、资源分配），并生成包含节点、边和预算的
可执行 ExecutionGraph。

一次 LLM 调用用于能力→执行器映射 + 拓扑优化。
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.runtime.objects import ExecutionBudget, ExecutionEdge, ExecutionNode, ExecutionPlan

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)

# 能力 → 执行器类型映射（不需要 LLM 时的后备）
_CAPABILITY_EXECUTOR_MAP: dict[str, str] = {
    "data.query": "agent",
    "data.analysis": "agent",
    "web.search": "agent",
    "rag.retrieve": "agent",
    "tool.datetime": "tool",
    "tool.weather": "tool",
    "tool.calculator": "tool",
    "python.execute": "tool",
    "chart.generate": "tool",
    "memory.retrieve": "agent",
    "skill.invoke": "agent",
    "rule.lookup": "agent",
    "vision.analyze": "agent",
    "entity.resolution": "agent",
}


class CapabilityGraphBuilder:
    """从 ExecutionPlan 构建 ExecutionGraph。

    将规划器的能力分配转换为具体执行节点，包含已解析的执行器、
    资源预算和优化后的拓扑。
    """

    def __init__(self, capability_registry: Any = None) -> None:
        self._capability_registry = capability_registry

    async def build(self, plan: ExecutionPlan) -> list[ExecutionNode]:
        """将 ExecutionPlan 转换为可执行的 ExecutionNodes。

        快速路径：小型计划（1-2 个子任务）— 直接解析，不调用 LLM。
        LLM 路径：复杂计划 — 一次 LLM 调用进行拓扑优化。
        """
        from kernel.runtime.objects import ExecutionBudget, ExecutionNode

        if not plan.subtasks:
            logger.warning("CapabilityGraphBuilder received empty plan")
            return []

        # ── 快速路径：简单计划不需要 LLM 拓扑优化 ──
        if len(plan.subtasks) <= 2:
            logger.debug("CapabilityGraphBuilder fast path", subtask_count=len(plan.subtasks))
            return self._build_direct(plan)

        # ── LLM 路径：复杂计划的拓扑优化 ──
        try:
            return await self._build_via_llm(plan)
        except Exception as exc:
            logger.error("CapabilityGraphBuilder LLM failed, falling back to direct", error=str(exc))
            return self._build_direct(plan)

    def _build_direct(self, plan: ExecutionPlan) -> list[ExecutionNode]:
        """直接映射，不调用 LLM — 使用硬编码执行器映射。"""
        from kernel.runtime.objects import ExecutionBudget, ExecutionNode

        nodes: list[ExecutionNode] = []
        for task in plan.subtasks:
            executor_type = _CAPABILITY_EXECUTOR_MAP.get(
                task.capability_type,
                _infer_executor_type(task.capability_type),
            )
            resource = _infer_resource(task.capability_type)

            nodes.append(ExecutionNode(
                node_id=task.task_id,
                capability_name=task.capability_type,
                executor_type=executor_type,
                query=task.query,
                params=task.params,
                depends_on=list(task.depends_on),
                resource=resource,
                priority=task.priority,
                budget=ExecutionBudget(
                    max_tokens=4096,
                    max_latency_ms=30000,
                ),
                expected_evidence_schema={"type": task.expected_evidence_type},
            ))

        logger.debug("CapabilityGraphBuilder direct build", node_count=len(nodes))
        return nodes

    async def _build_via_llm(self, plan: ExecutionPlan) -> list[ExecutionNode]:
        """LLM 驱动的复杂计划拓扑优化。"""
        from kernel.runtime.objects import ExecutionBudget, ExecutionNode

        system_prompt = self._build_system_prompt()
        user_prompt = self._build_user_prompt(plan)

        from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

        gw = get_model_gateway()
        resp = await gw.complete(
            [
                LLMMessage(role="system", content=system_prompt),
                LLMMessage(role="user", content=user_prompt),
            ],
            role=LLMRole.QUERY,
            temperature=0.0,
            max_tokens=1000,
        )
        text = (resp.content or "").strip()

        return self._parse_graph(text, plan)

    def _build_system_prompt(self) -> str:
        return """你是 Capability Graph Builder。将 ExecutionPlan 优化为可执行的 ExecutionGraph。

## 你的任务
1. 将每个 capability_type 映射到 executor_type（agent/tool/model）
2. 分配 resource 类型（CPU/GPU/IO）
3. 设置合理的 budget（max_tokens, max_latency_ms）
4. 优化拓扑：标记可并行的节点，确认依赖关系正确

## 映射规则
- data.query / data.analysis → executor: agent, resource: CPU
- web.search → executor: agent, resource: IO
- rag.retrieve → executor: agent, resource: CPU
- tool.* → executor: tool, resource: CPU
- python.execute → executor: tool, resource: CPU
- chart.generate → executor: tool, resource: GPU
- memory.retrieve → executor: agent, resource: IO

## 输出格式（纯 JSON，无 markdown 包裹）
{
  "nodes": [
    {
      "node_id": "原始 task_id",
      "executor_type": "agent|tool|model",
      "resource": "CPU|GPU|IO",
      "max_tokens": 4096,
      "max_latency_ms": 30000
    }
  ]
}"""

    def _build_user_prompt(self, plan: ExecutionPlan) -> str:
        tasks_desc = []
        for t in plan.subtasks:
            tasks_desc.append(
                f"- {t.task_id}: capability={t.capability_type}, "
                f"priority={t.priority}, depends_on={t.depends_on}, "
                f"query={t.query[:200]}"
            )
        return (
            f"## ExecutionPlan\n"
            f"merge_strategy: {plan.merge_strategy}\n"
            f"risk_level: {plan.risk_level}\n\n"
            + "\n".join(tasks_desc)
        )

    def _parse_graph(self, text: str, plan: ExecutionPlan) -> list[ExecutionNode]:
        from kernel.runtime.objects import ExecutionBudget, ExecutionNode

        text = re.sub(r"^```(?:json)?\s*\n?", "", text.strip())
        text = re.sub(r"\n?\s*```\s*$", "", text)

        try:
            data = json.loads(text)
            llm_nodes = data.get("nodes", [])
        except json.JSONDecodeError:
            logger.warning("CapabilityGraphBuilder JSON parse failed")
            return self._build_direct(plan)

        # 按 task_id 索引原始任务
        task_map: dict[str, Any] = {t.task_id: t for t in plan.subtasks}
        nodes: list[ExecutionNode] = []

        for i, ln in enumerate(llm_nodes):
            node_id = ln.get("node_id", f"node_{i}")
            task = task_map.get(node_id)
            if task is None:
                # 尝试按索引查找
                if i < len(plan.subtasks):
                    task = plan.subtasks[i]
                else:
                    continue

            nodes.append(ExecutionNode(
                node_id=task.task_id,
                capability_name=task.capability_type,
                executor_type=str(ln.get("executor_type", _infer_executor_type(task.capability_type))),
                query=task.query,
                params=task.params,
                depends_on=list(task.depends_on),
                resource=str(ln.get("resource", _infer_resource(task.capability_type))),
                priority=task.priority,
                budget=ExecutionBudget(
                    max_tokens=int(ln.get("max_tokens", 4096)),
                    max_latency_ms=int(ln.get("max_latency_ms", 30000)),
                ),
                expected_evidence_schema={"type": task.expected_evidence_type},
            ))

        if not nodes:
            return self._build_direct(plan)

        logger.debug("CapabilityGraphBuilder LLM build", node_count=len(nodes))
        return nodes


def _infer_executor_type(capability_type: str) -> str:
    """从能力名称推断执行器类型。"""
    if capability_type.startswith("tool."):
        return "tool"
    if capability_type in ("python.execute", "chart.generate"):
        return "tool"
    return "agent"


def _infer_resource(capability_type: str) -> str:
    """从能力名称推断资源类型。"""
    if capability_type in ("web.search", "memory.retrieve"):
        return "IO"
    if capability_type == "chart.generate":
        return "GPU"
    return "CPU"
