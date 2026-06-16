"""
执行投影 — 从 StrategyProjection → ExecutionPlan 的最终桥梁。

将能力分配 + 并行组转换为 ExecutionRuntime 可执行的具体
ExecutionNode 和 ExecutionEdge。

这是计划进入执行层之前的最后一个认知到执行映射步骤。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from .strategy_builder import CapabilityAssignment, StrategyProjection

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ProjectedCapability:
    """投影到执行层的单个能力调用。"""

    node_id: str = ""
    capability_type: str = ""
    executor_type: str = ""  # agent | tool | model
    query: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    priority: str = "normal"
    resource: str = "CPU"
    expected_evidence_type: str = "text"
    goal_id: str = ""
    max_tokens: int = 4096
    max_latency_ms: int = 30000


@dataclass
class ProjectionGroup:
    """一组可并行执行的投影能力。"""

    group_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    capabilities: list[ProjectedCapability] = field(default_factory=list)
    group_order: int = 0  # 执行顺序（从 0 开始）


@dataclass
class ExecutionProjection:
    """可供 ExecutionRuntime 使用的完整执行投影。

    映射为 kernel.runtime.objects.ExecutionPlan + ExecutionNode。
    """

    projection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    rewritten_query: str = ""
    intent_category: str = ""
    risk_level: str = "low"
    completion_criteria: str = ""

    # 按序排列的能力组
    groups: list[ProjectionGroup] = field(default_factory=list)

    # 所有节点的扁平列表
    all_nodes: list[ProjectedCapability] = field(default_factory=list)

    # 执行元数据
    merge_strategy: str = "union"
    max_parallel: int = 5
    total_estimated_latency_ms: int = 0
    total_estimated_tokens: int = 0

    metadata: dict[str, Any] = field(default_factory=dict)

    def to_execution_plan(self) -> Any:
        """转换为 kernel.runtime.objects.ExecutionPlan。"""
        from kernel.runtime.objects import ExecutionPlan, ExecutionTask

        tasks: list[ExecutionTask] = []
        for node in self.all_nodes:
            tasks.append(ExecutionTask(
                task_id=node.node_id,
                capability_type=node.capability_type,
                query=node.query,
                params=node.params,
                depends_on=node.depends_on,
                priority=node.priority,
                reason=f"projection from cognitive plan",
                expected_evidence_type=node.expected_evidence_type,
                goal_id=node.goal_id or "",
            ))

        return ExecutionPlan(
            rewritten_query=self.rewritten_query,
            intent_category=self.intent_category,
            required_capabilities=list({
                n.capability_type for n in self.all_nodes
            }),
            subtasks=tasks,
            merge_strategy=self.merge_strategy,
            risk_level=self.risk_level,
            completion_criteria=self.completion_criteria,
            metadata=self.metadata,
        )

    def to_execution_graph(self, ctx: Any | None = None) -> list[Any]:
        """转换为 kernel.runtime.objects.ExecutionNode 列表。"""
        from kernel.runtime.objects import ExecutionBudget, ExecutionEdge, ExecutionNode

        enrichment_base: dict[str, Any] = {}
        if ctx is not None:
            try:
                from kernel.turn_enrichment import runtime_agent_params_from_context

                enrichment_base = runtime_agent_params_from_context(ctx)
            except Exception as exc:
                logger.debug("execution_projection_enrichment_skipped", error=str(exc))

        nodes: list[ExecutionNode] = []
        all_node_ids = {n.node_id for n in self.all_nodes}

        for node in self.all_nodes:
            params = {**enrichment_base, **dict(node.params or {})}
            if node.goal_id:
                params.setdefault("goal_id", node.goal_id)
            nodes.append(ExecutionNode(
                node_id=node.node_id,
                capability_name=node.capability_type,
                executor_type=node.executor_type,
                query=node.query,
                params=params,
                depends_on=[d for d in node.depends_on if d in all_node_ids],
                resource=node.resource,
                priority=node.priority,
                budget=ExecutionBudget(
                    max_tokens=node.max_tokens,
                    max_latency_ms=node.max_latency_ms,
                ),
                expected_evidence_schema={"type": node.expected_evidence_type},
            ))

        return nodes

    def summary(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "group_count": len(self.groups),
            "total_nodes": len(self.all_nodes),
            "merge_strategy": self.merge_strategy,
            "risk_level": self.risk_level,
            "estimated_latency_ms": self.total_estimated_latency_ms,
            "estimated_tokens": self.total_estimated_tokens,
        }


# ── 构建器 ──────────────────────────────────────────────────────────────────

# 能力 → 执行器类型映射
_EXECUTOR_MAP: dict[str, str] = {
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
    "model.answer": "model",
}

_RESOURCE_MAP: dict[str, str] = {
    "web.search": "IO",
    "memory.retrieve": "IO",
    "chart.generate": "GPU",
}


def build_execution_projection(
    strategy: StrategyProjection,
    query: str = "",
    intent_category: str = "general",
    risk_level: str = "low",
    completion_criteria: str = "",
) -> ExecutionProjection:
    """将 StrategyProjection 转换为 ExecutionProjection（可供 ExecutionRuntime 使用）。

    将每个 CapabilityAssignment 映射为具有具体执行器类型、资源和预算的
    ProjectedCapability。按并行潜力分组。
    """
    # ── 步骤 1：将分配映射为投影能力 ──
    assignment_map: dict[str, CapabilityAssignment] = {
        a.assignment_id: a for a in strategy.assignments
    }

    all_nodes: list[ProjectedCapability] = []
    for assign in strategy.assignments:
        cap_type = assign.capability_type
        executor_type = _EXECUTOR_MAP.get(cap_type, _infer_executor(cap_type))
        resource = _RESOURCE_MAP.get(cap_type, _infer_resource(cap_type))

        # 能力智能：从配置文件动态获取预算
        max_tokens = 4096
        max_latency_ms = 30000
        try:
            from kernel.capability_intelligence import _capability_intelligence_enabled

            if _capability_intelligence_enabled():
                from kernel.capability_intelligence import capability_profiler
                from kernel.runtime.capability import capability_registry

                capability_profiler.build_profiles(capability_registry)
                profile = capability_profiler.get_profile(cap_type)
                if profile:
                    max_latency_ms = profile.expected_latency_ms * 2  # 2 倍预算余量
                    if profile.resource_type == "io":
                        max_latency_ms = max(max_latency_ms, 10000)
                    elif profile.resource_type == "gpu":
                        max_latency_ms = max(max_latency_ms, 60000)
        except Exception as exc:
            logger.debug("execution_projection_profiler_skipped", error=str(exc))

        params = dict(assign.params or {})
        if assign.goal_id:
            params.setdefault("goal_id", assign.goal_id)
        all_nodes.append(ProjectedCapability(
            node_id=assign.assignment_id,
            capability_type=cap_type,
            executor_type=executor_type,
            query=assign.query,
            params=params,
            depends_on=list(assign.depends_on),
            priority=assign.priority,
            resource=resource,
            expected_evidence_type=assign.expected_evidence_type,
            goal_id=assign.goal_id or "",
            max_tokens=max_tokens,
            max_latency_ms=max_latency_ms,
        ))

    # ── 步骤 2：从并行组构建分组 ──
    groups: list[ProjectionGroup] = []
    for order, group_ids in enumerate(strategy.parallelism_groups):
        group_caps: list[ProjectedCapability] = []
        for nid in group_ids:
            node = next((n for n in all_nodes if n.node_id == nid), None)
            if node:
                group_caps.append(node)
        if group_caps:
            groups.append(ProjectionGroup(
                capabilities=group_caps,
                group_order=order,
            ))

    # ── 步骤 3：计算估算值 ──
    total_latency = len(groups) * 30000  # 每组最多 30 秒
    total_tokens = len(all_nodes) * 3000

    projection = ExecutionProjection(
        rewritten_query=query,
        intent_category=intent_category,
        risk_level=risk_level,
        completion_criteria=completion_criteria or "所有能力执行完成 + 证据融合完成",
        groups=groups,
        all_nodes=all_nodes,
        merge_strategy=strategy.budget_constraints.get("merge_strategy", strategy.execution_strategy),
        max_parallel=strategy.budget_constraints.get("max_parallel", 5),
        total_estimated_latency_ms=total_latency,
        total_estimated_tokens=total_tokens,
        metadata={
            "plan_id": strategy.plan_id,
            "projection_id": strategy.projection_id,
            "risk_controls": strategy.risk_controls,
        },
    )

    logger.info(
        "ExecutionProjection built",
        groups=len(groups),
        nodes=len(all_nodes),
        latency_ms=total_latency,
    )

    return projection


def _infer_executor(capability_type: str) -> str:
    if capability_type.startswith("tool."):
        return "tool"
    return "agent"


def _infer_resource(capability_type: str) -> str:
    if capability_type in ("web.search", "memory.retrieve"):
        return "IO"
    if capability_type == "chart.generate":
        return "GPU"
    return "CPU"
