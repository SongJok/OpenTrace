"""执行策略：把 SQL 校验、数据敏感性和用户确认统一成一个闸门。"""

from __future__ import annotations

from text2sql.contracts import (
    EvidenceBundle,
    EvidenceType,
    LogicalQueryPlan,
    PolicyDecision,
    QueryRequest,
    ValidationReport,
)


class ExecutionPolicy:
    def decide(
        self,
        request: QueryRequest,
        plan: LogicalQueryPlan,
        report: ValidationReport,
        evidence: EvidenceBundle,
    ) -> PolicyDecision:
        reasons: list[str] = []
        if report.errors:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=False,
                reasons=["SQL 未通过静态验证"] + [item.message for item in report.errors[:5]],
                risk_level="blocked",
            )
        sensitive = any(
            item.sensitive or item.payload.get("sensitive") or item.payload.get("is_sensitive")
            for item in evidence.items
        )
        unverified_join = any(item.code == "unverified_join" for item in report.issues)
        blocking_quality = any(
            item.type == EvidenceType.DATA_QUALITY and bool(item.payload.get("blocking"))
            for item in evidence.items
        )
        source_policy_blocked = any(
            item.type == EvidenceType.SOURCE_POLICY
            and bool(item.payload.get("blocked") or item.payload.get("deny_sql_generation"))
            for item in evidence.items
        )
        source_policy_execution_blocked = any(
            item.type == EvidenceType.SOURCE_POLICY and bool(item.payload.get("deny_execution"))
            for item in evidence.items
        )
        source_policy_approval = any(
            item.type == EvidenceType.SOURCE_POLICY
            and bool(
                item.payload.get("requires_approval") or item.payload.get("requires_confirmation")
            )
            for item in evidence.items
        )
        if sensitive:
            reasons.append("查询上下文或字段包含敏感数据")
        if unverified_join:
            reasons.append("查询包含未验证的 JOIN 关系")
        if blocking_quality:
            reasons.append("数据质量资产标记当前数据不可用于可靠回答")
        if source_policy_execution_blocked:
            reasons.append("数据源策略明确禁止查询执行")
        if source_policy_approval:
            reasons.append("数据源策略要求额外审批或确认")
        if plan.missing_information:
            reasons.append("逻辑计划仍有未解决的信息缺口")
        if source_policy_blocked or (
            request.mode.value == "execute_and_answer" and source_policy_execution_blocked
        ):
            return PolicyDecision(
                allowed=False,
                requires_confirmation=False,
                reasons=reasons,
                risk_level="blocked",
            )
        if request.mode.value == "sql_only":
            return PolicyDecision(
                allowed=True,
                requires_confirmation=False,
                reasons=reasons or ["仅生成 SQL，不执行数据访问"],
                risk_level="medium" if reasons else "low",
            )
        if plan.needs_clarification:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=False,
                reasons=reasons + ["需要先澄清查询口径"],
                risk_level="blocked",
            )
        if not request.confirmed:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=True,
                reasons=reasons + ["执行需要显式确认"],
                risk_level="high" if sensitive else "medium",
            )
        if sensitive or unverified_join or blocking_quality or source_policy_approval:
            return PolicyDecision(
                allowed=False,
                requires_confirmation=True,
                reasons=reasons + ["高风险查询需要额外审批"],
                risk_level="high",
            )
        return PolicyDecision(
            allowed=True,
            requires_confirmation=False,
            reasons=reasons or ["只读 SQL 通过策略检查"],
            risk_level="low",
        )
