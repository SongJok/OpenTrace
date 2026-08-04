from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from starlette.requests import Request

from gateway.api_gateway.routers.enterprise_reports import (
    EnterpriseReportPayload,
    create_enterprise_report,
)
from infra.errors import AppException
from infra.observability.turn_metering import add_llm_usage, reset_turn_tokens
from infra.storage.models import ResponseToolExecution, User
from services.enterprise_reports import (
    REPORT_TASK_TYPE,
    build_report_artifact,
    build_report_prompt,
    build_report_task_config,
)
from services.response_enterprise_runtime import (
    accumulate_response_attempt_usage,
    evaluate_response_admission,
    settle_response_usage,
)
from tenant.tenant_context import resolve_tenant_context
from tenant.usage_metering import UsageMeteringService


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": []})


def test_report_prompt_keeps_data_rag_chart_and_evidence_contract() -> None:
    config = build_report_task_config(
        report_type="management_brief",
        objective="复盘收入与现金流",
        data_sources=[{"id": "ds-1", "name": "经营库", "type": "postgresql"}],
        include_knowledge=False,
        audience="管理层",
    )

    prompt = build_report_prompt(config)

    assert config["include_knowledge"] is True
    assert "data_source_id=ds-1" in prompt
    assert "DataAgent" in prompt
    assert "RAG" in prompt
    assert "verification_report" in prompt
    assert "visualization_config" in prompt


@pytest.mark.asyncio
async def test_report_creation_rejects_data_source_outside_project() -> None:
    project = SimpleNamespace(id="project-1", data_source_ids=["ds-allowed"])
    db = AsyncMock()
    db.scalar.return_value = project

    with pytest.raises(AppException) as raised:
        await create_enterprise_report(
            EnterpriseReportPayload(
                report_type="data_insight",
                title="经营洞察",
                project_id="project-1",
                data_source_ids=["ds-other"],
            ),
            _request(),
            User(id="user-1", email="user@example.com"),
            db,
        )

    assert raised.value.http_status == 403
    assert raised.value.details == {"data_source_ids": ["ds-other"]}


@pytest.mark.asyncio
async def test_report_creation_persists_governed_task_config() -> None:
    project = SimpleNamespace(id="project-1", data_source_ids=["ds-1"])
    source = SimpleNamespace(id="ds-1", name="经营库", source_type="postgresql", status="active")
    db = AsyncMock()
    db.scalar.return_value = project
    db.add = Mock()

    with patch(
        "gateway.api_gateway.routers.enterprise_reports.get_accessible_data_source",
        new=AsyncMock(return_value=source),
    ):
        result = await create_enterprise_report(
            EnterpriseReportPayload(
                report_type="monthly_report",
                title="月度经营复盘",
                project_id="project-1",
                data_source_ids=["ds-1"],
            ),
            _request(),
            User(id="user-1", email="user@example.com"),
            db,
        )

    task = db.add.call_args.args[0]
    assert task.task_type == REPORT_TASK_TYPE
    assert task.task_config["data_source_ids"] == ["ds-1"]
    assert task.task_config["report_type"] == "monthly_report"
    assert result["report_type"] == "monthly_report"
    db.commit.assert_awaited_once()


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def all(self):
        return self._rows


@pytest.mark.asyncio
async def test_report_artifact_projects_only_durable_tool_ledger_evidence() -> None:
    data_execution = ResponseToolExecution(
        response_id="resp-1",
        call_id="call-data",
        idempotency_key="resp-1:data",
        tool_name="data",
        status="completed",
        result={
            "status": "success",
            "metadata": {
                "data_source_id": "ds-1",
                "sql": "SELECT month, revenue FROM metrics",
                "row_count": 1,
                "rows": [{"month": "2026-07", "revenue": 120}],
                "verification_report": {"status": "pass", "issues": []},
                "visualization_config": {
                    "chart_type": "bar",
                    "x_axis": "month",
                    "y_axis": ["revenue"],
                },
            },
        },
    )
    rag_execution = ResponseToolExecution(
        response_id="resp-1",
        call_id="call-rag",
        idempotency_key="resp-1:rag",
        tool_name="rag",
        status="completed",
        result={"metadata": {"citations": [{"title": "预算制度", "source_id": "doc-1"}]}},
    )
    db = AsyncMock()
    db.execute.return_value = _Scalars([data_execution, rag_execution])
    task = SimpleNamespace(
        title="经营简报",
        task_config={
            "report_type": "management_brief",
            "objective": "复盘经营",
            "audience": "管理层",
            "include_knowledge": True,
            "data_source_ids": ["ds-1"],
            "artifact_schema_version": 1,
        },
    )
    response = SimpleNamespace(id="resp-1")

    artifact = await build_report_artifact(
        db,
        task=task,
        response=response,
        output="# 结论\n收入增长。",
        response_status="completed",
    )

    assert artifact["status"] == "verified"
    assert artifact["verification"] == {
        "status": "pass",
        "data_verified": True,
        "readonly_sql": True,
        "data_source_coverage": {
            "expected": ["ds-1"],
            "covered": ["ds-1"],
            "missing": [],
        },
        "knowledge_verified": True,
        "chart_verified": True,
        "missing": [],
    }
    assert artifact["data_evidence"][0]["sql"].startswith("SELECT")
    assert artifact["knowledge_citations"][0]["source_id"] == "doc-1"
    assert artifact["charts"][0]["rows"][0]["revenue"] == 120

    task.task_config["data_source_ids"] = ["ds-1", "ds-2"]
    incomplete = await build_report_artifact(
        db,
        task=task,
        response=response,
        output="# 结论\n只覆盖一个数据源。",
        response_status="completed",
    )
    assert incomplete["status"] == "needs_review"
    assert incomplete["verification"]["data_source_coverage"]["missing"] == ["ds-2"]
    assert "data_source_coverage" in incomplete["verification"]["missing"]


@pytest.mark.asyncio
async def test_report_artifact_rejects_failed_ledger_entries_and_mutating_sql() -> None:
    execution = ResponseToolExecution(
        response_id="resp-unsafe",
        call_id="call-data",
        idempotency_key="resp-unsafe:data",
        tool_name="data",
        status="failed",
        result={
            "metadata": {
                "data_source_id": "ds-1",
                "sql": "SELECT revenue FROM metrics",
                "verification_report": {"status": "pass"},
                "visualization_config": {"chart_type": "bar"},
            }
        },
    )
    db = AsyncMock()
    db.execute.return_value = _Scalars([execution])
    task = SimpleNamespace(
        title="经营洞察",
        task_config={
            "report_type": "data_insight",
            "objective": "复盘经营",
            "audience": "管理层",
            "include_knowledge": False,
            "data_source_ids": ["ds-1"],
        },
    )

    failed = await build_report_artifact(
        db,
        task=task,
        response=SimpleNamespace(id="resp-unsafe"),
        output="失败账本不能成为证据。",
        response_status="completed",
    )
    assert failed["data_evidence"] == []
    assert failed["status"] == "needs_review"

    execution.status = "completed"
    execution.result["metadata"]["sql"] = "DELETE FROM metrics"
    unsafe = await build_report_artifact(
        db,
        task=task,
        response=SimpleNamespace(id="resp-unsafe"),
        output="写 SQL 不能成为已验证证据。",
        response_status="completed",
    )
    assert unsafe["data_evidence"][0]["readonly_sql"] is False
    assert unsafe["verification"]["readonly_sql"] is False
    assert "readonly_sql" in unsafe["verification"]["missing"]


@pytest.mark.asyncio
async def test_response_admission_persists_control_plane_and_quota_snapshot() -> None:
    decision = SimpleNamespace(allowed=True, violations=[], to_dict=lambda: {"allowed": True})
    reservation = SimpleNamespace(
        allowed=True,
        violations=[],
        to_dict=lambda: {"allowed": True, "turns_used": 1, "cost_used": 0.0},
    )
    control_plane = SimpleNamespace(
        evaluate_turn_async=AsyncMock(return_value=decision),
        consume_turn_quota_async=AsyncMock(return_value=reservation),
    )

    with patch(
        "services.response_enterprise_runtime.get_enterprise_control_plane",
        return_value=control_plane,
    ):
        snapshot = await evaluate_response_admission(
            query="分析本月收入",
            user_id="user-1",
            session_id="session-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            org_id="org-1",
        )

    assert snapshot["allowed"] is True
    assert snapshot["quota_reservation"]["allowed"] is True
    assert snapshot["version"] == "responses-enterprise-beta-v1"


@pytest.mark.asyncio
async def test_response_admission_fails_closed_when_pii_scan_is_unavailable() -> None:
    with patch("governance.pii_detector.detect_pii_signals", side_effect=RuntimeError("down")):
        with pytest.raises(AppException) as raised:
            await evaluate_response_admission(
                query="分析客户数据",
                user_id="user-1",
                session_id="session-1",
                tenant_id="tenant-1",
                workspace_id="workspace-1",
                org_id="org-1",
            )

    assert raised.value.http_status == 500
    assert raised.value.details == {"stage": "pii_detection"}


def test_response_settlement_accumulates_actual_tokens_and_billing() -> None:
    reset_turn_tokens()
    add_llm_usage(prompt_tokens=120, completion_tokens=30)
    usage = SimpleNamespace(to_dict=lambda: {"prompt_tokens": 120, "completion_tokens": 30})
    meter = SimpleNamespace(record_turn=Mock(return_value=usage))

    with patch("services.response_enterprise_runtime.get_usage_metering", return_value=meter):
        metadata = settle_response_usage(
            response_id="resp-1",
            response_metadata={"org_id": "org-1"},
            result_metadata={"model_call_count": 1},
            user_id="user-1",
            conversation_id="conversation-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            org_id="org-1",
            goal_id=None,
            capability_type="responses",
        )

    assert metadata["prompt_tokens"] == 120
    assert metadata["completion_tokens"] == 30
    assert metadata["billing_attribution"]["capability_type"] == "responses"
    assert metadata["enterprise_settlement"]["response_id"] == "resp-1"
    meter.record_turn.assert_called_once()


def test_response_attempt_usage_can_settle_without_counting_current_context_twice() -> None:
    reset_turn_tokens()
    add_llm_usage(prompt_tokens=40, completion_tokens=10)
    accumulated = accumulate_response_attempt_usage({})
    usage = SimpleNamespace(to_dict=lambda: {"prompt_tokens": 40, "completion_tokens": 10})
    meter = SimpleNamespace(record_turn=Mock(return_value=usage))

    with patch("services.response_enterprise_runtime.get_usage_metering", return_value=meter):
        metadata = settle_response_usage(
            response_id="resp-retry",
            response_metadata=accumulated,
            result_metadata=None,
            user_id="user-1",
            conversation_id="conversation-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            org_id="org-1",
            goal_id=None,
            capability_type="responses",
            include_current_attempt=False,
        )

    assert metadata["prompt_tokens"] == 40
    assert metadata["completion_tokens"] == 10
    meter.record_turn.assert_called_once_with(
        resolve_tenant_context(
            user_id="user-1",
            session_id="conversation-1",
            tenant_id="tenant-1",
            org_id="org-1",
            workspace_id="workspace-1",
            goal_id=None,
        ),
        session_id="conversation-1",
        goal_id="",
        capability_type="responses",
        prompt_tokens=40,
        completion_tokens=10,
        estimated_cost=metadata["turn_cost"],
    )

    add_llm_usage(prompt_tokens=400, completion_tokens=100)
    with patch("services.response_enterprise_runtime.get_usage_metering", return_value=meter):
        repeated = settle_response_usage(
            response_id="resp-retry",
            response_metadata=metadata,
            result_metadata=None,
            user_id="user-1",
            conversation_id="conversation-1",
            tenant_id="tenant-1",
            workspace_id="workspace-1",
            org_id="org-1",
            goal_id=None,
            capability_type="responses",
        )

    assert repeated["prompt_tokens"] == 40
    assert repeated["completion_tokens"] == 10
    meter.record_turn.assert_called_once()


def test_actual_zero_token_settlement_does_not_fabricate_default_usage() -> None:
    meter = UsageMeteringService()
    context = resolve_tenant_context(tenant_id="tenant-zero")

    with (
        patch("control_plane.control_plane.get_enterprise_control_plane") as control_plane,
        patch("tenant.usage_redis_store.record_usage_delta", return_value=None),
        patch("tenant.usage_redis_store.run_usage_coro"),
    ):
        usage = meter.record_turn(context, estimated_cost=0.0)

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.estimated_cost_usd == 0.0
    control_plane.return_value.record_turn_cost.assert_called_once()
