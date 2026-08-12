from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from data_agent.adapters.opentrace.answer import sanitize_answer_citations
from data_agent.adapters.opentrace.evidence import OpenTraceEvidenceProvider
from data_agent.adapters.opentrace.learning import OpenTraceLearningRepository
from data_agent.adapters.opentrace.source_resolution import OpenTraceSourceResolver
from data_agent.answering import AnswerEvidenceBuilder
from data_agent.compiler import CandidateRanker
from data_agent.contracts import (
    AnswerCitation,
    Authority,
    CandidateSQL,
    DataScope,
    DataSourceDecision,
    EvidenceBundle,
    EvidenceItem,
    EvidenceType,
    ExecutionResult,
    LearningRecord,
    LogicalQueryPlan,
    MetricSpec,
    PreflightReport,
    QueryRequest,
    QueryRun,
    ResultValidationReport,
    RunState,
    ValidationIssue,
    ValidationReport,
)
from data_agent.learning import ExecutionLearningEngine, plan_pattern_key, sql_structure_hash
from data_agent.semantics import LogicalPlanner
from data_agent.service import DataAgentService
from data_agent.source_resolution import SourceCatalogEntry, SourceSignal, TrustedSourceSelector
from gateway.api_gateway.routers.metrics import _metric_certification_missing_fields
from infra.storage.data_agent_models import DataAgentLearningPattern
from infra.storage.models import MetricDefinition


def _scope() -> DataScope:
    return DataScope(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        data_source_id="source-1",
    )


def _metric_evidence() -> EvidenceItem:
    return EvidenceItem(
        type=EvidenceType.METRIC,
        source_id="metric:paid-users",
        source_name="MetricDefinition",
        authority=Authority.GOVERNED,
        confidence=1.0,
        version="2",
        payload={
            "name": "付费用户数",
            "formula": "COUNT(DISTINCT orders.user_id)",
            "underlying_columns": ["orders.user_id"],
            "time_field": "orders.paid_at",
            "owner": "商业化数据团队",
        },
    )


def _evidence(*, semantic_version: str = "semantic-v1") -> EvidenceBundle:
    return EvidenceBundle(
        dialect="mysql",
        schema_fingerprint="schema-v1",
        semantic_version=semantic_version,
        table_columns={"orders": ["user_id", "paid_at", "status"]},
        items=[
            EvidenceItem(
                type=EvidenceType.SCHEMA,
                source_id="schema:orders",
                authority=Authority.LIVE_SYSTEM,
                confidence=1.0,
                payload={"table": "orders", "columns": ["user_id", "paid_at", "status"]},
            ),
            _metric_evidence(),
        ],
    )


def _plan() -> LogicalQueryPlan:
    return LogicalQueryPlan(
        question="昨天付费用户数",
        intent="aggregate",
        required_tables=["orders"],
        metrics=[
            MetricSpec(
                name="付费用户数",
                formula="COUNT(DISTINCT orders.user_id)",
                aggregation="count",
                underlying_columns=["orders.user_id"],
                time_field="orders.paid_at",
                source_evidence_id="metric:paid-users",
            )
        ],
        evidence_ids=["metric:paid-users"],
        confidence=0.96,
    )


def _completed_run(*, rows: list[dict] | None = None) -> tuple[QueryRun, CandidateSQL]:
    plan = _plan()
    candidate = CandidateSQL(
        sql="SELECT COUNT(DISTINCT orders.user_id) AS paid_users FROM orders LIMIT 100",
        source="semantic_compiler",
        validation=ValidationReport(
            status="warn",
            issues=[
                ValidationIssue(
                    code="limit_added",
                    message="已自动添加 LIMIT 100",
                    severity="info",
                )
            ],
        ),
    )
    result_rows = [{"paid_users": 12}] if rows is None else rows
    run = QueryRun(
        id="run-1",
        request=QueryRequest(question=plan.question, scope=_scope()),
        state=RunState.COMPLETED,
        evidence=_evidence(),
        logical_plan=plan,
        candidates=[candidate],
        selected_candidate_id=candidate.id,
        preflight=PreflightReport(status="pass", explain_rows=[{"rows": 10}]),
        result=ExecutionResult(
            rows=result_rows,
            returned_rows=len(result_rows),
            total_rows=len(result_rows),
        ),
        result_validation=ResultValidationReport(status="pass"),
    )
    run.answer_citations, run.answer_metadata = AnswerEvidenceBuilder().build(run, candidate)
    return run, candidate


def test_trusted_source_selector_prefers_certified_metric_evidence() -> None:
    selector = TrustedSourceSelector(minimum_score=0.2, ambiguity_delta=0.05)
    decision = selector.select(
        "查询付费用户数",
        [
            SourceCatalogEntry(
                data_source_id="source-a",
                name="交易数仓",
                source_type="mysql",
                schema_synced=True,
                signals=[
                    SourceSignal(
                        kind="metric",
                        source_id="metric:paid-users",
                        text="付费用户数 支付成功用户去重",
                        certified=True,
                    )
                ],
            ),
            SourceCatalogEntry(
                data_source_id="source-b",
                name="用户画像库",
                source_type="postgresql",
                schema_synced=True,
                signals=[
                    SourceSignal(
                        kind="schema",
                        source_id="schema:user",
                        text="用户基础信息",
                    )
                ],
            ),
        ],
    )

    assert decision.status == "selected"
    assert decision.selected_data_source_id == "source-a"
    assert "命中公司认证指标" in decision.candidates[0].reasons


def test_trusted_source_selector_clarifies_close_scores_and_blocks_policy() -> None:
    selector = TrustedSourceSelector(minimum_score=0.1, ambiguity_delta=0.08)
    entries = [
        SourceCatalogEntry(
            data_source_id=f"source-{suffix}",
            name=f"交易库{suffix}",
            source_type="mysql",
            schema_synced=True,
            signals=[
                SourceSignal(
                    kind="metric",
                    source_id=f"metric:{suffix}",
                    text="付费用户数",
                    certified=True,
                )
            ],
        )
        for suffix in ("a", "b")
    ]
    assert selector.select("付费用户数", entries).status == "needs_clarification"

    blocked = SourceCatalogEntry(
        data_source_id="source-blocked",
        name="受限库",
        source_type="mysql",
        signals=[
            SourceSignal(
                kind="semantic",
                source_id="policy:block",
                text="全局访问策略",
                blocked=True,
            )
        ],
    )
    assert selector.select("任意查询", [blocked]).status == "no_source"


@pytest.mark.asyncio
async def test_source_resolver_uses_only_explicit_candidates() -> None:
    class EmptyResult:
        @staticmethod
        def scalars():
            return SimpleNamespace(all=lambda: [])

    db = SimpleNamespace(
        scalar=AsyncMock(return_value=None),
        execute=AsyncMock(return_value=EmptyResult()),
    )

    decision = await OpenTraceSourceResolver(cast(AsyncSession, db)).resolve(
        question="查询订单",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        explicit_id="outside-source",
        candidate_ids=["outside-source"],
    )

    assert decision.status == "no_source"
    assert decision.selected_data_source_id is None
    db.execute.assert_awaited_once()


def test_query_request_rejects_mismatched_source_decision() -> None:
    decision = DataSourceDecision(
        status="selected",
        question="查询订单",
        selected_data_source_id="source-2",
        selected_data_source_name="其他库",
    )
    with pytest.raises(ValidationError):
        QueryRequest(question="查询订单", scope=_scope(), source_decision=decision)


def test_answer_citation_whitelist_removes_unknown_labels_and_requires_result() -> None:
    citations = [
        AnswerCitation(
            label="R1",
            evidence_id="execution-result:run-1",
            evidence_type="execution_result",
            title="本次执行结果",
            authority="live_system",
        ),
        AnswerCitation(
            label="E1",
            evidence_id="metric:paid-users",
            evidence_type="metric",
            title="付费用户数",
            authority="governed",
        ),
    ]

    answer = sanitize_answer_citations("付费用户为 12 [R9] [SQL1]，采用认证口径 [E1]。", citations)

    assert "[R9]" not in answer
    assert "[SQL1]" not in answer
    assert "[E1]" in answer
    assert "[R1]" in answer


def test_answer_evidence_builder_binds_result_and_governed_metric() -> None:
    run, candidate = _completed_run()

    citations, metadata = AnswerEvidenceBuilder().build(run, candidate)

    assert [item.label for item in citations[:2]] == ["R1", "E1"]
    assert citations[1].evidence_id == "metric:paid-users"
    assert metadata["metrics"][0]["owner"] is None
    assert metadata["result_validation"]["status"] == "pass"
    assert metadata["evidence_coverage"] == 1.0


def test_semantic_version_changes_when_business_rule_payload_changes() -> None:
    original = EvidenceItem(
        type=EvidenceType.BUSINESS_RULE,
        source_id="rule:paid-order",
        authority=Authority.GOVERNED,
        version="1",
        payload={"required_filters": ["status = 'paid'"]},
    )
    changed = original.model_copy(
        update={"payload": {"required_filters": ["status IN ('paid', 'settled')"]}}
    )

    assert OpenTraceEvidenceProvider._semantic_version(
        [original]
    ) != OpenTraceEvidenceProvider._semantic_version([changed])


def test_learning_requires_non_empty_fully_verified_execution() -> None:
    engine = ExecutionLearningEngine(minimum_confidence=0.85)
    run, candidate = _completed_run()

    eligible = engine.evaluate(run, candidate)
    assert eligible.status == "observed"
    assert eligible.reusable is False

    empty_run, empty_candidate = _completed_run(rows=[])
    empty = engine.evaluate(empty_run, empty_candidate)
    assert empty.status == "ineligible"
    assert any("空结果" in reason for reason in empty.reasons)

    run.result_validation = ResultValidationReport(
        status="warn",
        issues=[ValidationIssue(code="anomaly", message="异常", severity="warning")],
    )
    warned = engine.evaluate(run, candidate)
    assert warned.status == "ineligible"
    assert any("未完全通过" in reason for reason in warned.reasons)


def test_only_trusted_execution_memory_changes_candidate_ranking() -> None:
    plan = _plan()
    sql = "SELECT COUNT(DISTINCT orders.user_id) AS paid_users FROM orders LIMIT 100"
    structure = sql_structure_hash(sql, dialect="mysql")
    evidence = _evidence()
    evidence.items.extend(
        [
            EvidenceItem(
                type=EvidenceType.EXECUTION_MEMORY,
                source_id="learning-pattern:observed",
                authority=Authority.CONTEXTUAL,
                payload={
                    "pattern_key": plan_pattern_key(plan),
                    "sql_structure_hash": structure,
                    "status": "observed",
                },
            ),
            EvidenceItem(
                type=EvidenceType.EXECUTION_MEMORY,
                source_id="learning-pattern:trusted",
                authority=Authority.VERIFIED,
                payload={
                    "pattern_key": plan_pattern_key(plan),
                    "sql_structure_hash": structure,
                    "status": "trusted",
                },
            ),
        ]
    )
    candidate = CandidateSQL(sql=sql, validation=ValidationReport(status="pass"))

    ranked = CandidateRanker().rank([candidate], plan, evidence)

    assert ranked[0].supporting_memory_ids == ["learning-pattern:trusted"]
    assert ranked[0].score >= plan.confidence * 10 + 2


@pytest.mark.asyncio
async def test_learning_repository_promotes_then_rejects_pattern() -> None:
    run, candidate = _completed_run()
    run.id = "run-new"
    logical_plan = run.logical_plan
    assert logical_plan is not None
    pattern = DataAgentLearningPattern(
        id="pattern-1",
        user_id=run.request.scope.user_id,
        tenant_id=run.request.scope.tenant_id,
        workspace_id=run.request.scope.workspace_id,
        scope_key="__global__",
        data_source_id=run.request.scope.data_source_id,
        pattern_key=plan_pattern_key(logical_plan),
        question_examples=[run.request.question],
        logical_plan_json=logical_plan.model_dump(mode="json"),
        selected_sql=candidate.sql,
        sql_structure_hash=sql_structure_hash(candidate.sql, dialect="mysql"),
        schema_fingerprint="schema-v1",
        semantic_version="semantic-v1",
        confidence=0.95,
        observation_count=1,
        success_count=1,
        failure_count=0,
        status="observed",
        last_run_id="run-old",
    )
    db = SimpleNamespace(scalar=AsyncMock(return_value=pattern), flush=AsyncMock())
    repository = OpenTraceLearningRepository(cast(AsyncSession, db))

    promoted = await repository.record_success(
        run,
        candidate,
        LearningRecord(
            pattern_key=pattern.pattern_key,
            status="observed",
            confidence=0.95,
            observation_count=1,
            success_count=1,
        ),
    )
    assert promoted.status == "trusted"
    assert promoted.success_count == 2

    rejected = await repository.record_feedback(
        run,
        verdict="incorrect",
        candidate_id=candidate.id,
        corrected_sql="SELECT 1",
    )
    assert rejected is not None and rejected.status == "rejected"
    assert rejected.failure_count == 1


@pytest.mark.asyncio
async def test_semantic_version_drift_blocks_execution_before_database_access() -> None:
    class Provider:
        def __init__(self) -> None:
            self.calls = 0

        async def collect(self, scope, question, research_plan):
            self.calls += 1
            return _evidence(semantic_version=f"semantic-v{self.calls}")

    class Planner:
        def plan(self, request, evidence):
            return _plan()

    class Generator:
        async def generate(self, request, plan, evidence):
            return [
                CandidateSQL(
                    sql="SELECT COUNT(DISTINCT orders.user_id) FROM orders LIMIT 100",
                    source="semantic_compiler",
                )
            ]

    executor = SimpleNamespace(execute=AsyncMock())
    service = DataAgentService(
        evidence_provider=Provider(),
        logical_planner=cast(LogicalPlanner, Planner()),
        sql_generator=Generator(),
        query_executor=executor,
    )
    run = await service.create(
        QueryRequest(question="昨天付费用户数", scope=_scope(), minimum_confidence=0.5)
    )

    blocked = await service.execute(run.id, _scope(), confirmed=True)

    assert blocked.state == RunState.BLOCKED
    assert any(item.get("reason") == "semantic_version_changed" for item in blocked.trace)
    executor.execute.assert_not_awaited()


def test_metric_certification_requires_complete_business_contract() -> None:
    metric = SimpleNamespace(
        formula="COUNT(DISTINCT orders.user_id)",
        business_definition="支付成功用户去重数量",
        underlying_columns=["orders.user_id"],
        agg_function="COUNT_DISTINCT",
        owner="商业化数据团队",
        business_domain="交易",
        grain="day",
        evidence_refs=["需求单-1024", "经营日报"],
        time_field=None,
    )

    typed_metric = cast(MetricDefinition, metric)
    assert _metric_certification_missing_fields(typed_metric) == ["time_field"]
    metric.time_field = "orders.paid_at"
    assert _metric_certification_missing_fields(typed_metric) == []


def test_frontend_exposes_source_evidence_and_learning_state() -> None:
    source = Path("frontend/src/pages/DatabasesPage.tsx").read_text(encoding="utf-8")

    assert "可信数据源决策" in source
    assert "答案证据链" in source
    assert "受控执行学习" in source
    assert "supporting_memory_ids" in source
