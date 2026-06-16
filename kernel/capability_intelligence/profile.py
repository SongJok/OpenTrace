"""能力智能 — 运行时自我认知数据结构。

从「工具调用」升级为「能力认知」；CapabilityProfile 携带丰富语义元数据，
使 LLM 规划器了解能力擅长领域，而非仅见名称。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CapabilityProfile:
    """能力的丰富语义画像 — LLM 了解系统能力的窗口。"""

    capability_type: str  # "data.query"、"web.search"、"rag.retrieve" 等
    description: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    ideal_queries: list[str] = field(default_factory=list)
    anti_patterns: list[str] = field(default_factory=list)
    expected_latency_ms: int = 100
    reliability: float = 0.9
    required_inputs: list[str] = field(default_factory=list)
    output_types: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    resource_type: str = "cpu"
    agent_type: str = ""
    execution_count: int = 0
    success_rate_by_query_type: dict[str, float] = field(default_factory=dict)
    avg_latency_by_resource: dict[str, int] = field(default_factory=dict)


@dataclass
class CapabilityRelation:
    """两个能力之间的有向关系。"""

    from_cap: str
    to_cap: str
    relation_type: str  # "depends_on" | "complements" | "substitutes" | "conflicts_with"（依赖|互补|替代|冲突）
    strength: float = 1.0  # 0.0-1.0
    description: str = ""


@dataclass
class ExecutionRecord:
    """单次执行结果用于反馈学习 — 轻量级，仅内存存储。"""

    capability_type: str
    query_preview: str = ""  # 前 80 个字符
    success: bool = False
    latency_ms: int = 0
    evidence_quality: float = 0.0  # 来自 Evidence 的 credibility_score
    timestamp: float = 0.0


@dataclass
class StrategyRecord:
    """记录执行策略在某轮次中的表现。"""

    strategy_type: str = ""  # "direct" | "parallel" | "sequential" | "compare"（直接|并行|顺序|对比）
    capabilities_used: list[str] = field(default_factory=list)
    query_domain: str = ""  # "finance"、"sales"、"general" 等
    query_preview: str = ""
    success: bool = False
    turn_success: bool = False
    latency_ms: int = 0
    timestamp: float = 0.0
