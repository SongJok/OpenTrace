"""
DataAgent V2 — 多 Agent 认知流水线共享类型与协议。

各子 Agent 经 TaskMessage.params / AgentResult.metadata 传递 CognitiveContext，
DAG 调度器可串联执行而无需改动 BaseAgent 接口。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any

from kernel.data_cognition.types import (
    EntityMapping,
    MetricMapping,
    SemanticContext,
    LogicalPlan,
)
from kernel.data_cognition.table_graph import JoinStep
from kernel.data_cognition.sql_dialect import SQLDialectSpec


# ── Cognitive Context ──────────────────────────────────────────────────────


@dataclass
class CognitiveContext:
    """在子 Agent 间传递累积的认知状态。

    序列化为 JSON 写入 TaskMessage.params / AgentResult.metadata 的 cognitive_context，
    供 DAG 调度器串联依赖而无需了解内部结构。
    """

    # ── 输入（Supervisor 在 DAG 执行前设置）──────────────────
    query: str = ""
    data_source_id: str = ""
    dialect: str = "postgresql"  # SQLDialectSpec.value
    schema_hint: str = ""  # human-readable schema summary
    table_names: list[str] = field(default_factory=list)
    table_columns: dict[str, list[str]] = field(default_factory=dict)
    semantic_config: dict[str, Any] = field(default_factory=dict)

    # ── 由上游子 Agent 填充 ───────────────────────────────
    intent: dict[str, Any] | None = None  # IntentAgent
    entities: list[dict[str, Any]] | None = None  # EntityAgent
    metrics: list[dict[str, Any]] | None = None  # MetricAgent
    time_window: dict[str, Any] | None = None  # TimeReasoningAgent
    join_paths: list[dict[str, Any]] | None = None  # JoinAgent
    semantic_context: dict[str, Any] | None = None  # SemanticAgent
    business_semantic: dict[str, Any] | None = None  # BusinessSemanticAgent
    logical_plan: dict[str, Any] | None = None  # PlannerAgent
    compiled_sql: str | None = None  # SQLCompilerAgent
    verification_report: dict[str, Any] | None = None  # VerificationAgent

    # ── 知识层（KnowledgeRetrieverAgent 注入）───────────
    matched_metrics: list[dict[str, Any]] | None = None  # from metric_definitions
    matched_skills: list[dict[str, Any]] | None = None  # from analytical_skills
    matched_relationships: list[dict[str, Any]] | None = None  # from table_relationships
    column_semantics: list[dict[str, Any]] | None = None  # from schema_metadata
    pattern_hit: dict[str, Any] | None = None  # from query_patterns (fast path)

    # ── 执行结果（执行后写入）────────────────────────────
    execution_rows: list[dict[str, Any]] | None = None
    execution_row_count: int = 0
    execution_error: str | None = None
    reflection_rounds: int = 0

    # ── 学习层（FeedbackCollector、KnowledgeUpdater 填充）─
    learning_signals: dict[str, Any] | None = None  # classified feedback + actions
    refined_metrics: list[dict[str, Any]] | None = None  # from MetricRefinerAgent

    # ── 多轮澄清 ─────────────────────────────────────
    needs_clarification: bool = False
    clarification: dict[str, Any] | None = None  # ClarificationQuestion as dict
    clarify_context: str = ""  # user's response to a previous clarification

    # ── 高级分析（Phase 4）──────────────────────────────────
    statistical_report: dict[str, Any] | None = None  # from StatisticalAgent
    insights: dict[str, Any] | None = None  # from InsightAgent
    visualization_config: dict[str, Any] | None = None  # from VisualizationAgent

    # ── Turn outcome extensions (supervisor / error classifier) ──
    metadata_extra: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CognitiveContext:
        # 过滤非 dataclass 字段以保持前向兼容
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in valid_keys})

    @classmethod
    def from_json(cls, s: str) -> CognitiveContext:
        return cls.from_dict(json.loads(s) if s else {})


# ── Sub-Agent Result Helpers ───────────────────────────────────────────────


def pack_cognitive_result(
    task_id: str,
    agent_type: str,
    status: str,
    content: str,
    confidence: float,
    ctx: CognitiveContext,
    evidence: list[dict[str, Any]] | None = None,
    agent_trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构建含 cognitive_context 元数据的 AgentResult 字典。

    子 Agent 调用此方法供 DAG 调度器串联。
    """
    return {
        "task_id": task_id,
        "agent_type": agent_type,
        "status": status,
        "content": content,
        "confidence": confidence,
        "metadata": {
            "cognitive_context": ctx.to_dict(),
        },
        "evidence": evidence or [],
        "agent_trace": agent_trace or {},
    }


def unpack_cognitive_context(params: dict[str, Any]) -> CognitiveContext:
    """从 TaskMessage.params 中提取 CognitiveContext。"""
    raw = params.get("cognitive_context", {})
    if isinstance(raw, CognitiveContext):
        return raw
    if isinstance(raw, str):
        return CognitiveContext.from_json(raw)
    return CognitiveContext.from_dict(raw)


# ── Intent Types ───────────────────────────────────────────────────────────

INTENT_TYPES = frozenset({
    "aggregation",       # "每个地区的销售额"
    "filtering",         # "销售额大于1000的订单"
    "ranking",           # "销售额最高的10个产品"
    "trend",             # "过去6个月的趋势"
    "comparison",        # "今年 vs 去年的对比"
    "distribution",      # "用户等级的分布"
    "raw_lookup",        # "查询用户123的订单"
    "metadata",          # "这个数据库有哪些表"
    "anomaly_detection", # "哪些指标有异常"
    "funnel",            # "从注册到付费的转化"
    "cohort",            # "每月新增用户的留存"
    "composition",       # "各部分占比"
})

INTENT_TO_SKILL_TYPE: dict[str, str] = {
    "comparison": "comparison",
    "trend": "trend",
    "funnel": "funnel",
    "cohort": "cohort",
    "anomaly_detection": "anomaly",
    "ranking": "ranking",
    "composition": "composition",
}


# ── Knowledge Retrieval Specs ──────────────────────────────────────────────

class LowConfidenceError(Exception):
    """当 V2 流水线置信度低于配置阈值时抛出。

    由 DataAgent 包装器捕获以触发 V1 回退，
    同时保留 V2 尝试的诊断上下文。
    """
    def __init__(self, confidence: float, threshold: float, detail: str = ""):
        self.confidence = confidence
        self.threshold = threshold
        self.detail = detail
        super().__init__(f"Confidence {confidence:.2f} below threshold {threshold:.2f}" + (f": {detail}" if detail else ""))


@dataclass
class KnowledgeRetrievalSpec:
    """描述知识层应检索的内容。"""
    query: str
    intent_type: str | None = None
    entity_names: list[str] = field(default_factory=list)
    metric_names: list[str] = field(default_factory=list)
    data_source_id: str = ""
    table_names: list[str] = field(default_factory=list)
    enable_skills: bool = True
    enable_patterns: bool = True
    enable_relationships: bool = True
    enable_column_semantics: bool = True
