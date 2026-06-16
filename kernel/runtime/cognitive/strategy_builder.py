"""
策略构建器 — 将 CognitivePlan 转换为 StrategyProjection。

这是"思考什么"（CognitiveGraph）与"如何执行"（ExecutionPlan）之间的桥梁。
StrategyProjection 还不是执行计划 — 它是一种策略：需要哪些能力、
以什么顺序、具有什么依赖关系和并行度。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

from .cognitive_graph import CognitiveGraph, CognitivePlan, InformationGap
from .decomposition_policy import (
    DecompositionPolicy,
    DecompositionStrategy,
    build_decomposition_policy,
)

logger = get_logger(__name__)


# ── 策略投影 ─────────────────────────────────────────────────────────────

@dataclass
class CapabilityAssignment:
    """解决信息缺口或服务目标所需的能力。"""

    assignment_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    capability_type: str = ""     # "rag.retrieve"、"data.query"、"web.search" 等
    goal_id: str = ""             # 此能力服务的认知目标
    gap_id: str = ""              # 此能力解决的信息缺口
    query: str = ""               # 能力的具体查询
    priority: str = "normal"
    depends_on: list[str] = field(default_factory=list)  # 分配 ID
    expected_evidence_type: str = "text"
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class StrategyProjection:
    """CognitivePlan 与 ExecutionPlan 之间的桥梁。

    包含按并行潜力分组的能力分配，以及执行顺序、
    证据依赖和预算约束。
    """

    projection_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    plan_id: str = ""

    # 能力分配 — 需要做什么
    assignments: list[CapabilityAssignment] = field(default_factory=list)

    # 执行顺序
    execution_strategy: str = "direct"  # direct | parallel | sequential | compare
    parallelism_groups: list[list[str]] = field(default_factory=list)  # 分配 ID 分组

    # 预算
    budget_constraints: dict[str, Any] = field(default_factory=dict)

    # 风险控制
    risk_controls: dict[str, Any] = field(default_factory=dict)
    fallback_strategy: str = ""

    # 元信息
    estimated_latency_ms: int = 0
    estimated_tokens: int = 0

    def summary(self) -> dict[str, Any]:
        return {
            "projection_id": self.projection_id,
            "assignment_count": len(self.assignments),
            "execution_strategy": self.execution_strategy,
            "parallelism_group_count": len(self.parallelism_groups),
            "estimated_latency_ms": self.estimated_latency_ms,
        }


# ── 策略构建器 ────────────────────────────────────────────────────────────

class StrategyBuilder:
    """将 CognitivePlan 转换为 StrategyProjection。

    使用分解策略将认知目标 + 信息缺口映射为能力分配，
    然后按并行潜力分组。
    """

    def __init__(self, capability_registry: Any = None) -> None:
        self._capability_registry = capability_registry

    def build(self, plan: CognitivePlan) -> StrategyProjection:
        """从认知计划构建策略投影。

        算法：
        1. 将信息缺口映射为能力分配
        2. 将无缺口的叶目标映射为能力分配
        3. 应用分解策略确定顺序
        4. 将分配分组为并行组
        5. 估算预算和风险控制
        """
        graph = plan.cognitive_graph
        policy = build_decomposition_policy(graph)
        projection = StrategyProjection(plan_id=plan.plan_id)

        # ── 步骤 1：将信息缺口映射为能力分配 ──
        assignments: list[CapabilityAssignment] = []
        gap_assignments: dict[str, str] = {}  # gap_id → assignment_id

        for gap in graph.information_gaps:
            cap_type = self._gap_to_capability(gap)
            query = gap.query_template or gap.description
            assign = CapabilityAssignment(
                capability_type=cap_type,
                gap_id=gap.gap_id,
                query=query,
                priority=gap.priority,
                expected_evidence_type=self._gap_to_evidence_type(gap),
            )
            assignments.append(assign)
            gap_assignments[gap.gap_id] = assign.assignment_id

        # ── 步骤 2：将无缺口的叶目标映射为能力分配 ──
        leaf_goals = graph.goal_hierarchy.get_leaf_goals()
        for goal in leaf_goals:
            existing_assignments = [
                a for a in assignments
                if a.goal_id == goal.goal_id
            ]
            if existing_assignments:
                continue  # 已有基于缺口的能力分配

            cap_type = self._goal_to_capability(goal.description, goal.goal_type.value)
            assign = CapabilityAssignment(
                capability_type=cap_type,
                goal_id=goal.goal_id,
                query=goal.description,
                priority=goal.priority,
                expected_evidence_type="text",
            )
            assignments.append(assign)

        projection.assignments = assignments

        # ── 步骤 3：应用分解策略确定顺序和依赖 ──
        self._apply_policy(projection, graph, policy)

        # ── 步骤 4：分组为并行组 ──
        projection.parallelism_groups = self._build_parallelism_groups(assignments)

        # ── 步骤 5：执行策略 ──
        projection.execution_strategy = self._determine_execution_strategy(graph, policy, assignments)

        # ── 步骤 6：预算 ──
        projection.budget_constraints = {
            "max_total_tokens": len(assignments) * 4096,
            "max_latency_ms": len(assignments) * 30000,
            "max_parallel": policy.max_parallel,
        }

        # ── 步骤 7：风险控制 ──
        projection.risk_controls = self._build_risk_controls(graph, policy)
        projection.fallback_strategy = graph.risk_analysis.fallback_plan or "degrade_gracefully"

        projection.estimated_latency_ms = len(assignments) * 5000
        projection.estimated_tokens = len(assignments) * 3000

        logger.info(
            "StrategyBuilder built projection",
            assignments=len(assignments),
            strategy=projection.execution_strategy,
            groups=len(projection.parallelism_groups),
        )

        return projection

    # ── 辅助方法 ─────────────────────────────────────────────────────────────

    def _source_to_capability_candidates(self, source: str) -> list[str]:
        mapping: dict[str, list[str]] = {
            "rag": ["rag.retrieve", "document_retrieval"],
            "web": ["web.search", "web_search"],
            "data": ["data.query", "data_query"],
            "memory": ["memory.retrieve", "document_retrieval"],
        }
        return mapping.get(source.lower(), ["rag.retrieve", "web.search", "data.query"])

    def _gap_to_capability(self, gap: InformationGap) -> str:
        source = gap.suggested_source.lower()
        intent = str((getattr(gap, "metadata", None) or {}).get("intent_category", "general"))

        try:
            from kernel.capability_runtime.selector import rank_capabilities_for_intent

            candidates = self._source_to_capability_candidates(source)
            ranked = rank_capabilities_for_intent(candidates, intent_category=intent)
            if ranked:
                return ranked[0]["capability_type"]
        except Exception as exc:
            logger.debug("strategy_builder_selector_skipped", error=str(exc))

        # 能力智能：查询配置器获取最佳匹配
        try:
            from kernel.capability_intelligence import (
                _capability_intelligence_enabled,
                _capability_intelligence_phase2_enabled,
                capability_profiler,
            )

            if _capability_intelligence_enabled() and self._capability_registry is not None:
                capability_profiler.build_profiles(self._capability_registry)

                # 阶段 2：使用推理器进行知识图谱 + 历史加权匹配
                if _capability_intelligence_phase2_enabled():
                    reasoner = capability_profiler.get_reasoner()
                    if reasoner is not None:
                        results = reasoner.recommend_capability(
                            gap_description=gap.description or "",
                            suggested_source=source,
                            top_k=1,
                        )
                        if results:
                            return results[0][0].capability_type

                # 阶段 1：多目标评分（语义 + 历史 + 上下文 + 预算 + 风险）
                profiles = capability_profiler.list_profiles()
                if profiles:
                    results = capability_profiler.match_multi_objective(
                        query=gap.description or gap.query_template or source,
                        top_k=1,
                        context={"domain": "general", "required_inputs": []},
                    )
                    if results:
                        return results[0][1].capability_type
        except Exception as exc:
            logger.debug("strategy_builder_capability_intelligence_skipped", error=str(exc))

        # 回退：registry + topology 选型
        try:
            from kernel.capability_runtime.selector import rank_capabilities_for_intent

            intent = (getattr(gap, "metadata", None) or {}).get("intent", "general")
            candidates = ["rag.retrieve", "web.search", "data.query", "memory.retrieve"]
            ranked = rank_capabilities_for_intent(candidates, intent_category=str(intent))
            if ranked:
                return ranked[0]["capability_type"]
        except Exception as exc:
            logger.debug("strategy_builder_topology_fallback_skipped", error=str(exc))

        mapping: dict[str, str] = {
            "rag": "rag.retrieve",
            "web": "web.search",
            "data": "data.query",
            "memory": "memory.retrieve",
            "python": "python.execute",
            "model": "model.answer",
            "model.answer": "model.answer",
            "llm": "model.answer",
        }
        if source in ("", "none", "general"):
            return "model.answer"
        return mapping.get(source, "rag.retrieve")

    def _gap_to_evidence_type(self, gap: InformationGap) -> str:
        type_map: dict[str, str] = {
            "fact": "text",
            "entity": "text",
            "relation": "table",
            "constraint": "text",
            "verification": "text",
        }
        return type_map.get(gap.gap_type, "text")

    def _goal_to_capability(self, description: str, goal_type: str) -> str:
        desc_lower = description.lower()
        if any(kw in desc_lower for kw in ["查询", "数据", "统计", "分析", "sql", "报表"]):
            return "data.query"
        if any(kw in desc_lower for kw in ["搜索", "最新", "实时", "新闻", "天气"]):
            return "web.search"
        if any(kw in desc_lower for kw in ["计算", "运行", "代码", "执行"]):
            return "python.execute"
        return "rag.retrieve"

    def _apply_policy(
        self,
        projection: StrategyProjection,
        graph: CognitiveGraph,
        policy: DecompositionPolicy,
    ) -> None:
        """应用分解策略设置分配依赖。"""
        if policy.strategy == DecompositionStrategy.SEQUENTIAL:
            for i in range(1, len(projection.assignments)):
                prev_id = projection.assignments[i - 1].assignment_id
                projection.assignments[i].depends_on.append(prev_id)

        elif policy.strategy == DecompositionStrategy.COMPARE:
            # 比较：所有分配独立，之后合并
            pass  # 不需要依赖

        # 从认知图应用目标依赖
        goal_map: dict[str, list[str]] = {}
        for a in projection.assignments:
            if a.goal_id:
                goal_map.setdefault(a.goal_id, []).append(a.assignment_id)

        for goal in graph.goal_hierarchy.all_goals.values():
            if goal.depends_on and goal.goal_id in goal_map:
                for dep_goal_id in goal.depends_on:
                    if dep_goal_id in goal_map:
                        for aid in goal_map[goal.goal_id]:
                            for dep_aid in goal_map[dep_goal_id]:
                                if dep_aid not in projection.assignments:
                                    continue
                                assign = next(
                                    (a for a in projection.assignments if a.assignment_id == aid), None
                                )
                                if assign and dep_aid not in assign.depends_on:
                                    assign.depends_on.append(dep_aid)

    def _build_parallelism_groups(
        self, assignments: list[CapabilityAssignment]
    ) -> list[list[str]]:
        """将可并行执行的分配分组。

        两个分配如果没有相互依赖关系，则可以并行。

        阶段 2：额外参考知识图谱拓扑顺序
        以获取能力级别的依赖约束。
        """
        dep_graph: dict[str, set[str]] = {}
        for a in assignments:
            dep_graph[a.assignment_id] = set(a.depends_on)

        # 阶段 2：添加知识图谱级别的依赖
        try:
            from kernel.capability_intelligence import (
                _capability_intelligence_enabled,
                _capability_intelligence_phase2_enabled,
                capability_profiler,
            )

            if (
                _capability_intelligence_enabled()
                and _capability_intelligence_phase2_enabled()
            ):
                kg = capability_profiler.get_knowledge_graph()
                if kg is not None and kg.is_built:
                    # 映射 capability_type -> assignment_ids
                    cap_to_ids: dict[str, list[str]] = {}
                    for a in assignments:
                        cap_to_ids.setdefault(a.capability_type, []).append(a.assignment_id)

                    # 如果 cap_a 依赖 cap_b，确保所有 cap_a 的分配
                    # 依赖于所有 cap_b 的分配
                    for cap_a, ids_a in cap_to_ids.items():
                        deps = kg.depends_on(cap_a)
                        for cap_b in deps:
                            if cap_b in cap_to_ids:
                                for aid in ids_a:
                                    for dep_id in cap_to_ids[cap_b]:
                                        if aid != dep_id:
                                            dep_graph.setdefault(aid, set()).add(dep_id)
        except Exception as exc:
            logger.debug("strategy_builder_kg_deps_skipped", error=str(exc))

        groups: list[list[str]] = []
        remaining = set(a.assignment_id for a in assignments)

        while remaining:
            group: list[str] = []
            for aid in list(remaining):
                deps = dep_graph.get(aid, set())
                if deps & remaining:
                    continue  # 有仍在剩余集中的依赖 — 必须等待
                group.append(aid)
            if not group:
                # 循环或死锁 — 将剩余项拆分为单独组
                for aid in remaining:
                    groups.append([aid])
                break
            groups.append(group)
            remaining -= set(group)

        return groups

    def _determine_execution_strategy(
        self,
        graph: CognitiveGraph,
        policy: DecompositionPolicy,
        assignments: list[CapabilityAssignment],
    ) -> str:
        # 阶段 2：参考策略记忆获取自适应推荐
        try:
            from kernel.capability_intelligence import (
                _capability_intelligence_enabled,
                _capability_intelligence_phase2_enabled,
            )

            if _capability_intelligence_enabled() and _capability_intelligence_phase2_enabled():
                from kernel.capability_intelligence.strategy_memory import strategy_memory

                cap_types = sorted(list({a.capability_type for a in assignments}))
                domain = getattr(graph, "domain", "general")
                rec = strategy_memory.recommend(cap_types, domain)
                if rec.confidence > 0.3:
                    return rec.strategy_type
        except Exception as exc:
            logger.debug("strategy_builder_strategy_memory_skipped", error=str(exc))

        # 原始启发式（阶段 1 / 回退）
        if policy.strategy == DecompositionStrategy.PARALLEL:
            return "parallel"
        if policy.strategy == DecompositionStrategy.COMPARE:
            return "compare"
        if len(assignments) <= 1:
            return "direct"
        if len(graph.goal_hierarchy.get_leaf_goals()) > 2:
            return "parallel"
        return "sequential"

    def _build_risk_controls(
        self, graph: CognitiveGraph, policy: DecompositionPolicy
    ) -> dict[str, Any]:
        return {
            "risk_level": graph.risk_analysis.risk_level,
            "requires_human_approval": graph.risk_analysis.requires_human_approval,
            "max_retries": policy.max_retries,
            "confidence_threshold": graph.uncertainty_model.confidence_threshold,
            "mitigations": graph.risk_analysis.mitigation_strategies,
        }


# ── 便捷函数 ────────────────────────────────────────────────────────────


def build_strategy_projection(
    plan: CognitivePlan,
    capability_registry: Any = None,
) -> StrategyProjection:
    builder = StrategyBuilder(capability_registry=capability_registry)
    return builder.build(plan)
