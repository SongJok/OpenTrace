"""
VerificationAgent — 执行前多维度 SQL 校验。

封装 SQLValidator，并增加业务语义校验：
1. 语法（只读、防注入）
2. 语义合理性（禁止 LIMIT 0、WHERE 1=0）
3. 意图覆盖（SQL 含指标/实体/时间过滤）
4. 业务指标口径（SQL 与 metric_definitions.formula 一致）
"""
from __future__ import annotations

import json
import re

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class VerificationAgent(BaseAgent):
    """执行前多维度 SQL 校验。

    返回包含 pass/warning/fail 状态和可操作问题列表的校验报告。
    """

    def __init__(self) -> None:
        super().__init__("data_verification")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            sql = ctx.compiled_sql
            if not sql:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    error="no compiled_sql to verify",
                    metadata={"cognitive_context": ctx.to_dict()},
                )

            report = await self._verify(sql, ctx)
            ctx.verification_report = report

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=json.dumps(report, ensure_ascii=False),
                confidence=self._report_confidence(report),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="verification_agent",
                    source_type="data_cognition",
                    payload=report,
                    credibility=0.95,
                    relevance=1.0,
                )],
                agent_trace=report,
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error=str(exc),
                metadata={"cognitive_context": ctx.to_dict()},
            )

    async def _verify(self, sql: str, ctx: CognitiveContext) -> dict:
        issues: list[dict] = []

        # 1. 结构校验
        try:
            from kernel.data_cognition.sql_validator import SQLValidator
            validator = SQLValidator(default_limit=100)
            validator.validate(sql)
        except Exception as exc:
            issues.append({
                "type": "structural",
                "detail": str(exc),
                "severity": "critical",
            })

        # 2. 语义合理性检查
        sql_lower = sql.lower()
        if "limit 0" in sql_lower:
            issues.append({
                "type": "semantic_sanity",
                "detail": "LIMIT 0 — query will return zero rows",
                "severity": "high",
            })
        if "where 1=0" in sql_lower or "where false" in sql_lower:
            issues.append({
                "type": "semantic_sanity",
                "detail": "WHERE 1=0 or WHERE FALSE — query will return zero rows",
                "severity": "high",
            })

        # 3. 意图覆盖：时间过滤
        if ctx.time_window and ctx.time_window.get("type") not in (None, "none"):
            if "where" not in sql_lower:
                issues.append({
                    "type": "time_coverage",
                    "detail": "Time window specified but no WHERE clause for time filtering",
                    "severity": "medium",
                })

        # 4. 意图覆盖：指标
        if ctx.metrics:
            for metric in ctx.metrics:
                col = metric.get("mapped_column", "")
                if col and col.lower() not in sql_lower:
                    issues.append({
                        "type": "metric_coverage",
                        "detail": f"Metric column '{col}' not found in SQL",
                        "severity": "medium",
                    })

        # 5. 意图覆盖：实体（表）
        if ctx.entities:
            for entity in ctx.entities:
                table = entity.get("mapped_table", "")
                if table and table.lower() not in sql_lower:
                    issues.append({
                        "type": "entity_coverage",
                        "detail": f"Entity table '{table}' not found in SQL",
                        "severity": "medium",
                    })

        # 6. 业务指标口径校验 — 对比 SQL 与 metric_definitions
        if ctx.matched_metrics:
            for mm in ctx.matched_metrics:
                formula = (mm.get("formula") or "").lower()
                if formula and not self._formula_overlaps(formula, sql_lower):
                    issues.append({
                        "type": "metric_grounding",
                        "detail": f"Metric '{mm.get('name')}' formula may not be reflected in SQL",
                        "severity": "low",
                    })

        # 确定整体状态
        criticals = [i for i in issues if i["severity"] == "critical"]
        highs = [i for i in issues if i["severity"] == "high"]

        if criticals:
            status = "fail"
        elif highs:
            status = "warning"
        else:
            status = "pass"

        return {
            "status": status,
            "issues": issues,
            "critical_count": len(criticals),
            "high_count": len(highs),
            "total_issues": len(issues),
            "coverage_score": self._coverage_score(issues),
        }

    def _formula_overlaps(self, formula: str, sql: str) -> bool:
        """检查公式关键词是否出现在 SQL 中。"""
        formula_tokens = re.findall(r"[a-z_]+", formula)
        if not formula_tokens:
            return True  # 无法检查
        matches = sum(1 for t in formula_tokens if t in sql)
        return matches / len(formula_tokens) >= 0.5

    def _coverage_score(self, issues: list[dict]) -> float:
        if not issues:
            return 1.0
        weights = {"critical": -0.3, "high": -0.15, "medium": -0.05, "low": -0.02}
        score = 1.0
        for issue in issues:
            score += weights.get(issue.get("severity", "low"), 0)
        return max(0.0, min(1.0, score))

    def _report_confidence(self, report: dict) -> float:
        status = report.get("status", "fail")
        if status == "pass":
            return 0.95
        elif status == "warning":
            return 0.70
        return 0.30
