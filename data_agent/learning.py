"""把真实执行转化为可审计、可撤销的 DataAgent 经验。"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from data_agent.contracts import CandidateSQL, LearningRecord, LogicalQueryPlan, QueryRun, RunState


def plan_pattern_key(plan: LogicalQueryPlan) -> str:
    payload = {
        "intent": plan.intent,
        "metrics": [
            {
                "name": metric.name.lower(),
                "version": metric.version,
                "formula": " ".join(metric.formula.lower().split()),
            }
            for metric in plan.metrics
        ],
        "dimensions": sorted(
            f"{dimension.table or ''}.{dimension.column or dimension.name}".lower()
            for dimension in plan.dimensions
        ),
        "tables": sorted(table.lower() for table in plan.required_tables),
        "grain": sorted(value.lower() for value in plan.grain),
        "comparison": plan.comparison,
        "output_shape": plan.output_shape,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def sql_structure_hash(sql: str, *, dialect: str) -> str:
    try:
        expression = parse_one(sql, read=dialect or None)

        def replace_literal(node: exp.Expression) -> exp.Expression:
            if isinstance(node, exp.Literal):
                return exp.Placeholder()
            return node

        normalized = expression.transform(replace_literal).sql(
            dialect=dialect or None,
            comments=False,
            normalize=True,
            pretty=False,
        )
    except (ParseError, TypeError, ValueError):
        normalized = " ".join(str(sql or "").lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def result_signature(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ExecutionLearningEngine:
    def __init__(self, *, minimum_confidence: float = 0.85) -> None:
        self.minimum_confidence = minimum_confidence

    def evaluate(self, run: QueryRun, candidate: CandidateSQL) -> LearningRecord:
        plan = run.logical_plan
        evidence = run.evidence
        reasons: list[str] = []
        if plan is None or evidence is None:
            return LearningRecord(
                pattern_key="missing-plan",
                status="ineligible",
                reasons=["缺少逻辑计划或证据包"],
            )
        pattern_key = plan_pattern_key(plan)
        if run.state != RunState.COMPLETED:
            reasons.append("运行未成功完成")
        if not evidence.schema_fingerprint or not evidence.semantic_version:
            reasons.append("缺少 Schema 或语义版本，经验无法安全复用")
        if plan.authority_conflicts:
            reasons.append("业务证据仍存在权威冲突")
        if plan.confidence < self.minimum_confidence:
            reasons.append(
                f"逻辑计划置信度 {plan.confidence:.2f} 低于学习阈值 {self.minimum_confidence:.2f}"
            )
        if candidate.validation.errors:
            reasons.append("候选 SQL 存在验证错误")
        if any(issue.severity == "warning" for issue in candidate.validation.issues):
            reasons.append("候选 SQL 仍存在治理警告")
        if run.preflight is None:
            reasons.append("缺少数据库 EXPLAIN 预检")
        elif run.preflight.status != "pass":
            reasons.append("数据库 EXPLAIN 预检未完全通过")
        if run.result is None:
            reasons.append("缺少真实执行结果")
        elif not run.result.rows or run.result.returned_rows <= 0:
            reasons.append("空结果不能形成可复用执行经验")
        elif run.result.truncated:
            reasons.append("结果被截断，不能作为稳定结果经验")
        if run.result_validation is None or run.result_validation.status != "pass":
            reasons.append("结果完整性或质量验证未完全通过")
        if not plan.evidence_ids:
            reasons.append("逻辑计划没有可追溯业务证据")
        evidence_by_id = {item.source_id: item for item in evidence.items}
        for metric in plan.metrics:
            source = evidence_by_id.get(str(metric.source_evidence_id or ""))
            if (
                source is None
                or source.type.value != "metric"
                or source.authority.value not in {"governed", "verified"}
            ):
                reasons.append(f"指标 {metric.name} 缺少公司认证或已验证的指标契约")
        if reasons:
            return LearningRecord(
                pattern_key=pattern_key,
                status="ineligible",
                confidence=plan.confidence,
                reasons=reasons,
                evidence_ids=plan.evidence_ids,
            )

        confidence = plan.confidence * 0.45 + evidence.highest_authority * 0.20 + 0.20
        if candidate.source == "semantic_compiler":
            confidence += 0.10
        if run.answer_citations:
            confidence += 0.05
        return LearningRecord(
            pattern_key=pattern_key,
            status="observed",
            confidence=min(1.0, confidence),
            observation_count=1,
            success_count=1,
            reusable=False,
            reasons=["真实执行、SQL 校验和结果验证均通过，已记录为待强化经验"],
            evidence_ids=plan.evidence_ids,
        )
