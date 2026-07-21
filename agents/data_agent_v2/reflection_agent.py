"""
ReflectionAgent — 观察 SQL 执行结果、诊断问题并触发修复。

封装 SQLReflector（结果校验）与 SQLRewriter（SQL 修复），并增强结果质量分析：

- 空结果集 → 诊断过滤过严
- 异常大数值 → 检测 JOIN 放大（笛卡尔积）
- 空值过多 → 标记缺失数据
- 负值 → 建议指标口径校验
- 时间不匹配 → 校验时间过滤

最多 3 轮反思（可由 DATA_AGENT_V2_SUPERVISOR_MAX_RETRIES 配置）。
"""
from __future__ import annotations

import json
import time
from typing import Any

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class ReflectionAgent(BaseAgent):
    """执行后结果观察器，具备自动修复能力。

    诊断结果质量问题，通过 SQLRewriter 触发定向 SQL 修复。
    记录所有修复尝试以供审计。
    """

    MAX_ROUNDS = 3

    def __init__(self) -> None:
        super().__init__("data_reflection")
        self._rewriter = None  # 延迟初始化

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            result = await self._reflect(ctx)
            ctx = result["context"]

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=result["summary"],
                confidence=result["confidence"],
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="reflection_agent",
                    source_type="data_cognition",
                    payload={
                        "rounds": ctx.reflection_rounds,
                        "diagnosis": result.get("diagnosis"),
                        "repair_applied": result.get("repair_applied", False),
                    },
                    credibility=0.85,
                    relevance=0.95,
                )],
                agent_trace={
                    "reflection_rounds": ctx.reflection_rounds,
                    "diagnosis": result.get("diagnosis"),
                    "repair_sql": result.get("repair_sql"),
                    "original_sql": result.get("original_sql"),
                },
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="reflection skipped",
                confidence=0.5,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    async def _reflect(self, ctx: CognitiveContext) -> dict[str, Any]:
        """运行反思循环：分类 → 诊断 → 修复 → 重新执行。"""
        from kernel.data_cognition.sql_rewriter import SQLRewriter
        from agents.data_agent_v2.error_classifier import ErrorClassifier

        if self._rewriter is None:
            self._rewriter = SQLRewriter()

        original_sql = ctx.compiled_sql or ""
        rows = ctx.execution_rows or []
        error = ctx.execution_error or ""
        verification = ctx.verification_report or {}

        classifier = ErrorClassifier()
        diagnoses = classifier.classify_runtime_issue(rows, error, verification, ctx)

        diagnosis = self._build_diagnosis_dict(diagnoses)
        repair_applied = False
        repaired_sql = ""
        summary = ""

        # 仅在存在可修复问题时尝试修复
        if diagnosis["can_repair"] and ctx.reflection_rounds < self.MAX_ROUNDS:
            ctx.reflection_rounds += 1

            repair_prompt = classifier.get_repair_prompt(diagnoses)
            error_desc = diagnosis["summary"]

            repaired_sql = await self._rewriter.rewrite(
                sql=original_sql,
                error=error_desc + "\n" + repair_prompt,
                schema_hint=ctx.schema_hint,
            )

            if repaired_sql and repaired_sql != original_sql:
                ctx.compiled_sql = repaired_sql
                repair_applied = True
                summary = (
                    f"Reflection round {ctx.reflection_rounds}: "
                    f"{diagnosis['summary']}. SQL repaired."
                )
            else:
                summary = (
                    f"Reflection round {ctx.reflection_rounds}: "
                    f"{diagnosis['summary']}. Repair could not improve SQL."
                )
        elif diagnosis["can_repair"]:
            summary = f"Max reflection rounds ({self.MAX_ROUNDS}) reached. {diagnosis['summary']}"
        else:
            summary = f"Results look good — {diagnosis['summary']}"

        return {
            "context": ctx,
            "diagnosis": diagnosis,
            "repair_applied": repair_applied,
            "repair_sql": repaired_sql,
            "original_sql": original_sql,
            "summary": summary,
            "confidence": self._result_confidence(diagnosis, repair_applied),
        }

    def _build_diagnosis_dict(
        self, diagnoses: list
    ) -> dict[str, Any]:
        """将 ErrorClassifier 诊断结果转换为 _reflect 使用的字典格式。"""
        if not diagnoses:
            return {
                "can_repair": False,
                "issues": [],
                "categories": [],
                "summary": "no issues detected",
                "validation": {"passed": True, "issues": [], "severity": "info"},
            }

        issues: list[str] = []
        categories: list[str] = []
        has_repairable = False

        for d in diagnoses:
            issues.append(d.description)
            categories.append(d.category.value)
            if d.repairable:
                has_repairable = True

        return {
            "can_repair": has_repairable,
            "issues": issues,
            "categories": categories,
            "summary": f"{len(diagnoses)} issue(s) detected: {', '.join(categories)}",
            "validation": {
                "passed": not has_repairable,
                "issues": issues,
                "severity": "error" if has_repairable else "warning",
            },
        }

    def _result_confidence(self, diagnosis: dict, repair_applied: bool) -> float:
        """反思后计算置信度。"""
        if not diagnosis.get("issues"):
            return 0.95
        if repair_applied:
            return 0.75
        return 0.40

    def _build_recovery_context(self, ctx: CognitiveContext) -> dict[str, Any]:
        """构建面向用户的恢复选项（所有修复均失败时）。"""
        from agents.data_agent_v2.error_classifier import ErrorClassifier

        classifier = ErrorClassifier()
        rows = ctx.execution_rows or []
        error = ctx.execution_error or ""
        verification = ctx.verification_report or {}
        diagnoses = classifier.classify_runtime_issue(rows, error, verification, ctx)
        suggestions = classifier.get_recovery_suggestions(diagnoses)

        return {
            "query": ctx.query,
            "compiled_sql": ctx.compiled_sql,
            "execution_error": ctx.execution_error,
            "reflection_rounds": ctx.reflection_rounds,
            "diagnoses": [
                {"category": d.category.value, "severity": d.severity, "description": d.description}
                for d in diagnoses
            ],
            "suggestions": suggestions,
        }
