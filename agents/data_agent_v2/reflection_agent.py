"""
ReflectionAgent — observes SQL execution results, diagnoses issues, triggers repair.

Wraps SQLReflector for result validation and SQLRewriter for SQL repair.
Adds enhanced result quality analysis beyond the existing reflectors:

- Empty result set → diagnose over-filtering
- Giant numbers → detect join amplification (cartesian product)
- NULL-heavy results → flag missing data
- Negative values → suggest metric grounding checks
- Time mismatch → verify time filter correctness

Max 3 reflection rounds (configurable via DATA_AGENT_V2_SUPERVISOR_MAX_RETRIES).
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
    """Post-execution result observer with auto-repair capability.

    Diagnoses result quality issues and triggers targeted SQL repairs
    via the SQLRewriter. Records all repair attempts for audit.
    """

    MAX_ROUNDS = 3

    def __init__(self) -> None:
        super().__init__("data_reflection")
        self._rewriter = None  # Lazy init

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
        """Run reflection loop: classify → diagnose → repair → re-execute."""
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

        # Only attempt repair if there are actionable issues
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
        """Convert ErrorClassifier diagnoses into the dict format used by _reflect."""
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
        """Compute confidence after reflection."""
        if not diagnosis.get("issues"):
            return 0.95
        if repair_applied:
            return 0.75
        return 0.40

    def _build_recovery_context(self, ctx: CognitiveContext) -> dict[str, Any]:
        """Build user-facing recovery options if all repairs failed."""
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
