"""
分解策略 — 决定 CognitiveGraph 应如何分解以供执行。

并非所有计划都应以相同方式执行。此模块根据认知图的结构
计算最优分解策略：目标数量、依赖深度、不确定性、风险级别和领域约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .cognitive_graph import CognitiveGraph


class DecompositionStrategy(str, Enum):
    """认知图的执行分解方式。"""
    DIRECT = "direct"       # 单能力，单次调用
    PARALLEL = "parallel"   # 多能力，无依赖 → 并行执行
    SEQUENTIAL = "sequential"  # 多能力有依赖 → 顺序执行
    COMPARE = "compare"     # 多个独立来源 → 比较结果
    EXPLORE = "explore"     # 开放式 → 迭代
    VERIFY = "verify"       # 主结果 + 验证


@dataclass
class DecompositionPolicy:
    """认知图的最优执行分解策略。"""

    strategy: DecompositionStrategy = DecompositionStrategy.DIRECT
    max_parallel: int = 3
    max_retries: int = 2
    timeout_ms: int = 30000
    merge_strategy: str = "union"  # union | prioritized | compare
    reason: str = ""


def build_decomposition_policy(graph: CognitiveGraph) -> DecompositionPolicy:
    """确定认知图的最优分解策略。

    规则（按优先级排序）：
    1. 单目标 + 无缺口 → DIRECT
    2. 单目标 + 有缺口 → SEQUENTIAL（先填补缺口，再回答）
    3. 多个独立叶目标 → PARALLEL
    4. 目标间有交叉依赖 → SEQUENTIAL
    5. 比较类型目标 → COMPARE
    6. 高复杂度 → SEQUENTIAL 并加重试
    """
    leaf_goals = graph.goal_hierarchy.get_leaf_goals()
    gap_count = len(graph.information_gaps)
    constraint_count = len(graph.constraints)
    risk_level = graph.risk_analysis.risk_level

    # 规则 5（优先检查）：比较类型目标 → COMPARE
    has_comparison = any(
        g.goal_type.value == "comparison"
        for g in graph.goal_hierarchy.all_goals.values()
    )
    if has_comparison:
        return DecompositionPolicy(
            strategy=DecompositionStrategy.COMPARE,
            max_parallel=min(len(leaf_goals), 4),
            max_retries=1,
            merge_strategy="compare",
            reason="comparison-type goals require compare strategy",
        )

    # 规则 6（其次检查）：高复杂度或高风险 → SEQUENTIAL
    if graph.complexity_score > 0.7 or risk_level in ("high", "critical"):
        return DecompositionPolicy(
            strategy=DecompositionStrategy.SEQUENTIAL,
            max_parallel=1,
            max_retries=3,
            merge_strategy="prioritized",
            reason=f"high complexity ({graph.complexity_score:.1f}) or risk ({risk_level})",
        )

    # 规则 1：单目标 + 无缺口 → DIRECT
    if len(leaf_goals) <= 1 and gap_count == 0:
        return DecompositionPolicy(
            strategy=DecompositionStrategy.DIRECT,
            max_parallel=1,
            max_retries=1,
            merge_strategy="direct",
            reason="single goal, no information gaps",
        )

    # 规则 2：单目标 + 有缺口 → SEQUENTIAL
    if len(leaf_goals) <= 1 and gap_count > 0:
        return DecompositionPolicy(
            strategy=DecompositionStrategy.SEQUENTIAL,
            max_parallel=1,
            max_retries=2,
            merge_strategy="union",
            reason=f"single goal with {gap_count} information gaps",
        )

    # 规则 4：目标间有交叉依赖 → SEQUENTIAL
    has_dependencies = any(
        bool(g.depends_on) for g in graph.goal_hierarchy.all_goals.values()
    )
    if has_dependencies:
        return DecompositionPolicy(
            strategy=DecompositionStrategy.SEQUENTIAL,
            max_parallel=2,
            max_retries=2,
            merge_strategy="union",
            reason="goals have cross-dependencies",
        )

    # 规则 3：多个独立叶目标 → PARALLEL
    return DecompositionPolicy(
        strategy=DecompositionStrategy.PARALLEL,
        max_parallel=min(len(leaf_goals), 5),
        max_retries=1,
        merge_strategy="union",
        reason=f"{len(leaf_goals)} independent leaf goals, parallelizable",
    )
