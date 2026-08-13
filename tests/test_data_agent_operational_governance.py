from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from data_agent.contracts import DataScope, QueryRequest
from data_agent.evaluation import PlanComparator, ResultComparator
from gateway.api_gateway.routers.data_agent import (
    _ensure_data_governance_admin,
    _evaluation_suite_payload,
    _failure_pattern_payload,
)
from infra.storage.data_agent_models import (
    DataAgentEvaluationSuiteRun,
    DataAgentFailurePattern,
)
from services.sql_assets import schema_fingerprint


def test_evaluation_comparators_support_release_gate_assertions() -> None:
    plan = PlanComparator().compare(
        {"metrics": [{"name": "销售额"}], "grain": ["day"]},
        {
            "metrics": [{"name": "销售额", "formula": "SUM(amount)"}],
            "grain": ["day", "region"],
        },
    )
    result = ResultComparator().compare(
        [{"day": "2026-08-12", "amount": 12.0}],
        [{"amount": 12, "day": "2026-08-12"}],
    )

    assert plan.matches is True
    assert result.exact is True


def test_data_agent_run_purpose_defaults_online_and_supports_evaluation() -> None:
    scope = DataScope(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        data_source_id="source-1",
    )

    assert QueryRequest(question="查询销售额", scope=scope).run_purpose == "online"
    assert (
        QueryRequest(question="回放销售额案例", scope=scope, run_purpose="evaluation").run_purpose
        == "evaluation"
    )


def test_governance_payloads_expose_resolution_and_release_gate_facts() -> None:
    now = datetime.now(UTC)
    failure = DataAgentFailurePattern(
        id="failure-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        data_source_id="source-1",
        pattern_key="pattern-1",
        schema_fingerprint="schema-v1",
        semantic_version="semantic-v1",
        failure_stage="preflight_blocked",
        error_codes=["estimated_rows_exceeded"],
        question_examples=["查询销售额"],
        candidate_sql_hash="sql-hash",
        failure_count=2,
        status="open",
        last_failure_at=now,
    )
    suite = DataAgentEvaluationSuiteRun(
        id="suite-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        data_source_id="source-1",
        name="发布门禁",
        execute=True,
        minimum_pass_rate=1.0,
        case_count=3,
        passed_count=2,
        failed_count=1,
        pass_rate=2 / 3,
        status="failed",
        started_at=now,
        completed_at=now,
    )

    failure_payload = _failure_pattern_payload(failure)
    suite_payload = _evaluation_suite_payload(suite)

    assert failure_payload["status"] == "open"
    assert failure_payload["error_codes"] == ["estimated_rows_exceeded"]
    assert suite_payload["status"] == "failed"
    assert suite_payload["passed_count"] == 2


def test_governance_mutations_require_admin() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _ensure_data_governance_admin(SimpleNamespace(is_superuser=False, role="member"))

    assert exc_info.value.status_code == 403
    _ensure_data_governance_admin(SimpleNamespace(is_superuser=False, role="admin"))


def test_schema_fingerprint_is_stable_for_golden_case_freezing() -> None:
    payload = {
        "tables": [
            {
                "name": "orders",
                "columns": [{"name": "amount", "type": "numeric"}],
            }
        ]
    }

    assert schema_fingerprint(payload) == schema_fingerprint(payload)


def test_frontend_exposes_operational_data_agent_governance() -> None:
    page = Path("frontend/src/pages/DatabasesPage.tsx").read_text(encoding="utf-8")
    api = Path("frontend/src/api/sqlAssets.ts").read_text(encoding="utf-8")
    schema_api = Path("frontend/src/api/databaseSchema.ts").read_text(encoding="utf-8")

    assert "企业问数质量与发布门禁" in page
    assert "待处置失败模式" in page
    assert "真实执行门禁" in page
    assert "apiGetDataAgentGovernanceOverview" in api
    assert "apiRunDataAgentEvaluationSuite" in api
    assert "apiCreateDataAgentEvaluationCase" in api
    assert "apiPublishDataAgentEvaluationCase" in api
    assert "schema_fingerprint" in schema_api
