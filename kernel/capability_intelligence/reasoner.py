"""CapabilityReasoner — 基于知识图与执行历史的推理引擎。

回答：信息缺口应选何能力、多能力最优执行顺序、历史数据是否应调整推荐等。
将 profiler.match() 与知识图上下文及执行历史加权结合。
"""

from __future__ import annotations

from kernel.capability_intelligence.profile import CapabilityProfile
from kernel.capability_intelligence.knowledge_graph import (
    CapabilityKnowledgeGraph,
    TopologicalOrder,
)
from kernel.capability_intelligence.profiler import CapabilityProfiler
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class CapabilityReasoner:
    """结合知识图谱拓扑 + 画像匹配 + 执行历史的推理引擎。

    由 CapabilityProfiler 按需创建，非模块级单例。
    """

    def __init__(
        self,
        kg: CapabilityKnowledgeGraph,
        profiler: CapabilityProfiler,
        execution_memory=None,
        strategy_memory=None,
    ) -> None:
        self._kg = kg
        self._profiler = profiler
        self._exec_memory = execution_memory
        self._strategy_memory = strategy_memory
        # 来自演化引擎的逐能力权重调整
        self._weight_adjustments: dict[str, float] = {}

    def recommend_capability(
        self,
        gap_description: str,
        suggested_source: str = "",
        top_k: int = 5,
    ) -> list[tuple[CapabilityProfile, float]]:
        """为信息缺口推荐能力。

        算法：
        1. 从 profiler.match_scored() 获取 top_k*2 个带分匹配结果
        2. 将匹配分数作为基础（归一化），然后应用：
           - 权重调整（退化 → 降低，改进 → 提升）
           - 知识图谱惩罚：若候选依赖低可靠性的能力，降级
           - 执行记忆惩罚：若候选近期出现退化，降级
        3. 按调整后分数排序，返回 top_k
        """
        # 1. 原始带分匹配
        raw = self._profiler.match_scored(gap_description, top_k=max(top_k * 2, 10))
        if not raw:
            return []

        # 将匹配分数归一化至 [0.3, 1.0] 范围作为基础分
        max_raw = max(s for s, _ in raw) if raw else 1.0

        # 2. 计算调整后分数
        scored: list[tuple[CapabilityProfile, float]] = []
        for raw_score, profile in raw:
            # 归一化匹配分数，下限 0.3
            base_score = max(0.3, raw_score / max_raw) if max_raw > 0 else 0.3

            # 应用来自演化引擎的权重调整
            adj = self._weight_adjustments.get(profile.capability_type, 0.0)
            base_score += adj

            # 若能力依赖低可靠性的前置能力则惩罚
            deps = self._kg.depends_on(profile.capability_type)
            for dep in deps:
                dep_profile = self._profiler.get_profile(dep)
                if dep_profile and dep_profile.reliability < 0.70:
                    base_score -= 0.15

            # 若执行记忆中检测到近期退化则惩罚
            if self._exec_memory is not None:
                deg = self._exec_memory.degradation_check(profile.capability_type, 0.15)
                if deg is not None:
                    base_score -= 0.20

            # 钳制到正值范围
            base_score = max(0.05, base_score)
            scored.append((profile, round(base_score, 4)))

        # 3. 按调整后分数降序排列
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def determine_execution_order(self, capabilities: list[str]) -> TopologicalOrder:
        """利用知识图谱拓扑确定最优执行顺序。

        利用 knowledge_graph.topological_order()，该方法尊重
        depends_on 边以生成可并行化的执行层。
        """
        return self._kg.topological_order(capabilities)

    def adjust_recommendations(
        self, capability_type: str, adjustment: float, reason: str = ""
    ) -> None:
        """调整能力的推荐权重。

        由 EvolutionEngine 在检测到退化或改进时调用。
        正向调整 = 提升，负向调整 = 惩罚。
        """
        old = self._weight_adjustments.get(capability_type, 0.0)
        self._weight_adjustments[capability_type] = old + adjustment
        logger.debug(
            "Reasoner weight adjusted",
            capability=capability_type,
            old=old,
            new=self._weight_adjustments[capability_type],
            reason=reason,
        )

    def find_alternative(
        self, target: str, unavailable_reasons: dict[str, str] | None = None
    ) -> tuple[str | None, str]:
        """在能力不可用时找到最佳替代。

        使用 knowledge_graph.find_substitute_path() 查找已知替代。
        返回 (替代能力类型, 推理说明字符串)。
        """
        unavailable = set(unavailable_reasons.keys()) if unavailable_reasons else set()
        result = self._kg.find_substitute_path(target, unavailable)
        if result is not None:
            alt, chain = result
            path_desc = " → ".join(chain)
            return alt, f"通过知识图谱替代路径找到: {path_desc}"

        # 回退：用通用的"替代 target"查询尝试 profiler.match()
        matches = self._profiler.match(f"替代 {target}", top_k=3)
        for m in matches:
            if m.capability_type != target and m.capability_type not in unavailable:
                return m.capability_type, f"通过语义匹配找到替代: {m.description}"

        return None, "未找到可用的替代能力"

    def get_execution_strategy_hint(
        self, capabilities: list[str], query_domain: str = "general"
    ) -> str:
        """利用策略记忆历史推荐执行策略。

        返回以下之一："direct"、"parallel"、"sequential"、"compare"。
        无数据时回退到 "sequential"。
        """
        if self._strategy_memory is not None:
            rec = self._strategy_memory.recommend(capabilities, query_domain)
            if rec.confidence > 0.3:
                return rec.strategy_type

        # 基于能力数量与知识图谱拓扑的启发式回退
        if len(capabilities) <= 1:
            return "direct"

        order = self._kg.topological_order(capabilities)
        if len(order.layers) == 1 and len(order.layers[0]) > 1:
            return "parallel"

        return "sequential"
