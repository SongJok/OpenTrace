"""
认知图 — 系统的"思维图"。

将认知推理（解决什么、为什么、有什么不确定性）
与执行规划（如何执行、使用哪些能力）分离。

CognitiveGraph 是系统思考的内容。
ExecutionGraph 是系统执行的内容。

它们是具有不同语义的不同图。将它们混淆是复杂多跳任务中
规划器脆弱性的根本原因。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ── 目标类型 ───────────────────────────────────────────────────────────────

class GoalType(str, Enum):
    """认知层级中目标节点的性质。"""
    PRIMARY = "primary"        # 用户明确的需求
    IMPLICIT = "implicit"      # 隐含/暗示的需求
    VERIFICATION = "verification"  # 事实核查子目标
    EXPLORATION = "exploration"    # 开放式探索
    COMPARISON = "comparison"      # 多源比较
    DECOMPOSITION = "decomposition"  # 分解后的子目标
    CLARIFICATION = "clarification"  # 消歧


# ── 目标层级 ───────────────────────────────────────────────────────────

@dataclass
class GoalNode:
    """目标层级树中的单个节点。

    每个节点代表一个认知目标 — 不是任务，不是能力调用，
    而是一个真正的"我们需要弄清楚什么"。
    """

    goal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""           # 人类可读的目标描述
    goal_type: GoalType = GoalType.DECOMPOSITION
    parent_id: str | None = None    # 父目标（根节点为 None）
    children: list[str] = field(default_factory=list)  # 子目标 ID
    priority: str = "normal"        # high | normal | low
    completion_criteria: str = ""   # "此目标何时算完成？"
    depends_on: list[str] = field(default_factory=list)  # 依赖的目标 ID
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GoalHierarchy:
    """从用户主要意图分解出的目标树。

    根节点始终是 PRIMARY 目标。子目标是通过认知分解发现的，
    而非通过能力匹配产生的。
    """

    root_goal: GoalNode = field(default_factory=GoalNode)
    all_goals: dict[str, GoalNode] = field(default_factory=dict)
    max_depth: int = 0

    def add_goal(self, goal: GoalNode) -> None:
        self.all_goals[goal.goal_id] = goal

    def get_leaf_goals(self) -> list[GoalNode]:
        """没有子目标的目标 — 即终端认知目标。"""
        return [g for g in self.all_goals.values() if not g.children]

    def get_root_goals(self) -> list[GoalNode]:
        """没有父目标的目标 — 入口点。"""
        return [g for g in self.all_goals.values() if g.parent_id is None]

    def topological_order(self) -> list[GoalNode]:
        """按依赖关系的 BFS 序。"""
        visited: set[str] = set()
        order: list[GoalNode] = []

        def _visit(gid: str) -> None:
            if gid in visited:
                return
            visited.add(gid)
            goal = self.all_goals.get(gid)
            if goal is None:
                return
            for dep_id in goal.depends_on:
                _visit(dep_id)
            order.append(goal)

        for root in self.get_root_goals():
            _visit(root.goal_id)
        return order


# ── 不确定性模型 ───────────────────────────────────────────────────────

@dataclass
class UncertaintyModel:
    """系统不知道且需要解决的内容。

    这对多跳推理至关重要：在执行任何操作之前，
    我们必须显式建模缺失的信息。
    """

    unknown_entities: list[str] = field(default_factory=list)
    unknown_facts: list[str] = field(default_factory=list)
    ambiguous_terms: list[str] = field(default_factory=list)
    conflicting_hypotheses: list[dict[str, str]] = field(default_factory=list)
    confidence_threshold: float = 0.6

    @property
    def has_uncertainty(self) -> bool:
        return bool(
            self.unknown_entities
            or self.unknown_facts
            or self.ambiguous_terms
            or self.conflicting_hypotheses
        )

    @property
    def gap_count(self) -> int:
        return (
            len(self.unknown_entities)
            + len(self.unknown_facts)
            + len(self.ambiguous_terms)
            + len(self.conflicting_hypotheses)
        )


# ── 信息缺口 ──────────────────────────────────────────────────────────

@dataclass
class InformationGap:
    """系统需要获取的特定信息。"""

    gap_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    gap_type: str = "fact"  # fact | entity | relation | constraint | verification
    query_template: str = ""  # 如何请求此信息
    required_confidence: float = 0.6
    suggested_source: str = ""  # "rag" | "web" | "data" | "memory"
    resolved_by: str | None = None  # 解决此缺口的目标 ID
    priority: str = "normal"


# ── 推理链 ─────────────────────────────────────────────────────────────

@dataclass
class ReasoningStep:
    """推理链中的单个逻辑步骤。"""

    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""           # "筛选到 2025 年 Q4"、"与用户表关联" 等
    step_type: str = "inference"    # inference | lookup | compute | compare | verify
    inputs: list[str] = field(default_factory=list)   # 步骤 ID 或缺口 ID
    outputs: str = ""               # 此步骤产出什么
    confidence: float = 0.8
    depends_on: list[str] = field(default_factory=list)
    fallback_step_id: str | None = None  # 此步骤失败时的替代步骤


@dataclass
class ReasoningChain:
    """从问题到答案的完整推理链。

    可以并行存在多条链（用于比较或独立子目标）。
    每条链由一系列 ReasoningStep 组成。
    """

    chain_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    goal_id: str = ""               # 此链服务的目标
    steps: list[ReasoningStep] = field(default_factory=list)
    chain_type: str = "linear"      # linear | branching | comparative | iterative
    expected_output_type: str = "text"
    confidence: float = 0.8

    def topological_steps(self) -> list[ReasoningStep]:
        """按依赖顺序返回步骤。"""
        visited: set[str] = set()
        order: list[ReasoningStep] = []
        step_map = {s.step_id: s for s in self.steps}

        def _visit(sid: str) -> None:
            if sid in visited:
                return
            visited.add(sid)
            step = step_map.get(sid)
            if step is None:
                return
            for dep_id in step.depends_on:
                _visit(dep_id)
            order.append(step)

        for s in self.steps:
            _visit(s.step_id)
        return order


# ── 认知约束 ────────────────────────────────────────────────────────────

@dataclass
class CognitiveConstraint:
    """认知分析过程中发现的约束。

    这些不是系统/策略约束（那些在 PolicyEngine 中）。
    这些是任务级约束：领域规则、用户需求、
    推理必须遵守的逻辑不变量。
    """

    constraint_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    description: str = ""
    constraint_type: str = "domain"  # domain | user | temporal | logical | output
    severity: str = "hard"           # hard（必须遵守）| soft（尽量遵守）
    applies_to: list[str] = field(default_factory=list)  # 目标 ID 或 "all"


# ── 风险分析 ────────────────────────────────────────────────────────────

@dataclass
class RiskAnalysis:
    """认知规划过程中识别的风险。"""

    risk_level: str = "low"  # low | medium | high | critical
    risks: list[dict[str, str]] = field(default_factory=list)
    mitigation_strategies: list[str] = field(default_factory=list)
    fallback_plan: str = ""
    requires_human_approval: bool = False


# ── 认知图（顶层容器） ───────────────────────────────────────────────────

@dataclass
class CognitiveGraph:
    """用户请求的完整认知模型。

    这是 CognitivePlannerV2 的产出 — 系统需要思考什么的结构化表示，
    而非如何执行。

    CognitiveGraph → StrategyBuilder → StrategyProjection → ExecutionPlan
    """

    graph_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    original_query: str = ""
    rewritten_query: str = ""

    # 核心认知结构
    goal_hierarchy: GoalHierarchy = field(default_factory=GoalHierarchy)
    uncertainty_model: UncertaintyModel = field(default_factory=UncertaintyModel)
    information_gaps: list[InformationGap] = field(default_factory=list)
    reasoning_chains: list[ReasoningChain] = field(default_factory=list)
    constraints: list[CognitiveConstraint] = field(default_factory=list)
    risk_analysis: RiskAnalysis = field(default_factory=RiskAnalysis)

    # 元信息
    domain: str = ""
    complexity_score: float = 0.0
    expected_turn_count: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def total_gaps(self) -> int:
        return len(self.information_gaps)

    @property
    def total_steps(self) -> int:
        return sum(len(rc.steps) for rc in self.reasoning_chains)

    @property
    def has_uncertainty(self) -> bool:
        return self.uncertainty_model.has_uncertainty

    def summary(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "domain": self.domain,
            "goal_count": len(self.goal_hierarchy.all_goals),
            "leaf_goal_count": len(self.goal_hierarchy.get_leaf_goals()),
            "gap_count": self.total_gaps,
            "reasoning_chain_count": len(self.reasoning_chains),
            "total_reasoning_steps": self.total_steps,
            "constraint_count": len(self.constraints),
            "risk_level": self.risk_analysis.risk_level,
            "has_uncertainty": self.has_uncertainty,
            "complexity_score": self.complexity_score,
        }


# ── 认知计划（CognitivePlannerV2 的顶层输出） ──────────────────────────────

@dataclass
class CognitivePlan:
    """认知规划层的完整输出。

    包含认知图、记忆依赖、证据需求和预期产出物。
    StrategyBuilder 消费此计划以生成 StrategyProjection，
    然后 ExecutionProjection 将其映射为 ExecutionPlan。
    """

    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    cognitive_graph: CognitiveGraph = field(default_factory=CognitiveGraph)

    # 记忆依赖 — 此计划依赖的先验知识
    memory_dependencies: list[str] = field(default_factory=list)

    # 证据需求 — 必须获取的新证据
    evidence_requirements: list[dict[str, Any]] = field(default_factory=list)

    # 预期产出物 — 此计划应产生的结果
    expected_artifacts: list[dict[str, Any]] = field(default_factory=list)

    # 执行提示（不是计划本身 — StrategyBuilder 使用这些）
    execution_hints: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            **self.cognitive_graph.summary(),
            "memory_dependency_count": len(self.memory_dependencies),
            "evidence_requirement_count": len(self.evidence_requirements),
            "expected_artifact_count": len(self.expected_artifacts),
        }
