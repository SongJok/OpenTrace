"""
RefinePlanner — 有界局部重规划。

DAG 节点执行失败时，仅重建受影响下游子图，不改动已完成节点；最大重规划深度 2 层。
非顶层模型全量重规划，而是针对特定失败类型的确定性、有界补丁操作。
"""

from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from infra.observability.logger import get_logger

warnings.filterwarnings("ignore", category=DeprecationWarning, module=__name__)

logger = get_logger(__name__)


class FailureType(str, Enum):
    SCHEMA_MISMATCH = "schema_mismatch"
    TIMEOUT = "timeout"
    EMPTY_RESULT = "empty_result"
    PERMISSION_DENIED = "permission_denied"
    HALLUCINATION = "hallucination"
    LOW_CRITIC = "low_critic"
    UNKNOWN = "unknown"


class RepairStrategy(str, Enum):
    RETRY = "retry"                   # 重试相同能力（用于瞬时错误）
    SIMPLIFY = "simplify"             # 降低查询复杂度
    SUBSTITUTE = "substitute"         # 替换为替代能力
    SPLIT = "split"                   # 分解为更小的步骤
    PREPEND = "prepend"               # 添加准备步骤（如 schema 检查）
    SKIP = "skip"                     # 跳过此节点，继续执行下游
    ABORT = "abort"                   # 无法修复，中止该分支


# 失败类型 → 推荐修复策略（按优先级排序）
_FAILURE_REPAIR_MAP: dict[FailureType, list[RepairStrategy]] = {
    FailureType.SCHEMA_MISMATCH: [RepairStrategy.PREPEND, RepairStrategy.SIMPLIFY, RepairStrategy.SUBSTITUTE],
    FailureType.TIMEOUT: [RepairStrategy.RETRY, RepairStrategy.SIMPLIFY, RepairStrategy.SUBSTITUTE],
    FailureType.EMPTY_RESULT: [RepairStrategy.SIMPLIFY, RepairStrategy.SUBSTITUTE, RepairStrategy.SKIP],
    FailureType.PERMISSION_DENIED: [RepairStrategy.SUBSTITUTE, RepairStrategy.SKIP, RepairStrategy.ABORT],
    FailureType.HALLUCINATION: [RepairStrategy.SUBSTITUTE, RepairStrategy.SPLIT, RepairStrategy.ABORT],
    FailureType.LOW_CRITIC: [RepairStrategy.SIMPLIFY, RepairStrategy.RETRY, RepairStrategy.SKIP],
    FailureType.UNKNOWN: [RepairStrategy.RETRY, RepairStrategy.SUBSTITUTE, RepairStrategy.ABORT],
}


@dataclass
class CorrectionIntent:
    """检测到的修正需求。"""
    is_correction: bool = False
    failure_type: FailureType = FailureType.UNKNOWN
    failed_node_id: str = ""
    failure_reason: str = ""
    confidence: float = 0.0
    corrected_query: str = ""


@dataclass
class RefinedPlan:
    """有界重规划的结果。"""
    plan: Any = None
    reused_results: dict[str, Any] = field(default_factory=dict)
    replaced_indices: list[int] = field(default_factory=list)
    new_nodes: list[Any] = field(default_factory=list)
    removed_node_ids: list[str] = field(default_factory=list)
    repair_strategy: RepairStrategy = RepairStrategy.ABORT
    depth: int = 0


class RefinePlanner:
    """DAG 节点失败的有界局部重规划。

    关键约束：
    - 最大重规划深度：2 层（防止无限循环）
    - 仅重建失败节点的下游（已完成节点不受影响）
    - 不调用顶层模型 — 确定性的修复策略选择
    - 通过知识图谱查找尝试替代能力
    """

    MAX_REPLAN_DEPTH = 2

    async def detect_correction(
        self,
        query: str,
        previous_plan: Any,
        failed_result: Any = None,
    ) -> CorrectionIntent:
        """检测失败是否需要修正并分类失败类型。"""
        if failed_result is None:
            return CorrectionIntent()

        error_msg = getattr(failed_result, "error", "") or ""
        status = getattr(failed_result, "status", "")

        if status != "error":
            return CorrectionIntent()

        failure_type = self._classify_failure(error_msg, query)
        return CorrectionIntent(
            is_correction=True,
            failure_type=failure_type,
            failed_node_id=getattr(failed_result, "task_id", ""),
            failure_reason=error_msg[:200],
            confidence=0.9,
        )

    def refine_plan(
        self,
        correction_intent: CorrectionIntent,
        previous_plan: Any,
        previous_results: Any,
        query: str,
        depth: int = 0,
    ) -> RefinedPlan:
        """执行有界局部重规划。

        返回仅重建受影响子图的 RefinedPlan。
        已完成的节点通过 reused_results 保留。
        """
        if not correction_intent.is_correction:
            return RefinedPlan(plan=previous_plan, depth=depth)

        if depth >= self.MAX_REPLAN_DEPTH:
            logger.warning(
                "RefinePlanner max depth reached, aborting branch",
                node_id=correction_intent.failed_node_id,
                depth=depth,
            )
            return RefinedPlan(
                plan=previous_plan,
                reused_results=self._collect_reused(previous_results),
                repair_strategy=RepairStrategy.ABORT,
                depth=depth,
            )

        strategies = _FAILURE_REPAIR_MAP.get(
            correction_intent.failure_type,
            [RepairStrategy.RETRY, RepairStrategy.SUBSTITUTE, RepairStrategy.ABORT],
        )

        for strategy in strategies:
            result = self._try_strategy(
                strategy, correction_intent, previous_plan, previous_results, query, depth
            )
            if result is not None:
                return result

        return RefinedPlan(
            plan=previous_plan,
            reused_results=self._collect_reused(previous_results),
            repair_strategy=RepairStrategy.ABORT,
            depth=depth,
        )

    # ── 策略实现 ────────────────────────────────────────────

    def _try_strategy(
        self,
        strategy: RepairStrategy,
        intent: CorrectionIntent,
        plan: Any,
        results: Any,
        query: str,
        depth: int,
    ) -> RefinedPlan | None:
        """尝试单个修复策略。返回 RefinedPlan 或 None。"""
        if strategy == RepairStrategy.RETRY:
            return RefinedPlan(
                plan=plan,
                reused_results=self._collect_reused(results),
                repair_strategy=RepairStrategy.RETRY,
                depth=depth + 1,
            )

        if strategy == RepairStrategy.SKIP:
            return RefinedPlan(
                plan=plan,
                reused_results=self._collect_reused(results),
                removed_node_ids=[intent.failed_node_id],
                repair_strategy=RepairStrategy.SKIP,
                depth=depth + 1,
            )

        if strategy == RepairStrategy.SUBSTITUTE:
            substitute = self._find_substitute(intent)
            if substitute:
                return RefinedPlan(
                    plan=self._replace_node(plan, intent.failed_node_id, substitute),
                    reused_results=self._collect_reused(results),
                    replaced_indices=[0],
                    repair_strategy=RepairStrategy.SUBSTITUTE,
                    depth=depth + 1,
                )

        if strategy == RepairStrategy.PREPEND:
            prepend_node = self._build_prepend_node(intent, query)
            if prepend_node:
                return RefinedPlan(
                    plan=plan,
                    reused_results=self._collect_reused(results),
                    new_nodes=[prepend_node],
                    repair_strategy=RepairStrategy.PREPEND,
                    depth=depth + 1,
                )

        if strategy == RepairStrategy.SIMPLIFY:
            return RefinedPlan(
                plan=self._simplify_plan_for_node(plan, intent.failed_node_id),
                reused_results=self._collect_reused(results),
                repair_strategy=RepairStrategy.SIMPLIFY,
                depth=depth + 1,
            )

        return None

    # ── 辅助方法 ──────────────────────────────────────────────

    def _classify_failure(self, error_msg: str, query: str) -> FailureType:
        """从错误消息分类失败类型。"""
        msg = error_msg.lower()
        if "schema" in msg or "column" in msg or "field" in msg or "mismatch" in msg:
            return FailureType.SCHEMA_MISMATCH
        if "timeout" in msg or "timed out" in msg:
            return FailureType.TIMEOUT
        if "empty" in msg or "no result" in msg or "no data" in msg:
            return FailureType.EMPTY_RESULT
        if "permission" in msg or "denied" in msg or "unauthorized" in msg:
            return FailureType.PERMISSION_DENIED
        if "hallucin" in msg or "fabricat" in msg:
            return FailureType.HALLUCINATION
        if "critic" in msg and ("low" in msg or "fail" in msg):
            return FailureType.LOW_CRITIC
        return FailureType.UNKNOWN

    def _find_substitute(self, intent: CorrectionIntent) -> str | None:
        """通过知识图谱或种子映射查找替代能力。"""
        substitute_map: dict[str, str] = {
            "web.search": "rag.retrieve",
            "rag.retrieve": "web.search",
            "data.analysis": "data.query",
            "data.query": "data.analysis",
            "python.execute": "data.query",
            "chart.generate": "data.analysis",
            "skills.execute": "data.query",
            "vision.analyze": "rag.retrieve",
        }

        try:
            from kernel.capability_intelligence import (
                _capability_intelligence_phase2_enabled,
                capability_profiler,
            )
            if _capability_intelligence_phase2_enabled():
                kg = capability_profiler.get_knowledge_graph()
                if kg is not None:
                    # 尝试查找失败节点代表的能力
                    subs = kg.substitutes_for(intent.failure_type.value)
                    if subs:
                        return subs[0]
        except Exception:
            pass

        return substitute_map.get(intent.failure_type.value)

    def _build_prepend_node(self, intent: CorrectionIntent, query: str) -> Any | None:
        """构建准备节点（如 SQL 前的 schema 检查）。"""
        if intent.failure_type == FailureType.SCHEMA_MISMATCH:
            return {
                "node_id": f"schema_inspect_{intent.failed_node_id}",
                "capability_name": "data.query",
                "capability_type": "data.query",
                "query": f"查看表结构以修复: {intent.failure_reason[:100]}",
                "purpose": "schema_inspection",
                "depends_on": [],
                "priority": "high",
            }
        return None

    def _replace_node(self, plan: Any, failed_node_id: str, substitute: str) -> Any:
        """用替代能力替换失败节点。"""
        if hasattr(plan, "subtasks"):
            for i, task in enumerate(plan.subtasks):
                if getattr(task, "task_id", "") == failed_node_id or \
                   getattr(task, "capability_type", "") == failed_node_id:
                    plan.subtasks[i].capability_type = substitute
                    break
        return plan

    def _simplify_plan_for_node(self, plan: Any, failed_node_id: str) -> Any:
        """简化特定节点的查询部分。"""
        if hasattr(plan, "subtasks"):
            for task in plan.subtasks:
                tid = getattr(task, "task_id", "")
                ct = getattr(task, "capability_type", "")
                if tid == failed_node_id or ct == failed_node_id:
                    q = getattr(task, "query", "")
                    if q and len(q) > 100:
                        task.query = q[:100]  # 截断复杂查询
                    break
        return plan

    def _collect_reused(self, results: Any) -> dict[str, Any]:
        """收集已完成的结果以供复用。"""
        reused: dict[str, Any] = {}
        if isinstance(results, list):
            for r in results:
                task_id = getattr(r, "task_id", "")
                status = getattr(r, "status", "")
                if task_id and status == "success":
                    reused[task_id] = r
        elif isinstance(results, dict):
            for task_id, r in results.items():
                status = getattr(r, "status", "")
                if status == "success":
                    reused[task_id] = r
        return reused


# ── 向后兼容的修正意图 ──────────────────────────

@dataclass
class _CorrectionIntentCompat:
    is_correction: bool = False
    confidence: float = 0.0
    corrected_query: str = ""


# 模块级实例
refine_planner = RefinePlanner()
