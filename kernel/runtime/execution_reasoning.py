"""
ExecutionReasoning — 为认知运行时的每个执行决策生成确定性、可读的推理轨迹。

生成结构化推理，回答：
  - 为什么选择这些能力？
  - 为什么是这个执行顺序？
  - 跳过了什么，为什么？
  - 每个决策的置信度是多少？

这不是 LLM 调用。它是一个确定性轨迹构建器，读取约束决策、策略投影
和能力画像，将其渲染为可解释的格式。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CapabilityChoice:
    """选择特定能力的推理。"""
    capability_name: str = ""
    capability_type: str = ""
    score: float = 0.0
    reason: str = ""
    alternatives_considered: list[str] = field(default_factory=list)
    confidence: float = 0.8


@dataclass
class ExecutionStepReasoning:
    """执行计划中单步的推理。"""
    step_index: int = 0
    capability: CapabilityChoice = field(default_factory=CapabilityChoice)
    why_this_order: str = ""
    depends_on: list[str] = field(default_factory=list)
    expected_output: str = ""


@dataclass
class ExecutionReasoning:
    """一次执行的完整推理轨迹。"""
    request_id: str = ""
    session_id: str = ""
    query: str = ""
    timestamp: str = ""
    # 能力选择推理
    capability_choices: list[CapabilityChoice] = field(default_factory=list)
    # 执行顺序推理
    execution_steps: list[ExecutionStepReasoning] = field(default_factory=list)
    # 跳过的能力
    skipped_capabilities: list[dict[str, str]] = field(default_factory=list)
    # 约束决策
    constraint_decisions: list[str] = field(default_factory=list)
    # 整体置信度
    overall_confidence: float = 0.8
    # 摘要
    summary: str = ""


class ExecutionReasoningBuilder:
    """构建确定性执行推理轨迹。"""

    def build(
        self,
        query: str,
        request_id: str = "",
        session_id: str = "",
        plan: Any = None,
        capability_assignments: list[Any] | None = None,
        constraint_modifications: list[str] | None = None,
        skipped: list[str] | None = None,
        profiles: dict[str, Any] | None = None,
    ) -> ExecutionReasoning:
        """从计划 + 能力分配 + 约束构建完整的执行推理轨迹。"""

        reasoning = ExecutionReasoning(
            request_id=request_id,
            session_id=session_id,
            query=query,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )

        profiles = profiles or {}

        # 1. 构建能力选择推理
        if capability_assignments:
            for i, assignment in enumerate(capability_assignments):
                cap_type = getattr(assignment, "capability_type", "unknown")
                profile = profiles.get(cap_type)
                choice = CapabilityChoice(
                    capability_name=getattr(assignment, "capability_name", cap_type),
                    capability_type=cap_type,
                    score=getattr(assignment, "score", 0.0),
                    reason=self._build_choice_reason(cap_type, profile),
                    alternatives_considered=self._get_alternatives(cap_type, profiles),
                    confidence=getattr(profile, "reliability", 0.8) if profile else 0.8,
                )
                reasoning.capability_choices.append(choice)

                step = ExecutionStepReasoning(
                    step_index=i,
                    capability=choice,
                    why_this_order=self._build_order_reason(i, assignment, capability_assignments),
                    depends_on=getattr(assignment, "depends_on", []),
                    expected_output=getattr(assignment, "expected_output", ""),
                )
                reasoning.execution_steps.append(step)

        # 2. 记录跳过的能力
        for sk in (skipped or []):
            reasoning.skipped_capabilities.append({
                "capability": sk,
                "reason": self._build_skip_reason(sk, profiles),
            })

        # 3. 记录约束决策
        reasoning.constraint_decisions = constraint_modifications or []

        # 4. 计算整体置信度
        if reasoning.capability_choices:
            confidences = [c.confidence for c in reasoning.capability_choices]
            reasoning.overall_confidence = sum(confidences) / len(confidences)

        # 5. 构建摘要
        reasoning.summary = self._build_summary(reasoning)

        return reasoning

    def build_minimal(
        self,
        query: str,
        capabilities_used: list[str],
        reason: str = "Rule-based routing",
    ) -> ExecutionReasoning:
        """为简单/快速路径查询构建轻量推理轨迹。"""
        return ExecutionReasoning(
            query=query,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            capability_choices=[
                CapabilityChoice(
                    capability_name=cap,
                    capability_type=cap,
                    reason=reason,
                    confidence=0.95,
                )
                for cap in capabilities_used
            ],
            summary=f"Simple query routed via {reason}. Capabilities: {', '.join(capabilities_used)}.",
            overall_confidence=0.95,
        )

    def build_constraint_reasoning(
        self,
        query: str,
        constraint_decision: Any,
    ) -> ExecutionReasoning:
        """构建聚焦于约束决策的推理轨迹。"""
        allowed = getattr(constraint_decision, "allowed", True)
        modifications = getattr(constraint_decision, "modifications", [])
        warnings = getattr(constraint_decision, "warnings", [])
        reason = getattr(constraint_decision, "reason", "")

        return ExecutionReasoning(
            query=query,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            constraint_decisions=(
                modifications + warnings + ([reason] if reason else [])
            ),
            overall_confidence=0.7 if not allowed else 0.9,
            summary=(
                f"Plan {'approved' if allowed else 'denied'}: {reason}. "
                f"Modifications: {', '.join(modifications) if modifications else 'none'}."
            ),
        )

    # ── 私有辅助 ───────────────────────────────────────────────────────

    def _build_choice_reason(
        self, cap_type: str, profile: Any | None
    ) -> str:
        """构建选择某能力的可读理由。"""
        if profile is None:
            return f"Selected {cap_type} based on capability matching."

        parts: list[str] = []
        if hasattr(profile, "strengths") and profile.strengths:
            parts.append(f"strengths: {', '.join(profile.strengths[:2])}")
        if hasattr(profile, "reliability"):
            parts.append(f"reliability: {profile.reliability:.0%}")
        if hasattr(profile, "expected_latency_ms") and profile.expected_latency_ms:
            parts.append(f"latency: ~{profile.expected_latency_ms}ms")

        return f"Selected {cap_type} — {'; '.join(parts)}."

    def _get_alternatives(
        self, cap_type: str, profiles: dict[str, Any]
    ) -> list[str]:
        """列出被考虑过的替代能力。"""
        alternatives: list[str] = []
        for name, profile in profiles.items():
            if name != cap_type and hasattr(profile, "reliability"):
                alternatives.append(name)
        return alternatives[:3]

    def _build_order_reason(
        self,
        index: int,
        assignment: Any,
        all_assignments: list[Any],
    ) -> str:
        """解释为什么该能力在此位置执行。"""
        deps = getattr(assignment, "depends_on", [])
        if not deps:
            return f"Step {index}: no dependencies, can run in parallel with other independent steps."
        dep_names = [d for d in deps]
        return f"Step {index}: depends on [{', '.join(dep_names)}], runs after they complete."

    def _build_skip_reason(
        self, cap_type: str, profiles: dict[str, Any]
    ) -> str:
        """解释为什么某能力被跳过。"""
        profile = profiles.get(cap_type)
        if profile is None:
            return f"{cap_type} is not available in the current registry."
        reliability = getattr(profile, "reliability", 0)
        if reliability < 0.6:
            return f"{cap_type} reliability ({reliability:.0%}) below threshold."
        return f"{cap_type} was redundant or unnecessary for this query."

    def _build_summary(self, reasoning: ExecutionReasoning) -> str:
        """构建执行推理的一段式摘要。"""
        parts: list[str] = []

        if reasoning.capability_choices:
            cap_names = [c.capability_name for c in reasoning.capability_choices]
            parts.append(f"Selected {len(cap_names)} capabilities: {', '.join(cap_names)}.")

        if reasoning.skipped_capabilities:
            skipped = [s["capability"] for s in reasoning.skipped_capabilities]
            parts.append(f"Skipped {len(skipped)}: {', '.join(skipped)}.")

        if reasoning.constraint_decisions:
            parts.append(f"Constraints applied: {', '.join(reasoning.constraint_decisions[:3])}.")

        if not parts:
            return "Direct execution, no reasoning required."

        parts.append(f"Overall confidence: {reasoning.overall_confidence:.0%}.")
        return " ".join(parts)


# 模块级单例
execution_reasoning_builder = ExecutionReasoningBuilder()
