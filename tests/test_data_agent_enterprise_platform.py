from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_agent.compiler import SQLGuard
from data_agent.contracts import (
    Authority,
    CandidateSQL,
    DataScope,
    EvidenceBundle,
    EvidenceItem,
    EvidenceType,
    ExecutionMode,
    ExecutionResult,
    LogicalQueryPlan,
    MetricSpec,
    PreflightReport,
    QueryRequest,
    RunState,
    ValidationIssue,
)
from data_agent.profiling import _column_profile
from data_agent.research import ResearchPlanner
from data_agent.result_validation import ResultValidator
from data_agent.semantic_compiler import DeterministicSQLCompiler
from data_agent.semantics import LogicalPlanner
from data_agent.service import DataAgentService


def _scope() -> DataScope:
    return DataScope(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        data_source_id="source-1",
    )


def _metric_item(
    *,
    source_id: str,
    version: int,
    valid_from: datetime,
    valid_to: datetime | None,
) -> EvidenceItem:
    return EvidenceItem(
        type=EvidenceType.METRIC,
        source_id=source_id,
        authority=Authority.GOVERNED,
        confidence=1.0,
        version=str(version),
        valid_from=valid_from,
        valid_to=valid_to,
        payload={
            "name": "付费用户数",
            "aliases": ["付费用户"],
            "formula": "COUNT(DISTINCT orders.user_id)",
            "aggregation": "count",
            "underlying_columns": ["orders.user_id"],
            "required_filters": ["orders.status = 'paid'"],
            "time_field": "orders.paid_at",
            "grain": "day",
            "version": version,
            "owner": "商业化数据团队",
        },
    )


def _governed_evidence() -> EvidenceBundle:
    return EvidenceBundle(
        dialect="mysql",
        schema_fingerprint="schema-v1",
        table_columns={
            "orders": ["id", "user_id", "status", "paid_at", "channel_id", "is_test"],
            "channels": ["id", "name"],
        },
        items=[
            EvidenceItem(
                type=EvidenceType.SCHEMA,
                source_id="schema-orders",
                authority=Authority.LIVE_SYSTEM,
                confidence=1.0,
                payload={"table": "orders", "columns": ["user_id", "paid_at"]},
            ),
            _metric_item(
                source_id="metric-v1",
                version=1,
                valid_from=datetime(2025, 1, 1, tzinfo=UTC),
                valid_to=datetime(2026, 6, 1, tzinfo=UTC),
            ),
            _metric_item(
                source_id="metric-v2",
                version=2,
                valid_from=datetime(2026, 6, 1, tzinfo=UTC),
                valid_to=None,
            ),
            EvidenceItem(
                type=EvidenceType.COLUMN_PROFILE,
                source_id="column-channel",
                authority=Authority.GOVERNED,
                confidence=1.0,
                payload={
                    "table": "channels",
                    "column": "name",
                    "business_name": "渠道",
                    "aliases": ["业务线"],
                    "is_dimension": True,
                },
            ),
            EvidenceItem(
                type=EvidenceType.RELATIONSHIP,
                source_id="join-orders-channels",
                authority=Authority.GOVERNED,
                confidence=1.0,
                payload={
                    "left_table": "orders",
                    "left_column": "channel_id",
                    "right_table": "channels",
                    "right_column": "id",
                    "join_type": "LEFT",
                    "verified": True,
                },
            ),
            EvidenceItem(
                type=EvidenceType.BUSINESS_RULE,
                source_id="rule-test-account",
                authority=Authority.GOVERNED,
                confidence=1.0,
                payload={
                    "asset_key": "paid_user_excludes_test",
                    "title": "付费用户排除测试账号",
                    "metrics": ["付费用户数"],
                    "required_filters": ["orders.is_test = false"],
                },
            ),
        ],
    )


def test_planner_selects_historical_metric_version_and_absolute_time() -> None:
    request = QueryRequest(
        question="查询2025年7月各业务线付费用户数",
        scope=_scope(),
        as_of=datetime(2026, 8, 11, tzinfo=UTC),
        minimum_confidence=0.5,
    )
    plan = LogicalPlanner().plan(request, _governed_evidence())

    assert plan.needs_clarification is False
    assert plan.metrics[0].version == 1
    assert plan.metrics[0].owner == "商业化数据团队"
    assert plan.time_window["start"].startswith("2025-07-01")
    assert plan.time_window["end"].startswith("2025-08-01")
    assert plan.dimensions[0].column == "name"
    assert "orders.is_test = false" in plan.metrics[0].required_filters
    assert "rule-test-account" in plan.evidence_ids


def test_metric_research_always_collects_governed_business_rules() -> None:
    selected = {step.source for step in ResearchPlanner().plan("查询付费用户数").steps}

    assert EvidenceType.METRIC in selected
    assert EvidenceType.BUSINESS_RULE in selected


def test_deterministic_compiler_uses_metric_contract_time_and_verified_join() -> None:
    request = QueryRequest(
        question="查询2025年7月各业务线付费用户数",
        scope=_scope(),
        as_of=datetime(2026, 8, 11, tzinfo=UTC),
        minimum_confidence=0.5,
    )
    evidence = _governed_evidence()
    plan = LogicalPlanner().plan(request, evidence)
    candidate = DeterministicSQLCompiler().compile(request, plan, evidence)[0]
    normalized = " ".join(candidate.sql.lower().split())

    assert candidate.source == "semantic_compiler"
    assert "count(distinct orders.user_id)" in normalized
    assert "orders.status = 'paid'" in normalized
    assert "orders.is_test = false" in normalized
    assert "left join channels" in normalized
    assert "2025-07-01" in normalized and "2025-08-01" in normalized
    assert "2025-07-01 00:00:00" in normalized
    assert "+08:00" not in normalized
    report = SQLGuard().validate(candidate.sql, request=request, plan=plan, evidence=evidence)
    assert not report.errors


def test_sql_guard_rejects_wrong_aggregation_and_time_boundary() -> None:
    request = QueryRequest(question="查询2025年7月付费用户数", scope=_scope())
    plan = LogicalQueryPlan(
        question=request.question,
        required_tables=["orders"],
        metrics=[
            MetricSpec(
                name="付费用户数",
                formula="COUNT(DISTINCT orders.user_id)",
                aggregation="count",
                underlying_columns=["orders.user_id"],
                time_field="orders.paid_at",
            )
        ],
        time_window={
            "start": "2025-07-01T00:00:00+08:00",
            "end": "2025-08-01T00:00:00+08:00",
        },
    )
    evidence = _governed_evidence()
    report = SQLGuard().validate(
        "SELECT SUM(orders.user_id) FROM orders "
        "WHERE orders.paid_at >= '2025-07-02' AND orders.paid_at < '2025-08-01'",
        request=request,
        plan=plan,
        evidence=evidence,
    )
    codes = {issue.code for issue in report.errors}
    assert "metric_aggregation_mismatch" in codes
    assert "metric_distinct_missing" in codes
    assert "time_start_missing" in codes


def test_profile_masks_sensitive_values_and_infers_enum() -> None:
    public = _column_profile("status", [1, 1, 2, None], sensitive=False)
    sensitive = _column_profile("phone", ["13800000000", "13900000000"], sensitive=True)

    assert public["semantic_type"] == "enum"
    assert public["enum_candidate"] is True
    assert public["top_values"]
    assert sensitive["sample_values"] == []
    assert sensitive["top_values"] == []


def test_profile_and_execution_memory_use_full_user_scope() -> None:
    evidence_code = Path("data_agent/adapters/opentrace/evidence.py").read_text(encoding="utf-8")
    profiling_code = Path("data_agent/profiling.py").read_text(encoding="utf-8")
    router_code = Path("gateway/api_gateway/routers/data_agent.py").read_text(encoding="utf-8")
    profile_route = router_code.split("async def list_data_profiles", 1)[1].split(
        "@router.post", 1
    )[0]

    assert "DataAgentProfile.user_id == scope.user_id" in evidence_code
    assert "DataAgentRunRecord.user_id == scope.user_id" in evidence_code
    assert "DataAgentProfile.user_id == user_id" in profiling_code
    assert 'data_source_id, "query"' in profile_route


def test_result_validator_flags_truncation_and_execution_memory_anomaly() -> None:
    evidence = EvidenceBundle(
        items=[
            EvidenceItem(
                type=EvidenceType.EXECUTION_MEMORY,
                source_id="run-1",
                payload={"numeric_result_summary": {"paid_users": {"avg": 100000}}},
            )
        ]
    )
    report = ResultValidator().validate(
        LogicalQueryPlan(question="昨天付费用户", metrics=[MetricSpec(name="付费用户")]),
        ExecutionResult(rows=[{"paid_users": 8}], returned_rows=1, truncated=True),
        evidence,
    )
    codes = {issue.code for issue in report.issues}
    assert report.status == "warn"
    assert "result_truncated" in codes
    assert "historical_baseline_anomaly" in codes


class _Provider:
    async def collect(self, scope, question, research_plan):
        return EvidenceBundle(
            schema_fingerprint="v1",
            table_columns={"orders": ["id"]},
            items=[
                EvidenceItem(
                    type=EvidenceType.SCHEMA,
                    source_id="orders",
                    authority=Authority.LIVE_SYSTEM,
                    confidence=1.0,
                    payload={"table": "orders", "columns": ["id"]},
                )
            ],
        )


class _Generator:
    async def generate(self, request, plan, evidence):
        return [CandidateSQL(sql="SELECT id FROM orders")]


class _BlockingExecutor:
    def __init__(self) -> None:
        self.executed = False

    async def preflight(self, scope, sql, *, evidence):
        return PreflightReport(
            status="fail",
            issues=[ValidationIssue(code="cost", message="扫描量过大")],
        )

    async def execute(self, scope, sql, *, max_rows, evidence):
        self.executed = True
        return ExecutionResult()


@pytest.mark.asyncio
async def test_preflight_failure_blocks_execution() -> None:
    executor = _BlockingExecutor()
    service = DataAgentService(
        evidence_provider=_Provider(),
        sql_generator=_Generator(),
        query_executor=executor,
    )
    run = await service.create(
        QueryRequest(
            question="查询订单",
            scope=_scope(),
            mode=ExecutionMode.SQL_ONLY,
            minimum_confidence=0.5,
        )
    )
    blocked = await service.execute(run.id, _scope(), confirmed=True)

    assert blocked.state == RunState.BLOCKED
    assert executor.executed is False
    assert blocked.preflight is not None and blocked.preflight.errors
