from __future__ import annotations

import pytest

from data_agent.compiler import SQLGuard
from data_agent.contracts import (
    Authority,
    DataScope,
    EvidenceBundle,
    EvidenceItem,
    EvidenceType,
    ExecutionMode,
    ExecutionResult,
    QueryRequest,
    RunState,
    deterministic_run_id,
)
from data_agent.policy import ExecutionPolicy
from data_agent.research import ResearchPlanner
from data_agent.service import DataAgentService


def _scope() -> DataScope:
    return DataScope(user_id="u1", tenant_id="t1", workspace_id="w1", data_source_id="ds1")


def _evidence(fingerprint: str = "v1") -> EvidenceBundle:
    return EvidenceBundle(
        schema_fingerprint=fingerprint,
        dialect="mysql",
        table_columns={"users": ["id", "name"]},
        items=[
            EvidenceItem(
                type=EvidenceType.SCHEMA,
                source_id="schema-users",
                source_name="live-schema",
                authority=Authority.LIVE_SYSTEM,
                confidence=1.0,
                payload={"table": "users", "columns": ["id", "name"]},
            )
        ],
    )


def _join_evidence(verified: bool) -> EvidenceBundle:
    evidence = _evidence()
    evidence.table_columns["orders"] = ["id", "user_id", "amount"]
    evidence.items.append(
        EvidenceItem(
            type=EvidenceType.RELATIONSHIP,
            source_id="relationship-users-orders",
            payload={
                "left_table": "users",
                "left_column": "id",
                "right_table": "orders",
                "right_column": "user_id",
                "verified": verified,
            },
        )
    )
    return evidence


def test_research_planner_selects_process_and_analysis_sources() -> None:
    plan = ResearchPlanner().plan("本月支付漏斗和退款率为什么下降")
    selected = {step.source for step in plan.steps}
    assert EvidenceType.SCHEMA in selected
    assert EvidenceType.METRIC in selected
    assert EvidenceType.BUSINESS_PROCESS in selected
    assert EvidenceType.SKILL in selected
    assert EvidenceType.DATA_QUALITY in selected
    assert EvidenceType.SOURCE_POLICY in selected


def test_sql_guard_rejects_write_and_foreign_table() -> None:
    request = QueryRequest(question="查询用户", scope=_scope())
    from data_agent.contracts import LogicalQueryPlan

    plan = LogicalQueryPlan(question=request.question, required_tables=["users"])
    guard = SQLGuard()
    write_report = guard.validate(
        "DELETE FROM users", request=request, plan=plan, evidence=_evidence()
    )
    foreign_report = guard.validate(
        "SELECT id FROM payments", request=request, plan=plan, evidence=_evidence()
    )
    assert {issue.code for issue in write_report.errors} >= {"read_only", "write_statement"}
    assert any(issue.code == "table_scope" for issue in foreign_report.errors)


def test_sql_guard_rejects_unqualified_unknown_column() -> None:
    request = QueryRequest(question="查询用户", scope=_scope())
    from data_agent.contracts import LogicalQueryPlan

    report = SQLGuard().validate(
        "SELECT secret_value FROM users",
        request=request,
        plan=LogicalQueryPlan(question=request.question, required_tables=["users"]),
        evidence=_evidence(),
    )
    assert any(issue.code == "column_scope" for issue in report.errors)


def test_sql_guard_expands_projection_star_for_schema_qualified_sensitive_table() -> None:
    from data_agent.contracts import LogicalQueryPlan

    request = QueryRequest(
        question="导出用户",
        scope=_scope(),
        mode=ExecutionMode.EXECUTE_AND_ANSWER,
        confirmed=True,
    )
    evidence = EvidenceBundle(
        dialect="postgres",
        table_columns={"public.users": ["id", "email"]},
        items=[
            EvidenceItem(
                type=EvidenceType.COLUMN_PROFILE,
                source_id="profile-public-users-email",
                sensitive=True,
                payload={"table": "public.users", "column": "email", "sensitive": True},
            )
        ],
    )
    plan = LogicalQueryPlan(question=request.question, required_tables=["public.users"])

    report = SQLGuard().validate(
        "SELECT u.* FROM public.users AS u",
        request=request,
        plan=plan,
        evidence=evidence,
    )
    decision = ExecutionPolicy().decide(request, plan, report, evidence)

    assert any(issue.code == "select_star" for issue in report.issues)
    assert any(issue.code == "sensitive_column" for issue in report.issues)
    assert decision.allowed is False
    assert decision.risk_level == "high"


def test_sql_guard_resolves_schema_qualified_sensitive_column_through_alias() -> None:
    from data_agent.contracts import LogicalQueryPlan

    request = QueryRequest(question="查询用户邮箱", scope=_scope())
    evidence = EvidenceBundle(
        dialect="postgres",
        table_columns={"public.users": ["id", "email"]},
        items=[
            EvidenceItem(
                type=EvidenceType.SCHEMA,
                source_id="schema-public-users-email",
                payload={"table": "public.users", "column": "email", "sensitive": True},
            )
        ],
    )
    report = SQLGuard().validate(
        "SELECT u.email FROM public.users AS u",
        request=request,
        plan=LogicalQueryPlan(question=request.question, required_tables=["public.users"]),
        evidence=evidence,
    )

    assert any(issue.code == "sensitive_column" for issue in report.issues)


def test_sql_guard_does_not_treat_count_star_as_sensitive_projection() -> None:
    from data_agent.contracts import LogicalQueryPlan

    request = QueryRequest(question="统计用户数", scope=_scope())
    evidence = EvidenceBundle(
        dialect="postgres",
        table_columns={"public.users": ["id", "email"]},
        items=[
            EvidenceItem(
                type=EvidenceType.COLUMN_PROFILE,
                source_id="profile-public-users-email",
                sensitive=True,
                payload={"table": "public.users", "column": "email", "sensitive": True},
            )
        ],
    )
    report = SQLGuard().validate(
        "SELECT COUNT(*) AS user_count FROM public.users",
        request=request,
        plan=LogicalQueryPlan(question=request.question, required_tables=["public.users"]),
        evidence=evidence,
    )

    codes = {issue.code for issue in report.issues}
    assert "select_star" not in codes
    assert "sensitive_column" not in codes


def test_sql_guard_blocks_unverified_join_even_without_catalog_relationships() -> None:
    request = QueryRequest(question="查询用户订单", scope=_scope())
    from data_agent.contracts import LogicalQueryPlan

    report = SQLGuard().validate(
        "SELECT u.id, o.amount FROM users u JOIN orders o ON u.id = o.user_id",
        request=request,
        plan=LogicalQueryPlan(question=request.question, required_tables=["users", "orders"]),
        evidence=_join_evidence(verified=False),
    )
    assert any(issue.code == "unverified_join" for issue in report.issues)


def test_sql_guard_resolves_aliases_for_verified_join() -> None:
    request = QueryRequest(question="查询用户订单", scope=_scope())
    from data_agent.contracts import LogicalQueryPlan

    report = SQLGuard().validate(
        "SELECT u.id, o.amount FROM users u JOIN orders o ON u.id = o.user_id",
        request=request,
        plan=LogicalQueryPlan(question=request.question, required_tables=["users", "orders"]),
        evidence=_join_evidence(verified=True),
    )
    assert not any(issue.code == "unverified_join" for issue in report.issues)


def test_source_policy_can_block_execution() -> None:
    request = QueryRequest(
        question="查询用户",
        scope=_scope(),
        mode=ExecutionMode.EXECUTE_AND_ANSWER,
        confirmed=True,
    )
    from data_agent.contracts import LogicalQueryPlan

    evidence = _evidence()
    evidence.items.append(
        EvidenceItem(
            type=EvidenceType.SOURCE_POLICY,
            source_id="policy-users",
            payload={"deny_execution": True},
        )
    )
    decision = ExecutionPolicy().decide(
        request,
        LogicalQueryPlan(question=request.question),
        SQLGuard().validate(
            "SELECT id FROM users",
            request=request,
            plan=LogicalQueryPlan(question=request.question),
            evidence=evidence,
        ),
        evidence,
    )
    assert decision.allowed is False
    assert decision.risk_level == "blocked"


def test_idempotency_run_id_is_stable_inside_scope() -> None:
    request = QueryRequest(
        question="查询用户",
        scope=_scope(),
        idempotency_key="retry-1",
    )
    assert deterministic_run_id(request) == deterministic_run_id(request)
    assert deterministic_run_id(
        request.model_copy(
            update={"scope": _scope().model_copy(update={"workspace_id": "workspace-2"})}
        )
    ) != deterministic_run_id(request)


def test_sql_guard_adds_limit_and_marks_completeness() -> None:
    request = QueryRequest(question="查询用户", scope=_scope(), max_rows=20)
    from data_agent.contracts import LogicalQueryPlan

    report = SQLGuard().validate(
        "SELECT id, name FROM users",
        request=request,
        plan=LogicalQueryPlan(question=request.question, required_tables=["users"]),
        evidence=_evidence(),
    )
    assert report.status == "warn"
    assert "LIMIT 20" in report.normalized_sql
    assert report.completeness["truncation_must_be_reported"] is True


class _Provider:
    def __init__(self) -> None:
        self.fingerprint = "v1"
        self.sensitive = False

    async def collect(self, scope, question, plan):
        evidence = _evidence(self.fingerprint)
        if self.sensitive:
            evidence.items.append(
                EvidenceItem(
                    type=EvidenceType.COLUMN_PROFILE,
                    source_id="column-users-name",
                    sensitive=True,
                    payload={"table": "users", "column": "name", "sensitive": True},
                )
            )
        return evidence


class _Generator:
    async def generate(self, request, plan, evidence):
        return ["SELECT id, name FROM users"]


class _NonSensitiveGenerator:
    async def generate(self, request, plan, evidence):
        return ["SELECT id FROM users"]


class _Executor:
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, scope, sql, *, max_rows, evidence):
        self.calls += 1
        return ExecutionResult(
            rows=[{"id": 1, "name": "张三"}], returned_rows=1, columns=["id", "name"]
        )


@pytest.mark.asyncio
async def test_service_requires_confirmation_and_executes_after_confirmation() -> None:
    provider = _Provider()
    executor = _Executor()
    service = DataAgentService(
        evidence_provider=provider,
        sql_generator=_Generator(),
        query_executor=executor,
    )
    request = QueryRequest(
        question="查询用户",
        scope=_scope(),
        mode=ExecutionMode.EXECUTE_AND_ANSWER,
        confirmed=False,
    )
    run = await service.create(request)
    assert run.state == RunState.READY
    assert run.policy is not None and run.policy.requires_confirmation is True

    completed = await service.execute(run.id, _scope(), confirmed=True)
    assert completed.state == RunState.COMPLETED
    assert completed.result is not None and completed.result.returned_rows == 1
    assert completed.answer and "1" in completed.answer
    repeated = await service.execute(run.id, _scope(), confirmed=True)
    assert repeated.state == RunState.COMPLETED
    assert executor.calls == 1


@pytest.mark.asyncio
async def test_service_reuses_idempotent_run() -> None:
    provider = _Provider()
    service = DataAgentService(
        evidence_provider=provider,
        sql_generator=_Generator(),
        query_executor=_Executor(),
    )
    request = QueryRequest(
        question="查询用户",
        scope=_scope(),
        idempotency_key="retry-1",
    )
    first = await service.create(request)
    second = await service.create(request)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_service_blocks_execution_when_schema_changes() -> None:
    provider = _Provider()
    service = DataAgentService(
        evidence_provider=provider,
        sql_generator=_Generator(),
        query_executor=_Executor(),
    )
    run = await service.create(
        QueryRequest(question="查询用户", scope=_scope(), mode=ExecutionMode.SQL_ONLY)
    )
    provider.fingerprint = "v2"
    blocked = await service.execute(run.id, _scope(), confirmed=True)
    assert blocked.state == RunState.BLOCKED
    assert any("Schema 已变化" in warning for warning in blocked.warnings)


@pytest.mark.asyncio
async def test_service_rechecks_latest_sensitive_evidence_before_execution() -> None:
    provider = _Provider()
    service = DataAgentService(
        evidence_provider=provider,
        sql_generator=_Generator(),
        query_executor=_Executor(),
    )
    run = await service.create(
        QueryRequest(question="查询用户", scope=_scope(), mode=ExecutionMode.SQL_ONLY)
    )
    provider.sensitive = True
    blocked = await service.execute(run.id, _scope(), confirmed=True)
    assert blocked.state == RunState.BLOCKED
    assert any("高风险查询需要额外审批" in warning for warning in blocked.warnings)


@pytest.mark.asyncio
async def test_unreferenced_sensitive_column_does_not_block_safe_query() -> None:
    provider = _Provider()
    provider.sensitive = True
    executor = _Executor()
    service = DataAgentService(
        evidence_provider=provider,
        sql_generator=_NonSensitiveGenerator(),
        query_executor=executor,
    )
    run = await service.create(
        QueryRequest(question="查询用户编号", scope=_scope(), mode=ExecutionMode.SQL_ONLY)
    )
    completed = await service.execute(run.id, _scope(), confirmed=True)

    assert completed.state == RunState.COMPLETED
    assert executor.calls == 1
