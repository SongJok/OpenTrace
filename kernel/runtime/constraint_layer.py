"""
PlannerConstraintLayer — CognitivePlannerV2 输出与 ExecutionRuntime 之间的确定性护栏。
不调用 LLM，纯规则 + 查表。

在计划被允许执行之前，评估五个约束维度：
  1. 预算 — token/延迟/成本上限
  2. 策略 — 权限检查
  3. 风险 — 风险阈值强制执行
  4. 能力 — 可用性 + 替代
  5. 历史先验 — 相似历史计划结果
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kernel.runtime.cognitive.cognitive_graph import CognitivePlan
    from kernel.runtime.context import RuntimeContext

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


# ── 约束评估结果 ──────────────────────────────────────────────────────────────

@dataclass
class ConstraintDecision:
    """对计划运行约束层后的评估结果。"""
    allowed: bool = True
    risk_level: str = "low"  # low | medium | high | critical
    reason: str = ""
    modifications: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # 当计划被拒绝/降级时，提议降级策略
    fallback_strategy: str = ""  # "simplify" | "single_capability" | "direct_answer" | ""


# ── 预算常量 ──────────────────────────────────────────────────────────────────

_DEFAULT_MAX_TOKENS = 4000
_DEFAULT_MAX_LATENCY_MS = 30_000
_DEFAULT_MAX_PARALLEL_CAPABILITIES = 5

# 风险等级 → 最大并行数
_RISK_PARALLEL_MAP: dict[str, int] = {
    "low": 5,
    "medium": 3,
    "high": 1,
    "critical": 1,
}

# 能力 → 预估 token 开销（粗略上界）
_CAP_TOKEN_ESTIMATES: dict[str, int] = {
    "data.query": 600,
    "data.analysis": 900,
    "web.search": 500,
    "rag.retrieve": 400,
    "tool.datetime": 150,
    "tool.weather": 200,
    "tool.calculator": 150,
    "python.execute": 1200,
    "chart.generate": 800,
    "memory.retrieve": 250,
    "entity.resolution": 300,
    "vision.analyze": 700,
    "skills.execute": 600,
}


# ── 各能力权限要求 ────────────────────────────────────────────────────────────

_CAP_PERMISSION_MAP: dict[str, list[str]] = {
    "web.search": ["web_enabled"],
    "data.query": ["data_source_id"],
    "data.analysis": ["data_source_id"],
    "rag.retrieve": ["indexed_documents"],
    "vision.analyze": ["image_data"],
    "python.execute": ["sandbox_enabled"],
}


class PlannerConstraintLayer:
    """确定性约束评估器。不调用模型，不含歧义。"""

    def __init__(self) -> None:
        self._failure_memory: Any = None  # 延迟加载

    # ── 公共 API ────────────────────────────────────────────────────────────

    def evaluate(
        self,
        plan: CognitivePlan,
        ctx: RuntimeContext,
        capability_names: list[str] | None = None,
    ) -> ConstraintDecision:
        """对计划运行全部五项约束检查。返回通过/拒绝/修改。"""

        decision = ConstraintDecision()
        cog_graph = plan.cognitive_graph
        capability_names = capability_names or []

        intent_ok, intent_reason = self._check_intent_constraints(capability_names, ctx)
        if not intent_ok:
            decision.allowed = False
            decision.risk_level = "critical"
            decision.reason = intent_reason
            logger.warning("Plan denied by intent constraints", reason=intent_reason)
            return decision

        # 1. 预算检查
        budget_ok, budget_reason = self._check_budget(capability_names, ctx)
        if not budget_ok:
            decision.warnings.append(budget_reason)
            # 尝试简化：裁剪非关键能力
            decision.modifications.append("trim_non_critical")
            decision.fallback_strategy = "simplify"

        # 2. 策略/权限检查
        policy_ok, policy_reason = self._check_policy(capability_names, ctx)
        if not policy_ok:
            decision.allowed = False
            decision.risk_level = "critical"
            decision.reason = policy_reason
            logger.warning("Plan denied by policy", reason=policy_reason)
            return decision

        # 3. 风险阈值强制执行
        risk_ok, risk_reason, risk_level = self._check_risk(cog_graph.risk_analysis.risk_level)
        decision.risk_level = risk_level
        if not risk_ok:
            decision.warnings.append(risk_reason)
            decision.modifications.append("force_sequential")
            decision.modifications.append("reduce_parallelism")

        # 4. 能力可用性检查
        cap_ok, cap_reason, substitutions = self._check_capabilities(capability_names)
        if not cap_ok:
            decision.warnings.append(cap_reason)
            if substitutions:
                decision.modifications.append(f"substitute:{','.join(substitutions)}")

        # 5. 历史先验检查（尽力而为）
        prior_ok, prior_reason = self._check_historical_prior(plan, ctx)
        if not prior_ok:
            decision.warnings.append(prior_reason)
            decision.modifications.append("adjust_strategy_from_prior")

        return decision

    # ── 预算检查 ──────────────────────────────────────────────────────────

    def _check_budget(
        self, capability_names: list[str], ctx: RuntimeContext
    ) -> tuple[bool, str]:
        """预估总 token 开销并检查预算。"""
        budget = getattr(ctx, "cognitive_budget", {}) or {}
        max_caps = int(budget.get("max_capabilities", _DEFAULT_MAX_PARALLEL_CAPABILITIES) or _DEFAULT_MAX_PARALLEL_CAPABILITIES)
        if len([c for c in capability_names if c]) > max_caps:
            return False, (
                f"Capability count ({len(capability_names)}) exceeds cognitive budget ({max_caps})."
            )
        estimated_tokens = sum(
            _CAP_TOKEN_ESTIMATES.get(c, 500) for c in capability_names
        )
        if not capability_names:
            estimated_tokens = 500  # 单次直接回答

        max_tokens = _DEFAULT_MAX_TOKENS
        if estimated_tokens > max_tokens:
            return False, (
                f"Estimated token cost ({estimated_tokens}) exceeds budget ({max_tokens}). "
                "Consider simplifying the plan."
            )
        return True, "ok"

    def _check_intent_constraints(
        self, capability_names: list[str], ctx: RuntimeContext
    ) -> tuple[bool, str]:
        from kernel.cognitive_controls import normalize_capability_name

        allowed = set(getattr(ctx, "allowed_capabilities", []) or [])
        disallowed = set(getattr(ctx, "disallowed_capabilities", []) or [])
        # 规范化能力名称（如 tool.weather → get_weather）
        normalized = [normalize_capability_name(c) for c in capability_names if c]
        blocked = [c for c in normalized if c in disallowed]
        if blocked:
            return False, f"Capabilities violate protected intent: {', '.join(blocked)}"
        if allowed:
            outside = [c for c in normalized if c not in allowed]
            if outside:
                return False, (
                    f"Capabilities outside allowed set for protected intent: {', '.join(outside)}"
                )
        return True, "ok"

    # ── 策略/权限检查 ─────────────────────────────────────────────────────

    def _check_policy(
        self, capability_names: list[str], ctx: RuntimeContext
    ) -> tuple[bool, str]:
        """检查每个能力的前置条件是否满足。"""
        for cap_name in capability_names:
            required = _CAP_PERMISSION_MAP.get(cap_name, [])
            for req in required:
                if req == "web_enabled" and not ctx.web_enabled:
                    return False, f"Capability '{cap_name}' requires web_enabled=True"
                if req == "data_source_id":
                    ds = getattr(ctx, "data_source_context", {}) or {}
                    if not ds.get("data_source_id"):
                        return False, f"Capability '{cap_name}' requires a bound data_source_id"
                if req == "indexed_documents":
                    # 非阻塞：仅在没有索引文档时警告
                    pass
                if req == "image_data":
                    attachments = getattr(ctx, "attachment_contexts", None)
                    if not attachments:
                        return False, f"Capability '{cap_name}' requires image attachments"
                if req == "sandbox_enabled":
                    sandbox = getattr(settings, "kernel_sandbox_enabled", False)
                    if not sandbox:
                        return False, f"Capability '{cap_name}' requires sandbox"
        return True, "ok"

    # ── 风险检查 ────────────────────────────────────────────────────────────

    def _check_risk(
        self, reported_risk: str
    ) -> tuple[bool, str, str]:
        """强制执行风险阈值。critical 风险始终强制串行执行。"""
        risk = reported_risk.lower()
        if risk == "critical":
            return False, "Risk level is critical; forcing sequential single-capability execution.", "critical"
        if risk == "high":
            return True, f"Risk level is high; max parallelism reduced to {_RISK_PARALLEL_MAP['high']}.", "high"
        return True, "ok", risk

    # ── 能力可用性检查 ─────────────────────────────────────────────────────

    def _check_capabilities(
        self, capability_names: list[str]
    ) -> tuple[bool, str, list[str]]:
        """检查每个所需能力是否在注册表中存在，并建议替代。"""
        from kernel.runtime.capability import capability_registry

        unavailable: list[str] = []
        substitutions: list[str] = []

        for cap_name in capability_names:
            if not capability_registry.get(cap_name):
                unavailable.append(cap_name)
                # 尝试通过知识图谱查找替代
                sub = self._find_substitute(cap_name)
                if sub:
                    substitutions.append(f"{cap_name}→{sub}")

        if unavailable and not substitutions:
            return False, f"Capabilities unavailable and no substitutes: {', '.join(unavailable)}", []
        if unavailable:
            return False, (
                f"Capabilities unavailable: {', '.join(unavailable)}. "
                f"Substitutes: {', '.join(substitutions)}"
            ), substitutions

        return True, "ok", []

    def _find_substitute(self, cap_name: str) -> str | None:
        """通过知识图谱或种子映射查找替代能力。"""
        # 硬编码替代映射作为后备
        substitute_map: dict[str, str] = {
            "web.search": "rag.retrieve",
            "rag.retrieve": "web.search",
            "data.analysis": "data.query",
            "python.execute": "data.query",
            "chart.generate": "data.analysis",
        }

        # 优先尝试知识图谱
        try:
            from kernel.capability_intelligence import (
                _capability_intelligence_phase2_enabled,
                capability_profiler,
            )
            if _capability_intelligence_phase2_enabled():
                kg = capability_profiler.get_knowledge_graph()
                if kg is not None:
                    subs = kg.substitutes_for(cap_name)
                    if subs:
                        return subs[0]
        except Exception as exc:
            logger.debug("constraint_layer_kg_substitute_skipped", error=str(exc))

        return substitute_map.get(cap_name)

    # ── 历史先验检查 ────────────────────────────────────────────────────────

    def _check_historical_prior(
        self, plan: CognitivePlan, ctx: RuntimeContext
    ) -> tuple[bool, str]:
        """检查 execution_memory 和 failure_memory 中相似历史计划的结果。"""
        try:
            from kernel.capability_intelligence import _capability_intelligence_phase2_enabled
            if not _capability_intelligence_phase2_enabled():
                return True, "ok"

            from kernel.capability_intelligence.execution_memory import execution_memory
            from kernel.capability_intelligence.failure_memory import failure_memory

            # 扫描计划能力以检测退化信号
            cap_types = self._extract_cap_types_from_plan(plan)
            degraded: list[str] = []
            failed: list[str] = []

            for ct in cap_types:
                # 先检查失败记忆
                recent_failures = failure_memory.get_recent_failures(ct, window_seconds=3600)
                if recent_failures and len(recent_failures) >= 3:
                    failed.append(ct)

                # 然后检查执行记忆中的退化
                deg = execution_memory.degradation_check(ct, threshold=0.25)
                if deg is not None:
                    degraded.append(ct)

            if failed:
                return False, (
                    f"Capabilities with recent repeated failures (last 1h): {', '.join(failed)}. "
                    "Consider alternative capabilities or simplified strategy."
                )
            if degraded:
                return False, (
                    f"Capabilities showing degradation: {', '.join(degraded)}. "
                    "Recent success rate significantly below historical average."
                )

            return True, "ok"
        except Exception:
            return True, "ok"  # 尽力而为，不得因此阻塞

    def _extract_cap_types_from_plan(self, plan: CognitivePlan) -> list[str]:
        """提取 CognitivePlan 中引用的能力类型。"""
        cap_types: list[str] = []
        for gap in plan.cognitive_graph.information_gaps:
            source = gap.suggested_source
            if source and source not in cap_types:
                cap_types.append(source)
        # 也从执行提示中提取
        hints = plan.execution_hints
        if isinstance(hints, dict):
            for cap_type in hints.get("required_capabilities", []):
                if cap_type not in cap_types:
                    cap_types.append(str(cap_type))
        return cap_types


# ── 模块级单例 ────────────────────────────────────────────────────────────

constraint_layer = PlannerConstraintLayer()
