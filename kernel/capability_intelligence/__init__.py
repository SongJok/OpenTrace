"""能力智能层 — 运行时自我认知。

将系统从「工具调用」升级为「能力认知」：
  - CapabilityProfile：每项能力的丰富语义元数据
  - CapabilityProfiler：构建/增强/查询画像
  - CapabilityAdapter：为 LLM 提示格式化画像
  - CapabilityFeedbackLoop：从执行结果学习

Phase 2 — 运行时自我认知与编排学习：
  - CapabilityKnowledgeGraph：能力间关系图
  - CapabilityReasoner：基于知识图与执行历史的推理
  - ExecutionMemory：结构化时间窗执行统计
  - StrategyMemory：策略模式成功率跟踪
  - EvolutionEngine：持续分析改进

特性开关：
  - kernel_capability_intelligence_enabled（Phase 1 总开关）
  - kernel_capability_intelligence_phase2_enabled（Phase 2 总开关）
"""

from __future__ import annotations

from kernel.capability_intelligence.adapter import CapabilityAdapter

# Phase 2 — 失败记忆（始终可用，无特性开关控制）
from kernel.capability_intelligence.failure_memory import (
    FailureMemory,
    FailureRecord,
    FailureStats,
    failure_memory,
)
from kernel.capability_intelligence.feedback import CapabilityFeedbackLoop
from kernel.capability_intelligence.profile import (
    CapabilityProfile,
    CapabilityRelation,
    ExecutionRecord,
    StrategyRecord,
)
from kernel.capability_intelligence.profiler import (
    CapabilityProfiler,
    capability_profiler,
)


def _capability_intelligence_enabled() -> bool:
    """检查能力智能特性开关是否启用。"""
    try:
        from infra.config.settings import settings

        return bool(
            getattr(settings, "kernel_capability_intelligence_enabled", False)
        )
    except Exception:
        return False


def _capability_intelligence_phase2_enabled() -> bool:
    """检查 Phase 2 能力智能是否启用。"""
    try:
        from infra.config.settings import settings

        return bool(
            getattr(settings, "kernel_capability_intelligence_enabled", False)
            and getattr(
                settings, "kernel_capability_intelligence_phase2_enabled", False
            )
        )
    except Exception:
        return False


# Phase 2 导入 — 延迟加载以避免模块级循环导入
def _get_knowledge_graph():
    from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
    return CapabilityKnowledgeGraph


def _get_execution_memory():
    from kernel.capability_intelligence.execution_memory import execution_memory
    return execution_memory


def _get_strategy_memory():
    from kernel.capability_intelligence.strategy_memory import strategy_memory
    return strategy_memory


__all__ = [
    # Phase 1
    "CapabilityProfile",
    "CapabilityRelation",
    "ExecutionRecord",
    "CapabilityProfiler",
    "capability_profiler",
    "CapabilityAdapter",
    "CapabilityFeedbackLoop",
    "_capability_intelligence_enabled",
    # Phase 2
    "StrategyRecord",
    "_capability_intelligence_phase2_enabled",
    "_get_knowledge_graph",
    "_get_execution_memory",
    "_get_strategy_memory",
    # Failure Memory（失败记忆）
    "FailureMemory",
    "FailureRecord",
    "FailureStats",
    "failure_memory",
]
