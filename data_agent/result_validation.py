"""执行结果的一致性、完整性与数据质量验证。"""

from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any

from data_agent.contracts import (
    EvidenceBundle,
    EvidenceType,
    ExecutionResult,
    LogicalQueryPlan,
    ResultValidationReport,
    ValidationIssue,
)


class ResultValidator:
    def validate(
        self,
        plan: LogicalQueryPlan,
        result: ExecutionResult,
        evidence: EvidenceBundle,
    ) -> ResultValidationReport:
        issues: list[ValidationIssue] = []
        checks: dict[str, Any] = {
            "returned_rows": result.returned_rows,
            "truncated": result.truncated,
            "columns": result.columns,
        }
        if result.returned_rows != len(result.rows):
            issues.append(
                ValidationIssue(
                    code="row_count_mismatch",
                    message="执行器报告的返回行数与实际结果行数不一致",
                )
            )
        if result.truncated:
            issues.append(
                ValidationIssue(
                    code="result_truncated",
                    message="结果达到返回上限，不能将当前结果描述为完整数据",
                    severity="warning",
                )
            )
        if not result.rows:
            issues.append(
                ValidationIssue(
                    code="empty_result",
                    message="查询结果为空，需要核对时间范围、指标过滤和数据新鲜度",
                    severity="warning",
                )
            )

        null_counts: Counter[str] = Counter()
        negative_counts: Counter[str] = Counter()
        numeric_counts: Counter[str] = Counter()
        for row in result.rows:
            for column, value in row.items():
                if value is None:
                    null_counts[column] += 1
                if isinstance(value, int | float) and not isinstance(value, bool):
                    numeric_counts[column] += 1
                    if value < 0:
                        negative_counts[column] += 1
        checks["null_counts"] = dict(null_counts)
        checks["negative_counts"] = dict(negative_counts)

        quality_assets = evidence.of_type(EvidenceType.DATA_QUALITY)
        for item in quality_assets:
            payload = item.payload
            column = str(payload.get("column") or "")
            max_null_rate = payload.get("max_null_rate")
            if column and max_null_rate is not None and result.rows:
                actual = null_counts[column] / len(result.rows)
                if actual > float(max_null_rate):
                    issues.append(
                        ValidationIssue(
                            code="null_rate_exceeded",
                            message=(
                                f"字段 {column} 空值率 {actual:.2%} 超过治理阈值 "
                                f"{float(max_null_rate):.2%}"
                            ),
                            severity="error" if payload.get("blocking") else "warning",
                            evidence_id=item.id,
                        )
                    )

        for metric in plan.metrics:
            positive_only = any(
                bool(item.payload.get("positive_only"))
                for item in quality_assets
                if str(item.payload.get("metric") or "") == metric.name
            )
            if positive_only:
                matching = [
                    column
                    for column in negative_counts
                    if column.lower() == metric.name.lower() or len(plan.metrics) == 1
                ]
                if any(negative_counts[column] for column in matching):
                    issues.append(
                        ValidationIssue(
                            code="unexpected_negative_metric",
                            message=f"指标 {metric.name} 出现治理规则不允许的负值",
                            severity="warning",
                            evidence_id=metric.source_evidence_id,
                        )
                    )

        baseline_values: list[float] = []
        for item in evidence.of_type(EvidenceType.EXECUTION_MEMORY):
            summary = item.payload.get("numeric_result_summary") or {}
            for column_summary in summary.values():
                if isinstance(column_summary, dict) and isinstance(
                    column_summary.get("avg"), int | float
                ):
                    baseline_values.append(float(column_summary["avg"]))
        current_numeric = [
            float(value)
            for row in result.rows
            for value in row.values()
            if isinstance(value, int | float) and not isinstance(value, bool)
        ]
        baseline: dict[str, Any] = {}
        if baseline_values and len(current_numeric) == 1:
            expected = median(baseline_values)
            actual = current_numeric[0]
            baseline = {
                "historical_median": expected,
                "actual": actual,
                "sample_count": len(baseline_values),
            }
            if expected != 0:
                ratio = abs(actual / expected)
                baseline["ratio"] = ratio
                if ratio < 0.1 or ratio > 10:
                    issues.append(
                        ValidationIssue(
                            code="historical_baseline_anomaly",
                            message=(
                                f"结果与同作用域历史执行中位数偏差显著：当前 {actual:g}，"
                                f"历史中位数 {expected:g}"
                            ),
                            severity="warning",
                        )
                    )

        errors = [item for item in issues if item.severity == "error"]
        status = "fail" if errors else ("warn" if issues else "pass")
        return ResultValidationReport(
            status=status,
            issues=issues,
            checks=checks,
            baseline=baseline,
        )
