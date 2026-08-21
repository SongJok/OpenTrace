from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agents.production_agent import _build_arguments, _operation_score, _target_domains
from connectors.contracts import ConnectorOperationSpec
from infra.storage.models import EnterpriseConnector, ProductionAsset, ProductionConfigPolicy
from kernel.agent_loop.contracts import (
    EvidenceRequirement,
    ExecutionPlan,
    InformationSource,
    IntentPlan,
    PlanningDecision,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.evidence import ResponseEvidenceLedger
from kernel.agent_loop.intent_policy import apply_enterprise_intent_policy
from services.production_intelligence.actions import (
    ProductionActionError,
    bind_operation_arguments,
    make_action_ref,
    parse_action_ref,
)
from services.production_intelligence.config_intelligence import DeterministicConfigValidator
from services.production_intelligence.evidence_critic import ProductionEvidenceCritic


def _tool(name: str) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        side_effect=SideEffect.READ,
    )


def _decision() -> PlanningDecision:
    return PlanningDecision(
        intent=IntentPlan(goal="test"),
        execution_plan=ExecutionPlan(goal="test"),
    )


def _policy() -> ProductionConfigPolicy:
    return ProductionConfigPolicy(
        id="policy-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_id="asset-config",
        version=1,
        status="published",
        schema={
            "type": "object",
            "properties": {
                "replicas": {"type": "integer", "minimum": 1},
                "region": {"type": "string"},
                "mode": {"type": "string"},
                "blue": {"type": "boolean"},
                "green": {"type": "boolean"},
            },
            "required": ["replicas", "region", "mode"],
            "additionalProperties": False,
        },
        reference_rules=[
            {
                "id": "region-catalog",
                "path": "/region",
                "allowed_values": ["cn-east", "cn-north"],
                "severity": "error",
            }
        ],
        business_rules=[
            {
                "id": "safe-mode",
                "path": "/mode",
                "operator": "in",
                "value": ["safe", "readonly"],
                "severity": "error",
            }
        ],
        history_rules=[
            {
                "id": "replica-change",
                "path": "/replicas",
                "max_change_ratio": 0.5,
                "min_samples": 3,
                "severity": "warning",
            }
        ],
        capacity_rules=[
            {
                "id": "replica-capacity",
                "path": "/replicas",
                "operator": "lte",
                "value": 10,
                "severity": "error",
            }
        ],
        conflict_rules=[
            {
                "id": "rollout-conflict",
                "paths": ["/blue", "/green"],
                "max_present": 1,
                "severity": "error",
            }
        ],
        dry_run_operation="validate_config",
        created_by="admin-1",
    )


def test_config_validator_covers_schema_reference_business_history_capacity_conflict_and_dry_run():
    validator = DeterministicConfigValidator()
    report = validator.validate(
        candidate={
            "replicas": 5,
            "region": "cn-east",
            "mode": "safe",
            "blue": True,
            "green": True,
        },
        policy=_policy(),
        history=[{"replicas": 4}, {"replicas": 4}, {"replicas": 4}],
        dry_run={"status": "passed"},
    )

    assert report.status == "fail"
    assert report.risk_level == "critical"
    assert {item.category for item in report.checks} == {
        "schema",
        "reference",
        "business_rule",
        "history",
        "capacity",
        "conflict",
        "dry_run",
    }
    conflict = next(item for item in report.checks if item.category == "conflict")
    assert conflict.status == "fail"


def test_config_validator_passes_safe_candidate_and_never_executes_arbitrary_code():
    report = DeterministicConfigValidator().validate(
        candidate={
            "replicas": 5,
            "region": "cn-east",
            "mode": "safe",
            "blue": True,
            "green": False,
        },
        policy=_policy(),
        history=[{"replicas": 4}, {"replicas": 4}, {"replicas": 4}],
        dry_run={"status": "passed"},
    )

    assert report.status == "pass"
    assert report.risk_level == "low"
    assert report.summary["errors"] == 0


def test_config_validator_does_not_treat_transport_completion_as_dry_run_success():
    report = DeterministicConfigValidator().validate(
        candidate={
            "replicas": 5,
            "region": "cn-east",
            "mode": "safe",
            "blue": True,
            "green": False,
        },
        policy=_policy(),
        history=[{"replicas": 4}, {"replicas": 4}, {"replicas": 4}],
        dry_run={"status": "completed"},
    )

    assert report.status == "fail"
    dry_run = next(item for item in report.checks if item.category == "dry_run")
    assert dry_run.status == "fail"


def test_production_critic_rejects_failed_config_validation_requirements():
    now = datetime.now(UTC).isoformat()
    assessment = ProductionEvidenceCritic().assess(
        [
            {
                "evidence_type": "config_validation",
                "source_kind": "config_validator",
                "source_ref": "config-validation://failed",
                "environment": "prod",
                "observed_at": now,
                "payload": {"status": "fail"},
                "requirements": ["config_validation"],
            },
            {
                "evidence_type": "config_dry_run",
                "source_kind": "config_backend",
                "source_ref": "config-dry-run://transport-completed",
                "environment": "prod",
                "observed_at": now,
                "payload": {"verification_status": "failed"},
                "requirements": ["config_dry_run"],
            },
        ],
        required={"config_validation", "config_dry_run"},
        expected_environment="prod",
    )

    assert assessment.status == "blocked"
    assert assessment.requirements_missing == ("config_dry_run", "config_validation")


def test_config_validator_uses_history_percentiles_and_capacity_formula() -> None:
    policy = _policy()
    policy.schema = {
        "type": "object",
        "properties": {
            "batchSize": {"type": "integer"},
            "maxUsers": {"type": "integer"},
            "requestsPerUser": {"type": "number"},
        },
        "required": ["batchSize", "maxUsers", "requestsPerUser"],
        "additionalProperties": False,
    }
    policy.reference_rules = []
    policy.business_rules = []
    policy.conflict_rules = []
    policy.dry_run_operation = None
    policy.history_rules = [
        {
            "id": "batch-history",
            "path": "/batchSize",
            "baseline_percentile": 95,
            "max_multiplier": 2,
            "min_samples": 5,
            "severity": "error",
        }
    ]
    policy.capacity_rules = [
        {
            "id": "projected-qps",
            "path": "/projectedQps",
            "operator": "lte",
            "value": 2_000,
            "estimate": {
                "operation": "product",
                "terms": [{"path": "/maxUsers"}, {"path": "/requestsPerUser"}],
            },
            "severity": "error",
        }
    ]
    report = DeterministicConfigValidator().validate(
        candidate={"batchSize": 500, "maxUsers": 1_000, "requestsPerUser": 3},
        policy=policy,
        history=[
            {"batchSize": 100},
            {"batchSize": 90},
            {"batchSize": 110},
            {"batchSize": 95},
            {"batchSize": 105},
        ],
    )

    history = next(item for item in report.checks if item.category == "history")
    capacity = next(item for item in report.checks if item.category == "capacity")
    assert history.status == "fail"
    assert history.expected["statistics"]["p95"] == pytest.approx(109.0)
    assert capacity.status == "fail"
    assert capacity.actual["estimate"] == 3_000
    assert report.risk_level == "critical"


def test_production_critic_requires_fresh_environment_aligned_independent_sources():
    now = datetime.now(UTC)
    evidence = [
        {
            "evidence_type": "asset",
            "source_kind": "asset_graph",
            "source_ref": "production-asset://service-1",
            "environment": "prod",
            "observed_at": now.isoformat(),
            "confidence": 0.9,
        },
        {
            "evidence_type": "metric",
            "source_kind": "mcp",
            "source_ref": "metric://service-1/error-rate",
            "connector_id": "prometheus-1",
            "environment": "prod",
            "observed_at": now.isoformat(),
            "confidence": 0.95,
        },
        {
            "evidence_type": "trace",
            "source_kind": "mcp",
            "source_ref": "trace://service-1/trace-1",
            "connector_id": "jaeger-1",
            "environment": "prod",
            "observed_at": now.isoformat(),
            "confidence": 0.9,
        },
    ]
    assessment = ProductionEvidenceCritic().assess(
        evidence,
        required={"asset_context", "live_observation", "cross_source_corroboration"},
        expected_environment="prod",
        now=now,
    )

    assert assessment.status == "pass"
    assert assessment.source_count == 3
    assert assessment.confidence >= 0.9


def test_production_critic_blocks_conflicting_claims():
    now = datetime.now(UTC).isoformat()
    evidence = [
        {
            "evidence_type": "metric",
            "source_kind": "observability",
            "source_ref": "metric://a",
            "connector_id": "a",
            "environment": "prod",
            "observed_at": now,
            "payload": {"claim_key": "service.status", "claim_value": "healthy"},
        },
        {
            "evidence_type": "business_record",
            "source_kind": "business",
            "source_ref": "business://b",
            "connector_id": "b",
            "environment": "prod",
            "observed_at": now,
            "payload": {"claim_key": "service.status", "claim_value": "degraded"},
        },
    ]

    assessment = ProductionEvidenceCritic().assess(
        evidence,
        required={"live_observation", "cross_source_corroboration"},
        expected_environment="prod",
    )
    assert assessment.status == "blocked"
    assert assessment.conflicts[0]["claim_key"] == "service.status"


def test_intent_policy_routes_production_and_config_to_controlled_agents():
    production = apply_enterprise_intent_policy(
        _decision(),
        query="生产 payment-service 为什么错误率上升？",
        context_manifest={},
        tool_specs=[_tool("production"), _tool("config"), _tool("rag")],
    )
    assert production.intent.capabilities == ("production",)
    assert production.intent.information_sources == (InformationSource.PRODUCTION,)
    assert EvidenceRequirement.CROSS_SOURCE_CORROBORATION in production.intent.evidence_requirements

    config = apply_enterprise_intent_policy(
        _decision(),
        query="校验 payment-service 的生产配置是否有容量冲突",
        context_manifest={},
        tool_specs=[_tool("production"), _tool("config"), _tool("rag")],
    )
    assert config.intent.capabilities == ("config",)
    assert config.intent.information_sources == (InformationSource.CONFIG,)
    assert EvidenceRequirement.CONFIG_VALIDATION in config.intent.evidence_requirements
    assert EvidenceRequirement.CONFIG_CAPACITY in config.intent.evidence_requirements


def test_production_ledger_blocks_critic_conflicts_and_does_not_trust_declared_requirements():
    ledger = ResponseEvidenceLedger(
        IntentPlan(
            goal="diagnose",
            information_sources=(InformationSource.PRODUCTION,),
            evidence_requirements=(
                EvidenceRequirement.ASSET_CONTEXT,
                EvidenceRequirement.LIVE_OBSERVATION,
            ),
        )
    )
    ledger.observe_tool(
        "production",
        {
            "status": "success",
            "evidence": [
                {
                    "evidence_type": "asset",
                    "source_ref": "asset://service-1",
                    "title": "service-1",
                    "requirements": ["asset_context"],
                },
                {
                    "evidence_type": "metric",
                    "source_ref": "metric://service-1",
                    "title": "error rate",
                    "requirements": ["live_observation"],
                },
            ],
            "metadata": {
                "critic": {
                    "status": "blocked",
                    "gaps": ["来源冲突"],
                    "conflicts": [{"claim_key": "service.status"}],
                }
            },
        },
    )

    assessment = ledger.assessment()
    assert assessment["missing"] == ["asset_context", "live_observation"]
    assert assessment["status"] == "blocked"
    assert len(ledger.entries) == 2
    answer, gate = ledger.govern_answer("service healthy")
    assert "不能给出可靠结论" in answer
    assert gate["answer_replaced"] is True


def test_production_ledger_keeps_incomplete_evidence_for_audit_but_never_unlocks_answer():
    ledger = ResponseEvidenceLedger(
        IntentPlan(
            goal="diagnose",
            information_sources=(InformationSource.PRODUCTION,),
            evidence_requirements=(
                EvidenceRequirement.ASSET_CONTEXT,
                EvidenceRequirement.LIVE_OBSERVATION,
            ),
        )
    )
    ledger.observe_tool(
        "production",
        {
            "status": "success",
            "evidence": [
                {
                    "evidence_type": "asset",
                    "source_ref": "asset://service-1",
                    "requirements": ["asset_context"],
                },
                {
                    "evidence_type": "metric",
                    "source_ref": "metric://service-1",
                    "requirements": ["live_observation"],
                },
            ],
            "metadata": {
                "critic": {
                    "status": "incomplete",
                    "requirements_satisfied": ["asset_context", "live_observation"],
                    "gaps": ["实时指标已经过期"],
                    "conflicts": [],
                }
            },
        },
    )

    assessment = ledger.assessment()
    assert assessment["status"] == "blocked"
    assert assessment["missing"] == ["asset_context", "live_observation"]
    assert assessment["critic_failures"][0]["reason"] == "production_evidence_incomplete"
    assert len(ledger.entries) == 2
    assert all(not entry.requirements for entry in ledger.entries.values())
    answer, gate = ledger.govern_answer("service healthy")
    assert "未通过 Critic" in answer
    assert gate["answer_replaced"] is True


def test_production_operation_binding_is_platform_controlled_and_read_only():
    asset = ProductionAsset(
        id="asset-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_type="service",
        external_key="payment-service",
        name="Payment Service",
        environment="prod",
        created_by="admin-1",
    )
    connector = EnterpriseConnector(
        id="connector-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        name="prometheus",
        connector_kind="observability",
        transport="native",
        status="enabled",
        created_by="admin-1",
    )
    spec = ConnectorOperationSpec(
        name="query_metrics",
        description="query service metrics",
        domain="observability",
        risk="read",
        input_schema={
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "environment": {"type": "string"},
            },
            "required": ["service", "environment"],
            "additionalProperties": False,
        },
    )
    arguments = _build_arguments(
        spec.input_schema,
        query="生产错误率",
        environment="prod",
        asset=asset,
    )
    assert arguments == {"service": "payment-service", "environment": "prod"}
    assert "observability" in _target_domains("查看生产错误率和 trace")
    assert _operation_score(connector, spec, "查看生产 metrics", {"observability"}) > 0

    unsupported = _build_arguments(
        {
            "type": "object",
            "properties": {"arbitrary_target": {"type": "string"}},
            "required": ["arbitrary_target"],
        },
        query="test",
        environment="prod",
        asset=asset,
    )
    assert unsupported is None


def test_production_action_reference_and_arguments_are_server_bound():
    asset = ProductionAsset(
        id="asset-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_type="deployment",
        external_key="payment-v2.17.4",
        name="Payment v2.17.4",
        environment="prod",
        created_by="admin-1",
    )
    connector = EnterpriseConnector(
        id="connector-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        name="deployment-control",
        connector_kind="cicd",
        transport="mcp",
        status="enabled",
        config={
            "operation_bindings": {"rollback_deployment": {"strategy": "previous_verified_release"}}
        },
        created_by="admin-1",
    )
    reference = make_action_ref(
        connector_id=connector.id,
        operation="rollback_deployment",
        asset_id=asset.id,
        environment="prod",
    )
    parsed = parse_action_ref(reference)
    assert parsed.connector_id == connector.id
    assert parsed.asset_id == asset.id
    assert parsed.operation == "rollback_deployment"
    arguments = bind_operation_arguments(
        {
            "type": "object",
            "properties": {
                "deployment_id": {"type": "string"},
                "environment": {"type": "string"},
                "strategy": {"type": "string"},
            },
            "required": ["deployment_id", "environment", "strategy"],
            "additionalProperties": False,
        },
        query="用户明确要求回滚，并已核对错误率和 Trace",
        environment="prod",
        asset=asset,
        connector=connector,
        operation="rollback_deployment",
    )
    assert arguments == {
        "deployment_id": "payment-v2.17.4",
        "environment": "prod",
        "strategy": "previous_verified_release",
    }
    with pytest.raises(ProductionActionError, match="reference_invalid"):
        parse_action_ref("connector-1:rollback_deployment")
