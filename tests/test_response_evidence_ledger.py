from data_agent.contracts import (
    CandidateSQL,
    DataScope,
    EvidenceBundle,
    ExecutionResult,
    QueryRequest,
    QueryRun,
)
from data_agent.learning import bind_result_snapshot
from kernel.agent_loop.contracts import (
    DataIntentStage,
    EvidenceRequirement,
    InformationSource,
    IntentPlan,
)
from kernel.agent_loop.data_tools import governed_sql_execution_spec
from kernel.agent_loop.evidence import ResponseEvidenceLedger


def _intent(*requirements: EvidenceRequirement, stage: DataIntentStage) -> IntentPlan:
    return IntentPlan(
        goal="查询复购率",
        information_sources=(InformationSource.DATA,),
        evidence_requirements=requirements,
        data_stage=stage,
    )


def test_evidence_gate_blocks_unverified_business_number() -> None:
    ledger = ResponseEvidenceLedger.from_context(
        _intent(EvidenceRequirement.EXECUTED_RESULT, stage=DataIntentStage.EXECUTE_AND_VERIFY),
        context_manifest={},
        memory_ids=[],
    )

    content, gate = ledger.govern_answer("本月复购率是 42%。")

    assert gate["status"] == "blocked"
    assert gate["answer_replaced"] is True
    assert "不能给出或确认业务数字" in content


def test_evidence_gate_blocks_missing_company_skill_instead_of_using_model_knowledge() -> None:
    ledger = ResponseEvidenceLedger.from_context(
        IntentPlan(
            goal="解释企业字段",
            information_sources=(InformationSource.COMPANY_SKILL,),
            evidence_requirements=(EvidenceRequirement.COMPANY_SKILL_CONTEXT,),
        ),
        context_manifest={},
        memory_ids=[],
    )

    content, gate = ledger.govern_answer("这个字段表示支付成功。")

    assert gate["status"] == "blocked"
    assert gate["answer_replaced"] is True
    assert "不会用模型常识伪造" in content


def test_tool_failure_ledger_does_not_persist_raw_exception_text() -> None:
    ledger = ResponseEvidenceLedger(IntentPlan(goal="检索企业知识"))

    ledger.observe_tool(
        "rag",
        {"status": "failed", "error": "postgresql://user:super-secret@db/internal"},
    )

    assert ledger.failures == [
        {
            "source": "rag",
            "status": "failed",
            "reason": "governed_source_unavailable",
        }
    ]
    assert "super-secret" not in str(ledger.to_dict())


def test_evidence_ledger_accepts_verified_data_execution() -> None:
    ledger = ResponseEvidenceLedger.from_context(
        _intent(
            EvidenceRequirement.METRIC_DEFINITION,
            EvidenceRequirement.TRUSTED_DATA_SOURCE,
            EvidenceRequirement.BUSINESS_RULES,
            EvidenceRequirement.VALIDATED_SQL,
            EvidenceRequirement.EXECUTED_RESULT,
            stage=DataIntentStage.EXECUTE_AND_VERIFY,
        ),
        context_manifest={},
        memory_ids=[],
    )
    ledger.observe_tool(
        "execute_sql_draft",
        {
            "status": "success",
            "result": {
                "execution_summary": {
                    "data_agent_run_id": "run-1",
                    "state": "completed",
                    "result_validation": {"status": "pass"},
                    "answer_metadata": {
                        "snapshot_id": "snapshot-1",
                        "evidence_requirements": {
                            "metric_definition": True,
                            "trusted_data_source": True,
                            "business_rules": True,
                            "validated_sql": True,
                            "executed_result": True,
                        },
                    },
                    "answer_citations": [{"label": "R1"}],
                }
            },
        },
    )

    content, gate = ledger.govern_answer("复购率为 42% [R1]。")

    assert content == "复购率为 42% [R1]。"
    assert gate["status"] == "pass"
    assert ledger.to_dict()["source_counts"]["data"] == 1


def test_execution_does_not_claim_unproven_governance_requirements() -> None:
    ledger = ResponseEvidenceLedger.from_context(
        _intent(
            EvidenceRequirement.METRIC_DEFINITION,
            EvidenceRequirement.TRUSTED_DATA_SOURCE,
            EvidenceRequirement.BUSINESS_RULES,
            EvidenceRequirement.EXECUTED_RESULT,
            stage=DataIntentStage.EXECUTE_AND_VERIFY,
        ),
        context_manifest={},
        memory_ids=[],
    )
    ledger.observe_tool(
        "execute_sql_draft",
        {
            "status": "success",
            "result": {
                "execution_summary": {
                    "data_agent_run_id": "run-1",
                    "state": "completed",
                    "result_validation": {"status": "pass"},
                    "answer_metadata": {
                        "snapshot_id": "snapshot-1",
                        "data_source": {
                            "id": "source-1",
                            "decision": {"status": "selected"},
                        },
                        "metrics": [
                            {
                                "name": "复购率",
                                "evidence_id": "metric:repurchase-rate",
                            }
                        ],
                        "evidence_requirements": {
                            "metric_definition": False,
                            "trusted_data_source": False,
                            "business_rules": False,
                            "validated_sql": True,
                            "executed_result": True,
                        },
                    },
                    "answer_citations": [{"label": "R1", "evidence_type": "execution_result"}],
                }
            },
        },
    )

    content, gate = ledger.govern_answer("结果为 42 [R1]。")

    assert gate["status"] == "blocked"
    assert gate["answer_replaced"] is True
    assert "治理证据仍不完整" in content
    assert set(gate["missing"]) == {
        "metric_definition",
        "trusted_data_source",
        "business_rules",
    }


def test_result_snapshot_is_content_addressed_and_stable() -> None:
    scope = DataScope(
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        data_source_id="source-1",
    )
    run = QueryRun(
        id="run-1",
        request=QueryRequest(question="销售额", scope=scope),
        evidence=EvidenceBundle(
            schema_fingerprint="schema-v1",
            semantic_version="semantic-v1",
            dialect="postgres",
        ),
        result=ExecutionResult(
            rows=[{"amount": 12}],
            returned_rows=1,
            total_rows=1,
            columns=["amount"],
        ),
    )
    candidate = CandidateSQL(sql="SELECT SUM(amount) AS amount FROM orders")
    first = bind_result_snapshot(run, candidate)
    second = bind_result_snapshot(run, candidate)

    assert first == second
    assert first is not None and first.startswith("snapshot_")
    assert run.result is not None and run.result.snapshot_id == first


def test_sql_draft_execution_is_governed_read() -> None:
    spec = governed_sql_execution_spec()

    assert spec.side_effect.value == "write"
    assert spec.operation_class == "governed_read"
    assert spec.max_retries == 0
