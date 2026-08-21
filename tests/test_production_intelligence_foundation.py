from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from connectors.bootstrap import load_configured_secret_resolver, register_configured_connectors
from connectors.contracts import (
    ConnectorEvidence,
    ConnectorExecutionContext,
    ConnectorOperationSpec,
    ConnectorResult,
)
from connectors.gateway import ConnectorGatewayError, GovernedConnectorGateway
from connectors.mcp import MCPStreamableHTTPAdapter
from connectors.prometheus import PrometheusHTTPAdapter
from connectors.registry import ConnectorRegistry, connector_registry
from connectors.runtime import ConnectorRuntimeControl, runtime_policy_from_config
from connectors.sdk import NativeConnectorBuilder
from gateway.api_gateway.routers.production_intelligence import router as production_router
from infra.storage.models import (
    AuditLog,
    EnterpriseConnector,
    ProductionAsset,
    ProductionAssetRelation,
    ProductionAssetSyncRun,
    ProductionEvidence,
    User,
)
from services.production_intelligence.actions import (
    ProductionActionError,
    discover_production_actions,
    execute_production_action,
    make_action_ref,
)
from services.production_intelligence.asset_graph import AssetGraphService, ProductionScope
from services.production_intelligence.asset_sync import AssetSyncError, ProductionAssetSyncService
from services.production_intelligence.config_intelligence import (
    ConfigIntelligenceError,
    ConfigIntelligenceService,
)
from services.production_intelligence.connectors import (
    ConnectorCatalogError,
    ConnectorCatalogService,
)
from services.production_intelligence.policy import CapabilityPolicy

ROOT = Path(__file__).resolve().parents[1]


class _ScalarResult:
    def __init__(self, rows: list[Any]):
        self._rows = rows

    def scalars(self) -> _ScalarResult:
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class _FakeDB:
    def __init__(self, *, scalars: list[Any] | None = None, rows: list[Any] | None = None):
        self.scalar_values = list(scalars or [])
        self.rows = list(rows or [])
        self.added: list[Any] = []
        self.flush_count = 0
        self.deleted: list[Any] = []

    async def scalar(self, _statement):
        return self.scalar_values.pop(0) if self.scalar_values else None

    async def execute(self, _statement):
        return _ScalarResult(self.rows)

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flush_count += 1

    async def delete(self, row: Any) -> None:
        self.deleted.append(row)


class _SequenceDB(_FakeDB):
    def __init__(self, execute_rows: list[list[Any]]):
        super().__init__()
        self.execute_rows = list(execute_rows)

    async def execute(self, _statement):
        rows = self.execute_rows.pop(0) if self.execute_rows else []
        return _ScalarResult(rows)


class _RowcountResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _SyncDB(_FakeDB):
    def __init__(self, *, scalars: list[Any], execute_values: list[Any]):
        super().__init__(scalars=scalars)
        self.execute_values = list(execute_values)
        self.commit_count = 0
        self.rollback_count = 0

    async def scalar(self, _statement):
        value = self.scalar_values.pop(0) if self.scalar_values else None
        return value(self) if callable(value) else value

    async def execute(self, _statement):
        value = self.execute_values.pop(0)
        return _ScalarResult(value) if isinstance(value, list) else value

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class _AllowRuntimeStore:
    async def acquire(self, **_kwargs):
        return True, "closed", 0

    async def record_outcome(self, **_kwargs) -> None:
        return None


class _OutcomeRuntimeStore(_AllowRuntimeStore):
    def __init__(self) -> None:
        self.outcomes: list[bool] = []

    async def record_outcome(self, **kwargs) -> None:
        self.outcomes.append(bool(kwargs["success"]))


def _runtime_control() -> ConnectorRuntimeControl:
    return ConnectorRuntimeControl(store=_AllowRuntimeStore())  # type: ignore[arg-type]


class _UnavailableRuntimeStore:
    async def acquire(self, **_kwargs):
        raise ConnectionError("redis unavailable")

    async def record_outcome(self, **_kwargs) -> None:
        raise ConnectionError("redis unavailable")


class _DenyRuntimeStore:
    async def acquire(self, **_kwargs):
        return False, "rate_limited", 2500

    async def record_outcome(self, **_kwargs) -> None:
        raise AssertionError("被拒绝的调用不得记录执行结果")


class _ObservabilityAdapter:
    adapter_key = "test-observability"
    calls = 0

    def operations(self) -> tuple[ConnectorOperationSpec, ...]:
        return (
            ConnectorOperationSpec(
                name="query_traces",
                description="查询 Trace",
                domain="observability",
                input_schema={
                    "type": "object",
                    "properties": {"service": {"type": "string", "minLength": 1, "maxLength": 64}},
                    "required": ["service"],
                    "additionalProperties": False,
                },
                evidence_types=("trace",),
            ),
        )

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        context: ConnectorExecutionContext,
        connector_config: dict[str, Any],
        secret_ref: str | None,
    ) -> ConnectorResult:
        self.calls += 1
        assert operation == "query_traces"
        assert connector_config["_policy_data_mode"] in {"masked", "full"}
        assert secret_ref == "vault://opentrace/grafana"
        return ConnectorResult(
            status="completed",
            data={
                "trace_id": "trace-1",
                "customer_email": "alice@example.com",
                "api_key": "must-not-leak",
            },
            evidence=(
                ConnectorEvidence(
                    evidence_type="trace",
                    source_ref="trace://trace-1",
                    title="ledger RPC timeout",
                    summary="alice@example.com 的 account-service 调用 ledger-service 超时",
                    observed_at=datetime.now(UTC),
                    environment=context.environment,
                    confidence=0.95,
                    payload={"authorization": "must-not-leak", "duration_ms": 5000},
                ),
            ),
        )


class _RestrictedObservabilityAdapter(_ObservabilityAdapter):
    adapter_key = "restricted-observability"

    def operations(self) -> tuple[ConnectorOperationSpec, ...]:
        base = super().operations()[0]
        return (
            ConnectorOperationSpec(
                name=base.name,
                description=base.description,
                domain=base.domain,
                input_schema=base.input_schema,
                required_permissions=("role:sre",),
                evidence_types=base.evidence_types,
            ),
        )


class _InvalidEvidenceAdapter(_ObservabilityAdapter):
    adapter_key = "invalid-evidence"

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        context: ConnectorExecutionContext,
        connector_config: dict[str, Any],
        secret_ref: str | None,
    ) -> ConnectorResult:
        del operation, arguments, connector_config, secret_ref
        return ConnectorResult(
            status="completed",
            evidence=(
                ConnectorEvidence(
                    evidence_type="trace",
                    source_ref="trace://invalid",
                    title="invalid evidence",
                    summary="",
                    observed_at=datetime.now(UTC),
                    environment=context.environment,
                ),
            ),
        )


class _ProductionActionAdapter:
    adapter_key = "test-production-action"

    def operations(self) -> tuple[ConnectorOperationSpec, ...]:
        return (
            ConnectorOperationSpec(
                name="rollback_deployment",
                description="回滚到上一个已验证版本",
                domain="cicd",
                risk="write_high",
                input_schema={
                    "type": "object",
                    "properties": {
                        "deployment_id": {"type": "string"},
                        "environment": {"type": "string"},
                    },
                    "required": ["deployment_id", "environment"],
                    "additionalProperties": False,
                },
                required_permissions=("role:sre",),
                max_output_bytes=32_768,
                evidence_types=("deployment",),
                verification_evidence_types=("deployment",),
                supports_idempotency=True,
            ),
        )

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        context: ConnectorExecutionContext,
        connector_config: dict[str, Any],
        secret_ref: str | None,
    ) -> ConnectorResult:
        assert operation == "rollback_deployment"
        assert context.approved is True
        assert arguments == {"deployment_id": "payment-v2.17.4", "environment": "prod"}
        return ConnectorResult(
            status="completed",
            data={"release": "payment-v2.17.3"},
            evidence=(
                ConnectorEvidence(
                    evidence_type="deployment",
                    source_ref="deployment://payment-v2.17.3",
                    title="回滚后部署状态",
                    summary="payment-service 已回到 v2.17.3 且健康检查通过",
                    observed_at=datetime.now(UTC),
                    asset_id="asset-deployment-1",
                    environment="prod",
                    authority="deployment_control_plane",
                    confidence=0.99,
                    payload={
                        "verification": {
                            "status": "verified",
                            "idempotency_key": context.idempotency_key,
                        }
                    },
                ),
            ),
        )


class _SecretResolver:
    async def resolve_headers(self, secret_ref: str | None) -> dict[str, str]:
        assert secret_ref == "vault://opentrace/grafana"
        return {"Authorization": "Bearer resolved-but-never-persisted"}


class _MCPResult:
    is_error = False
    structured_content = {
        "summary": "支付服务错误率上升",
        "evidence": [
            {
                "evidence_type": "metric",
                "source_ref": "metric://payment/error-rate",
                "title": "payment error rate",
                "summary": "错误率从 0.02% 上升到 4.7%",
                "environment": "prod",
                "observed_at": datetime.now(UTC).isoformat(),
                "confidence": 0.9,
            }
        ],
    }
    content: list[Any] = []


def _connector(**changes: Any) -> EnterpriseConnector:
    values: dict[str, Any] = {
        "id": "connector-1",
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "name": "grafana-prod",
        "connector_kind": "observability",
        "transport": "mcp",
        "endpoint": "https://grafana.example.com/mcp",
        "secret_ref": "vault://opentrace/grafana",
        "status": "enabled",
        "allowed_operations": ["query_traces"],
        "allowed_environments": ["prod"],
        "data_classification": "internal",
        "config": {"adapter_key": "test-observability"},
        "created_by": "admin-1",
    }
    values.update(changes)
    return EnterpriseConnector(**values)


def _context(**changes: Any) -> ConnectorExecutionContext:
    values: dict[str, Any] = {
        "tenant_id": "tenant-a",
        "workspace_id": "workspace-a",
        "user_id": "user-1",
        "role": "user",
        "environment": "prod",
        "trace_id": "request-1",
    }
    values.update(changes)
    return ConnectorExecutionContext(**values)


def _register_action_adapter() -> _ProductionActionAdapter:
    existing = connector_registry.get(_ProductionActionAdapter.adapter_key)
    if existing is not None:
        return existing  # type: ignore[return-value]
    adapter = _ProductionActionAdapter()
    connector_registry.register(adapter)
    return adapter


def test_capability_policy_is_default_deny_and_requires_durable_approval() -> None:
    policy = CapabilityPolicy()

    customer_read = policy.authorize(
        role="user", domain="observability", risk="read", environment="prod"
    )
    assert customer_read.allowed is True
    assert customer_read.data_mode == "masked"

    denied_write = policy.authorize(
        role="user", domain="config", risk="write_low", environment="prod"
    )
    assert denied_write.allowed is False

    sre_write = policy.authorize(role="sre", domain="config", risk="write_high", environment="prod")
    assert sre_write.allowed is True
    assert sre_write.approval_required is True
    assert policy.role_projection("sre")["destructive_writes_required_approvals"] == 2

    restricted = policy.authorize(
        role="developer", domain="data", risk="read", classification="restricted"
    )
    assert restricted.allowed is False


def test_connector_registry_rejects_duplicate_and_invalid_adapters() -> None:
    registry = ConnectorRegistry()
    adapter = _ObservabilityAdapter()
    registry.register(adapter)
    assert registry.require(adapter.adapter_key) is adapter
    with pytest.raises(ValueError, match="already_registered"):
        registry.register(adapter)


def test_connector_entrypoints_are_explicitly_allowlisted_and_fail_closed(monkeypatch) -> None:
    registry = ConnectorRegistry()
    adapter = _ObservabilityAdapter()
    unapproved_loaded = False

    class EntryPoint:
        def __init__(self, name: str, value: Any):
            self.name = name
            self.value = value

        def load(self):
            nonlocal unapproved_loaded
            if self.name == "unapproved":
                unapproved_loaded = True
            return self.value

    monkeypatch.setattr(
        "connectors.bootstrap._entry_points_for_group",
        lambda: [
            EntryPoint("approved", lambda: adapter),
            EntryPoint("unapproved", lambda: _InvalidEvidenceAdapter()),
        ],
    )

    registered = register_configured_connectors(
        registry=registry,
        names=("approved",),
    )
    assert registered == (adapter.adapter_key,)
    assert registry.require(adapter.adapter_key) is adapter
    assert unapproved_loaded is False

    with pytest.raises(RuntimeError, match="entrypoint_missing:missing"):
        register_configured_connectors(registry=ConnectorRegistry(), names=("missing",))


def test_mcp_secret_resolver_entrypoint_is_singular_and_fails_closed(monkeypatch) -> None:
    resolver = _SecretResolver()

    class EntryPoint:
        name = "approved_vault"

        @staticmethod
        def load():
            return lambda: resolver

    monkeypatch.setattr(
        "connectors.bootstrap._secret_resolver_entry_points",
        lambda: [EntryPoint()],
    )

    assert load_configured_secret_resolver("approved_vault") is resolver
    with pytest.raises(RuntimeError, match="entrypoint_missing:missing"):
        load_configured_secret_resolver("missing")


@pytest.mark.asyncio
async def test_native_connector_sdk_binds_declared_handler() -> None:
    builder = NativeConnectorBuilder("example.health")

    @builder.operation(
        ConnectorOperationSpec(
            name="health",
            description="健康检查",
            domain="observability",
            input_schema={
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": ["service"],
                "additionalProperties": False,
            },
            evidence_types=("metric",),
        )
    )
    async def health(arguments, *, context, connector_config, secret_ref):
        assert context.environment == "prod"
        assert connector_config == {"region": "cn-east"}
        assert secret_ref == "vault://observability"
        return ConnectorResult(status="completed", data={"service": arguments["service"]})

    adapter = builder.build()
    result = await adapter.execute(
        "health",
        {"service": "payment-service"},
        context=_context(),
        connector_config={"region": "cn-east"},
        secret_ref="vault://observability",
    )

    assert adapter.adapter_key == "example.health"
    assert adapter.operations()[0].name == "health"
    assert result.data == {"service": "payment-service"}


@pytest.mark.asyncio
async def test_builtin_prometheus_adapter_uses_live_timestamps_and_controlled_promql() -> None:
    captured: dict[str, Any] = {}

    async def request(endpoint, params, headers, timeout, max_bytes):
        captured.update(
            endpoint=endpoint,
            params=params,
            headers=headers,
            timeout=timeout,
            max_bytes=max_bytes,
        )
        return {
            "status": "success",
            "data": {
                "resultType": "vector",
                "result": [{"metric": {}, "value": [1_777_000_000, "0.047"]}],
            },
        }

    adapter = PrometheusHTTPAdapter(requester=request, secret_resolver=_SecretResolver())
    result = await adapter.execute(
        "query_http_error_ratio",
        {
            "service": 'payment-service" or vector(1)',
            "environment": "prod",
            "asset_id": "asset-1",
            "window_seconds": 300,
        },
        context=_context(),
        connector_config={"endpoint": "https://prometheus.example.com"},
        secret_ref="vault://opentrace/grafana",
    )

    assert result.status == "completed"
    assert result.data["series"][0]["value"] == pytest.approx(0.047)
    assert result.evidence[0].observed_at == datetime.fromtimestamp(1_777_000_000, tz=UTC)
    assert result.evidence[0].asset_id == "asset-1"
    assert "healthy" not in result.evidence[0].summary.lower()
    assert '\\" or vector(1)' in captured["params"]["query"]
    assert captured["headers"]["Authorization"].startswith("Bearer ")


def test_native_connector_sdk_rejects_duplicate_operations() -> None:
    builder = NativeConnectorBuilder("example.duplicate")
    spec = ConnectorOperationSpec(
        name="health",
        description="健康检查",
        domain="observability",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
    )

    async def handler(arguments, *, context, connector_config, secret_ref):
        del arguments, context, connector_config, secret_ref
        return ConnectorResult(status="completed")

    builder.operation(spec)(handler)
    with pytest.raises(ValueError, match="native_connector_operation_duplicate"):
        builder.operation(spec)(handler)


@pytest.mark.asyncio
async def test_mcp_adapter_uses_declared_operations_and_normalizes_evidence() -> None:
    captured: dict[str, Any] = {}

    async def invoke(endpoint, operation, arguments, headers, timeout):
        captured.update(
            endpoint=endpoint,
            operation=operation,
            arguments=arguments,
            headers=headers,
            timeout=timeout,
        )
        return _MCPResult()

    adapter = MCPStreamableHTTPAdapter(
        invoker=invoke,
        secret_resolver=_SecretResolver(),
    )
    config = {
        "endpoint": "https://grafana.example.com/mcp",
        "operation_specs": [
            {
                "name": "query_metrics",
                "description": "查询生产指标",
                "domain": "observability",
                "risk": "read",
                "input_schema": {
                    "type": "object",
                    "properties": {"service": {"type": "string"}},
                    "required": ["service"],
                    "additionalProperties": False,
                },
                "evidence_types": ["metric"],
                "supports_idempotency": True,
            }
        ],
    }
    result = await adapter.execute(
        "query_metrics",
        {"service": "payment-service"},
        context=_context(idempotency_key="read-request-1"),
        connector_config=config,
        secret_ref="vault://opentrace/grafana",
    )
    assert result.status == "completed"
    assert result.evidence[0].source_ref == "metric://payment/error-rate"
    assert captured["headers"]["Authorization"].startswith("Bearer ")
    assert captured["headers"]["Idempotency-Key"] == "read-request-1"
    assert "Authorization" not in result.data


@pytest.mark.asyncio
async def test_mcp_adapter_never_fabricates_evidence_timestamp_or_fallback_evidence() -> None:
    class MissingTimestampResult:
        is_error = False
        structured_content = {
            "summary": "远端只返回了无法核验的摘要",
            "evidence": [
                {
                    "evidence_type": "metric",
                    "source_ref": "metric://payment/error-rate",
                    "title": "payment error rate",
                    "summary": "缺少观测时间",
                    "environment": "prod",
                    "confidence": 0.9,
                }
            ],
        }
        content: list[Any] = []

    async def invoke(_endpoint, _operation, _arguments, _headers, _timeout):
        return MissingTimestampResult()

    adapter = MCPStreamableHTTPAdapter(invoker=invoke, secret_resolver=_SecretResolver())
    result = await adapter.execute(
        "query_metrics",
        {"service": "payment-service"},
        context=_context(),
        connector_config={
            "endpoint": "https://grafana.example.com/mcp",
            "operation_specs": [
                {
                    "name": "query_metrics",
                    "domain": "observability",
                    "input_schema": {"type": "object"},
                    "evidence_types": ["metric"],
                }
            ],
        },
        secret_ref="vault://opentrace/grafana",
    )

    assert result.status == "completed"
    assert result.evidence == ()
    assert result.data["summary"] == "远端只返回了无法核验的摘要"


@pytest.mark.asyncio
async def test_connector_runtime_control_rate_limit_and_store_failure_semantics() -> None:
    denied, _ = await ConnectorRuntimeControl(
        store=_DenyRuntimeStore()  # type: ignore[arg-type]
    ).acquire(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        connector_id="connector-1",
        risk="read",
        timeout_seconds=30,
        config={},
    )
    assert denied.admitted is False
    assert denied.reason == "rate_limited"
    assert denied.retry_after_ms == 2500

    unavailable = ConnectorRuntimeControl(
        store=_UnavailableRuntimeStore()  # type: ignore[arg-type]
    )
    read_admission, _ = await unavailable.acquire(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        connector_id="connector-1",
        risk="read",
        timeout_seconds=30,
        config={},
    )
    write_admission, _ = await unavailable.acquire(
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        connector_id="connector-1",
        risk="write_high",
        timeout_seconds=30,
        config={},
    )
    assert read_admission.admitted is True and read_admission.degraded is True
    assert write_admission.admitted is False and write_admission.degraded is False


def test_connector_runtime_policy_is_bounded_and_has_production_defaults() -> None:
    policy = runtime_policy_from_config({})
    assert policy.enabled is True
    assert policy.requests_per_minute == 120
    assert policy.failure_threshold == 5
    with pytest.raises(ValueError, match="out_of_range"):
        runtime_policy_from_config({"runtime_policy": {"max_concurrency": 0}})


@pytest.mark.asyncio
async def test_governed_connector_gateway_persists_sanitized_evidence_and_audit() -> None:
    registry = ConnectorRegistry()
    adapter = _ObservabilityAdapter()
    registry.register(adapter)
    gateway = GovernedConnectorGateway(registry=registry, runtime_control=_runtime_control())
    db = _FakeDB(scalars=[_connector()])

    result = await gateway.execute(
        db,  # type: ignore[arg-type]
        connector_id="connector-1",
        operation="query_traces",
        arguments={"service": "account-service"},
        context=_context(),
    )

    assert result.status == "completed"
    assert result.data["api_key"] == "***"
    assert result.data["customer_email"] == "***"
    assert "alice@example.com" not in result.evidence[0].summary
    evidence = next(row for row in db.added if isinstance(row, ProductionEvidence))
    assert evidence.tenant_id == "tenant-a"
    assert evidence.workspace_id == "workspace-a"
    assert evidence.source_ref == "trace://trace-1"
    assert evidence.payload["authorization"] == "***"
    assert evidence.content_hash.startswith("sha256:")
    audit = next(row for row in db.added if isinstance(row, AuditLog))
    audit_payload = json.loads(audit.payload_json)
    assert audit_payload["operation"] == "query_traces"
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_production_action_is_catalogued_then_executed_with_verification_evidence() -> None:
    _register_action_adapter()
    connector = _connector(
        connector_kind="cicd",
        config={"adapter_key": _ProductionActionAdapter.adapter_key},
        allowed_operations=["rollback_deployment"],
    )
    asset = ProductionAsset(
        id="asset-deployment-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_type="deployment",
        external_key="payment-v2.17.4",
        name="Payment v2.17.4",
        environment="prod",
        status="active",
        created_by="admin-1",
    )
    user = User(id="user-1", email="sre@example.com", role="sre", is_active=True)
    scope = ProductionScope("tenant-a", "workspace-a", "user-1")
    catalog = await discover_production_actions(
        _FakeDB(rows=[connector]),  # type: ignore[arg-type]
        scope=scope,
        user=user,
        query="依据错误率和 Trace 回滚 payment-service",
        assets=[asset],
    )
    assert len(catalog) == 1
    assert catalog[0]["operation"] == "rollback_deployment"
    assert catalog[0]["approval_required"] is True

    db = _FakeDB(
        scalars=[connector, asset, connector, "response-1", None],
        rows=[asset.id],
    )
    result = await execute_production_action(
        db,  # type: ignore[arg-type]
        scope=scope,
        response_id="response-1",
        user=user,
        action_ref=make_action_ref(
            connector_id=connector.id,
            operation="rollback_deployment",
            asset_id=asset.id,
            environment="prod",
        ),
        query="依据错误率和 Trace 回滚 payment-service",
        trace_id="response-1",
        gateway=GovernedConnectorGateway(runtime_control=_runtime_control()),
    )
    assert result["status"] == "completed"
    assert result["verification_status"] == "verified"
    assert result["verified_evidence_count"] == 1
    assert result["requires_reconciliation"] is False
    assert any(isinstance(row, ProductionEvidence) for row in db.added)

    class UnverifiedGateway:
        async def execute(self, *_args, **_kwargs):
            return ConnectorResult(
                status="completed",
                data={"release": "payment-v2.17.3"},
                evidence=(
                    ConnectorEvidence(
                        evidence_type="deployment",
                        source_ref="deployment://payment-v2.17.3",
                        title="部署完成事件",
                        summary="下游返回了部署事件，但没有绑定后置条件与幂等事实",
                        observed_at=datetime.now(UTC),
                        asset_id=asset.id,
                        environment="prod",
                    ),
                ),
            )

    unverified = await execute_production_action(
        _FakeDB(scalars=[connector, asset]),  # type: ignore[arg-type]
        scope=scope,
        response_id="response-unverified",
        user=user,
        action_ref=make_action_ref(
            connector_id=connector.id,
            operation="rollback_deployment",
            asset_id=asset.id,
            environment="prod",
        ),
        query="依据错误率和 Trace 回滚 payment-service",
        trace_id="response-unverified",
        gateway=UnverifiedGateway(),  # type: ignore[arg-type]
    )
    assert unverified["status"] == "incomplete"
    assert unverified["verification_status"] == "evidence_missing"
    assert unverified["requires_reconciliation"] is True

    class UnknownOutcomeGateway:
        async def execute(self, *_args, **_kwargs):
            raise ConnectorGatewayError("connector_operation_timeout", outcome_unknown=True)

    with pytest.raises(ProductionActionError) as raised:
        await execute_production_action(
            _FakeDB(scalars=[connector, asset]),  # type: ignore[arg-type]
            scope=scope,
            response_id="response-unknown",
            user=user,
            action_ref=make_action_ref(
                connector_id=connector.id,
                operation="rollback_deployment",
                asset_id=asset.id,
                environment="prod",
            ),
            query="依据错误率和 Trace 回滚 payment-service",
            trace_id="response-unknown",
            gateway=UnknownOutcomeGateway(),  # type: ignore[arg-type]
        )
    assert raised.value.outcome_unknown is True


@pytest.mark.asyncio
async def test_connector_gateway_enforces_declared_permissions_and_deduplicates_retry_evidence():
    registry = ConnectorRegistry()
    adapter = _RestrictedObservabilityAdapter()
    registry.register(adapter)
    gateway = GovernedConnectorGateway(registry=registry, runtime_control=_runtime_control())
    connector = _connector(config={"adapter_key": adapter.adapter_key})

    with pytest.raises(ConnectorGatewayError, match="required_permission_missing"):
        await gateway.execute(
            _FakeDB(scalars=[connector]),  # type: ignore[arg-type]
            connector_id=connector.id,
            operation="query_traces",
            arguments={"service": "account-service"},
            context=_context(role="user"),
        )

    db = _FakeDB(scalars=[connector, "response-1", "existing-evidence"])
    result = await gateway.execute(
        db,  # type: ignore[arg-type]
        connector_id=connector.id,
        operation="query_traces",
        arguments={"service": "account-service"},
        context=_context(role="sre", response_id="response-1"),
    )
    assert result.status == "completed"
    assert not any(isinstance(row, ProductionEvidence) for row in db.added)
    assert any(isinstance(row, AuditLog) for row in db.added)


@pytest.mark.asyncio
async def test_connector_invalid_output_records_runtime_failure_and_failure_audit() -> None:
    registry = ConnectorRegistry()
    adapter = _InvalidEvidenceAdapter()
    registry.register(adapter)
    store = _OutcomeRuntimeStore()
    gateway = GovernedConnectorGateway(
        registry=registry,
        runtime_control=ConnectorRuntimeControl(store=store),  # type: ignore[arg-type]
    )
    db = _FakeDB(scalars=[_connector(config={"adapter_key": adapter.adapter_key})])

    with pytest.raises(ConnectorGatewayError, match="evidence_content_required"):
        await gateway.execute(
            db,  # type: ignore[arg-type]
            connector_id="connector-1",
            operation="query_traces",
            arguments={"service": "account-service"},
            context=_context(),
        )

    assert store.outcomes == [False]
    failure_audits = [
        row
        for row in db.added
        if isinstance(row, AuditLog) and row.action == "enterprise_connector.execution_failed"
    ]
    assert len(failure_audits) == 1


@pytest.mark.asyncio
async def test_connector_gateway_rejects_environment_and_unknown_arguments_before_execution() -> (
    None
):
    registry = ConnectorRegistry()
    adapter = _ObservabilityAdapter()
    registry.register(adapter)
    gateway = GovernedConnectorGateway(registry=registry, runtime_control=_runtime_control())

    with pytest.raises(ConnectorGatewayError, match="environment_not_allowed"):
        await gateway.execute(
            _FakeDB(scalars=[_connector()]),  # type: ignore[arg-type]
            connector_id="connector-1",
            operation="query_traces",
            arguments={"service": "account-service"},
            context=_context(environment="staging"),
        )

    with pytest.raises(ConnectorGatewayError, match="arguments_unknown"):
        await gateway.execute(
            _FakeDB(scalars=[_connector()]),  # type: ignore[arg-type]
            connector_id="connector-1",
            operation="query_traces",
            arguments={"service": "account-service", "url": "http://metadata"},
            context=_context(),
        )


@pytest.mark.asyncio
async def test_connector_catalog_rejects_plaintext_secrets() -> None:
    service = ConnectorCatalogService(
        _FakeDB(),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    with pytest.raises(ConnectorCatalogError, match="plaintext_secret"):
        await service.create(
            name="unsafe",
            connector_kind="observability",
            transport="mcp",
            endpoint="https://example.com/mcp",
            secret_ref=None,
            status="disabled",
            allowed_operations=[],
            allowed_environments=[],
            data_classification="internal",
            config={"api_token": "plaintext"},
        )
    with pytest.raises(ConnectorCatalogError, match="secret_ref_invalid"):
        await service.create(
            name="unsafe-ref",
            connector_kind="observability",
            transport="mcp",
            endpoint="https://example.com/mcp",
            secret_ref="plaintext-token",
            status="disabled",
            allowed_operations=[],
            allowed_environments=[],
            data_classification="internal",
            config={},
        )


@pytest.mark.asyncio
async def test_connector_catalog_requires_mcp_operation_declarations() -> None:
    service = ConnectorCatalogService(
        _FakeDB(),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    with pytest.raises(ConnectorCatalogError, match="operation_specs_required"):
        await service.create(
            name="grafana",
            connector_kind="observability",
            transport="mcp",
            endpoint="https://grafana.example.com/mcp",
            secret_ref="env://GRAFANA_MCP_TOKEN",
            status="disabled",
            allowed_operations=["query_metrics"],
            allowed_environments=["prod"],
            data_classification="internal",
            config={},
        )


@pytest.mark.asyncio
async def test_connector_catalog_binds_transport_to_adapter_and_requires_enablement_readiness():
    service = ConnectorCatalogService(
        _FakeDB(scalars=[None]),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    operation_specs = [
        {
            "name": "query_metrics",
            "domain": "observability",
            "risk": "read",
            "input_schema": {
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": ["service"],
                "additionalProperties": False,
            },
            "evidence_types": ["metric"],
        }
    ]
    row = await service.create(
        name="grafana-disabled",
        connector_kind="observability",
        transport="mcp",
        endpoint="https://grafana.example.com/mcp",
        secret_ref="env://GRAFANA_TOKEN",
        status="disabled",
        allowed_operations=["query_metrics"],
        allowed_environments=["prod"],
        data_classification="internal",
        config={"operation_specs": operation_specs},
    )
    assert row.config["adapter_key"] == "mcp"

    with pytest.raises(ConnectorCatalogError, match="host_allowlist_required"):
        await service.create(
            name="grafana-enabled",
            connector_kind="observability",
            transport="mcp",
            endpoint="https://grafana.example.com/mcp",
            secret_ref="env://GRAFANA_TOKEN",
            status="enabled",
            allowed_operations=["query_metrics"],
            allowed_environments=["prod"],
            data_classification="internal",
            config={"operation_specs": operation_specs},
        )

    with pytest.raises(ConnectorCatalogError, match="adapter_key_mismatch"):
        await service.create(
            name="mismatched",
            connector_kind="observability",
            transport="mcp",
            endpoint="https://grafana.example.com/mcp",
            secret_ref=None,
            status="disabled",
            allowed_operations=["query_metrics"],
            allowed_environments=["prod"],
            data_classification="internal",
            config={"adapter_key": "prometheus", "operation_specs": operation_specs},
        )

    with pytest.raises(ConnectorCatalogError, match="adapter_not_registered"):
        await service.create(
            name="missing-native",
            connector_kind="observability",
            transport="native",
            endpoint="https://native.example.com",
            secret_ref=None,
            status="disabled",
            allowed_operations=["query_metrics"],
            allowed_environments=["prod"],
            data_classification="internal",
            config={"adapter_key": "missing.native"},
        )


@pytest.mark.asyncio
async def test_connector_catalog_rejects_unverifiable_write_operations() -> None:
    service = ConnectorCatalogService(
        _FakeDB(),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    with pytest.raises(ConnectorCatalogError, match="operation_spec_invalid"):
        await service.create(
            name="unsafe-deployer",
            connector_kind="cicd",
            transport="mcp",
            endpoint="https://deploy.example.com/mcp",
            secret_ref="env://DEPLOY_MCP_TOKEN",
            status="disabled",
            allowed_operations=["rollback_deployment"],
            allowed_environments=["prod"],
            data_classification="internal",
            config={
                "operation_specs": [
                    {
                        "name": "rollback_deployment",
                        "domain": "cicd",
                        "risk": "destructive",
                        "input_schema": {
                            "type": "object",
                            "properties": {"deployment_id": {"type": "string"}},
                            "required": ["deployment_id"],
                            "additionalProperties": False,
                        },
                        "evidence_types": ["deployment"],
                        "verification_evidence_types": [],
                        "supports_idempotency": True,
                    }
                ]
            },
        )


@pytest.mark.asyncio
async def test_asset_graph_create_binds_scope_and_flushes_before_audit() -> None:
    db = _FakeDB(scalars=[None])
    service = AssetGraphService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    row = await service.create_asset(
        asset_type="service",
        external_key="account-service",
        name="Account Service",
        environment="prod",
    )
    assert row.tenant_id == "tenant-a"
    assert row.workspace_id == "workspace-a"
    assert db.added[0] is row
    assert isinstance(db.added[1], AuditLog)
    assert db.flush_count == 1


@pytest.mark.asyncio
async def test_asset_graph_relation_requires_both_assets_in_same_scope() -> None:
    source = ProductionAsset(
        id="asset-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_type="service",
        external_key="service-a",
        name="Service A",
        created_by="admin-1",
    )
    target = ProductionAsset(
        id="asset-2",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_type="repository",
        external_key="repo-a",
        name="Repo A",
        created_by="admin-1",
    )
    db = _FakeDB(scalars=[source, target, None])
    service = AssetGraphService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    relation = await service.create_relation(
        source_asset_id=source.id,
        target_asset_id=target.id,
        relation_type="repository_for",
    )
    assert isinstance(relation, ProductionAssetRelation)
    assert relation.tenant_id == "tenant-a"
    assert relation.workspace_id == "workspace-a"


@pytest.mark.asyncio
async def test_asset_graph_import_creates_nodes_before_edges_in_one_unit() -> None:
    db = _SequenceDB([[], []])
    service = AssetGraphService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )

    result = await service.import_graph(
        assets=[
            {
                "asset_type": "business_domain",
                "external_key": "payment",
                "name": "支付业务",
                "environment": "prod",
            },
            {
                "asset_type": "service",
                "external_key": "payment-service",
                "name": "Payment Service",
                "environment": "prod",
            },
        ],
        relations=[
            {
                "source_asset_type": "business_domain",
                "source_external_key": "payment",
                "target_asset_type": "service",
                "target_external_key": "payment-service",
                "relation_type": "contains",
            }
        ],
        source="cmdb_import",
    )

    assert result == {
        "created_assets": 2,
        "updated_assets": 0,
        "created_relations": 1,
        "updated_relations": 0,
        "asset_ids": {
            "business_domain:payment": result["asset_ids"]["business_domain:payment"],
            "service:payment-service": result["asset_ids"]["service:payment-service"],
        },
    }
    assert db.flush_count == 2
    assert [type(row) for row in db.added[:3]] == [
        ProductionAsset,
        ProductionAsset,
        ProductionAssetRelation,
    ]
    assert isinstance(db.added[-1], AuditLog)


@pytest.mark.asyncio
async def test_asset_graph_import_rejects_duplicate_nodes_before_writing() -> None:
    db = _SequenceDB([])
    service = AssetGraphService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )

    with pytest.raises(ValueError, match="asset_graph_import_duplicate_asset"):
        await service.import_graph(
            assets=[
                {"asset_type": "service", "external_key": "payments", "name": "A"},
                {"asset_type": "service", "external_key": "payments", "name": "B"},
            ],
            relations=[],
        )
    assert db.added == []
    assert db.flush_count == 0


@pytest.mark.asyncio
async def test_asset_sync_persists_lease_source_lineage_and_authoritative_cleanup() -> None:
    def claimed_run(db: _SyncDB) -> ProductionAssetSyncRun:
        return next(row for row in db.added if isinstance(row, ProductionAssetSyncRun))

    db = _SyncDB(
        scalars=["connector-1", None, None, None, claimed_run],
        execute_values=[[], ["connector-1"], _RowcountResult(2), _RowcountResult(1)],
    )
    service = ProductionAssetSyncService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
        lease_owner="worker-1",
    )
    run = await service.run_sync(
        source_key="cmdb:primary",
        connector_id="connector-1",
        idempotency_key="cmdb-page-42",
        cursor_before=None,
        cursor_after="cursor-42",
        authoritative=True,
        adopt_existing=False,
        assets=[
            {
                "asset_type": "service",
                "external_key": "payment-service",
                "name": "Payment Service",
                "environment": "prod",
            }
        ],
        relations=[],
    )

    asset = next(row for row in db.added if isinstance(row, ProductionAsset))
    assert run.status == "completed"
    assert run.attempt_count == 1
    assert run.cursor_after == "cursor-42"
    assert run.stats["created_assets"] == 1
    assert run.stats["retired_assets"] == 1
    assert run.stats["deleted_relations"] == 2
    assert asset.connector_id == "connector-1"
    assert asset.source_kind == "sync"
    assert asset.source_key == "cmdb:primary"
    assert asset.last_sync_run_id == run.id
    assert asset.last_seen_at is not None
    assert db.commit_count == 2
    assert db.rollback_count == 0


@pytest.mark.asyncio
async def test_asset_sync_reuses_completed_idempotency_record() -> None:
    completed = ProductionAssetSyncRun(
        id="run-1",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        source_key="cmdb:primary",
        status="completed",
        idempotency_key="cmdb-page-42",
        input_hash="placeholder",
        authoritative=False,
        attempt_count=1,
        lease_owner="worker-old",
        lease_expires_at=datetime.now(UTC),
        heartbeat_at=datetime.now(UTC),
        stats={},
        requested_by="admin-1",
        started_at=datetime.now(UTC),
    )
    db = _SyncDB(
        scalars=[completed],
        execute_values=[],
    )
    service = ProductionAssetSyncService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
        lease_owner="worker-1",
    )
    from services.production_intelligence.asset_sync import _input_hash

    completed.input_hash = _input_hash(
        source_key="cmdb:primary",
        connector_id=None,
        cursor_before=None,
        cursor_after=None,
        authoritative=False,
        adopt_existing=False,
        assets=[{"asset_type": "service", "external_key": "service-a", "name": "A"}],
        relations=[],
    )
    reused = await service.run_sync(
        source_key="cmdb:primary",
        connector_id=None,
        idempotency_key="cmdb-page-42",
        cursor_before=None,
        cursor_after=None,
        authoritative=False,
        adopt_existing=False,
        assets=[{"asset_type": "service", "external_key": "service-a", "name": "A"}],
        relations=[],
    )
    assert reused is completed
    assert db.commit_count == 0
    assert db.added == []


@pytest.mark.asyncio
async def test_asset_sync_serializes_sources_and_rechecks_cursor_inside_claim() -> None:
    active = ProductionAssetSyncRun(
        id="run-active",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        source_key="cmdb:primary",
        status="running",
        idempotency_key="page-active",
        input_hash="sha256:active",
        authoritative=False,
        attempt_count=1,
        lease_owner="worker-active",
        lease_expires_at=datetime.now(UTC) + timedelta(minutes=2),
        heartbeat_at=datetime.now(UTC),
        stats={},
        requested_by="admin-1",
        started_at=datetime.now(UTC),
    )
    db = _SyncDB(scalars=[None, active], execute_values=[])
    service = ProductionAssetSyncService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
        lease_owner="worker-2",
    )

    with pytest.raises(AssetSyncError, match="source_already_running"):
        await service.run_sync(
            source_key="cmdb:primary",
            connector_id=None,
            idempotency_key="page-next",
            cursor_before="cursor-1",
            cursor_after="cursor-2",
            authoritative=False,
            adopt_existing=False,
            assets=[{"asset_type": "service", "external_key": "service-b", "name": "B"}],
            relations=[],
        )
    assert db.commit_count == 0

    with pytest.raises(AssetSyncError, match="cursor_not_advanced"):
        await service.run_sync(
            source_key="cmdb:primary",
            connector_id=None,
            idempotency_key="page-loop",
            cursor_before="cursor-1",
            cursor_after="cursor-1",
            authoritative=False,
            adopt_existing=False,
            assets=[{"asset_type": "service", "external_key": "service-c", "name": "C"}],
            relations=[],
        )


@pytest.mark.asyncio
async def test_config_policy_requires_closed_bounded_schema_and_stable_rules() -> None:
    asset = ProductionAsset(
        id="config-asset",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_type="config",
        external_key="campaign-config",
        name="Campaign Config",
        environment="prod",
        created_by="admin-1",
    )
    service = ConfigIntelligenceService(
        _FakeDB(scalars=[asset]),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    with pytest.raises(ConfigIntelligenceError, match="closed_object_required"):
        await service.create_policy(
            asset_id=asset.id,
            schema={"type": "object", "properties": {}},
        )

    service = ConfigIntelligenceService(
        _FakeDB(scalars=[asset]),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    with pytest.raises(ConfigIntelligenceError, match="rule_id_required"):
        await service.create_policy(
            asset_id=asset.id,
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            history_rules=[
                {
                    "path": "/replicas",
                    "max_change_ratio": 0.5,
                    "min_samples": 5,
                }
            ],
        )

    db = _FakeDB(scalars=[asset, 2])
    service = ConfigIntelligenceService(
        db,  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    policy = await service.create_policy(
        asset_id=asset.id,
        schema={
            "type": "object",
            "properties": {"replicas": {"type": "integer", "minimum": 1}},
            "required": ["replicas"],
            "additionalProperties": False,
        },
        history_rules=[
            {
                "id": "replica-history",
                "path": "/replicas",
                "max_change_ratio": 0.5,
                "min_samples": 5,
            }
        ],
    )
    assert policy.version == 3
    assert policy.history_rules[0]["min_samples"] == 5


@pytest.mark.asyncio
async def test_config_snapshot_rejects_cross_scope_response_and_secret_source_ref() -> None:
    asset = ProductionAsset(
        id="config-asset",
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        asset_type="config",
        external_key="campaign-config",
        name="Campaign Config",
        environment="prod",
        created_by="admin-1",
    )
    service = ConfigIntelligenceService(
        _FakeDB(scalars=[asset, None]),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    with pytest.raises(ConfigIntelligenceError, match="response_scope_mismatch"):
        await service.record_snapshot(
            asset_id=asset.id,
            environment="prod",
            version_ref="v1",
            source_ref="config://campaign/v1",
            content={"replicas": 3},
            response_id="response-other-scope",
        )

    service = ConfigIntelligenceService(
        _FakeDB(scalars=[asset]),  # type: ignore[arg-type]
        ProductionScope("tenant-a", "workspace-a", "admin-1"),
    )
    with pytest.raises(ConfigIntelligenceError, match="source_ref_invalid"):
        await service.record_snapshot(
            asset_id=asset.id,
            environment="prod",
            version_ref="v1",
            source_ref="https://config.example.com/v1?token=secret",
            content={"replicas": 3},
        )


def test_production_intelligence_routes_and_migration_are_registered() -> None:
    paths = {str(getattr(route, "path", "")) for route in production_router.routes}
    assert "/production/assets" in paths
    assert "/production/asset-graph" in paths
    assert "/production/asset-graph/import" in paths
    assert "/production/asset-graph/sync" in paths
    assert "/production/asset-sync-runs" in paths
    assert "/production/connectors" in paths
    assert "/production/capability-policy" in paths
    assert "/production/config-assets/{asset_id}/policies" in paths
    assert "/production/config-assets/{asset_id}/snapshots" in paths
    assert "/production/config-assets/{asset_id}/validate" in paths
    assert "/production/config-assets/{asset_id}/validation-runs" in paths
    main_source = (ROOT / "gateway/api_gateway/main.py").read_text(encoding="utf-8")
    assert "production_intelligence.router" in main_source

    migration = (ROOT / "alembic/versions/r0029_production_intelligence_foundation.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "r0028_reconcile_legacy_approval_class"' in migration
    for table in (
        "enterprise_connectors",
        "production_assets",
        "production_asset_relations",
        "production_evidence",
    ):
        assert table in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration

    config_migration = (ROOT / "alembic/versions/r0030_config_intelligence.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "r0029_production_intelligence_foundation"' in config_migration
    for table in (
        "production_config_policies",
        "production_config_snapshots",
        "production_config_validation_runs",
    ):
        assert table in config_migration
    assert "ENABLE ROW LEVEL SECURITY" in config_migration

    sync_migration = (ROOT / "alembic/versions/r0031_production_asset_sync_runtime.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "r0030_config_intelligence"' in sync_migration
    assert "production_asset_sync_runs" in sync_migration
    assert "last_sync_run_id" in sync_migration
    assert "ENABLE ROW LEVEL SECURITY" in sync_migration

    approval_migration = (
        ROOT / "alembic/versions/r0032_four_eye_production_approvals.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "r0031_production_asset_sync_runtime"' in approval_migration
    assert "required_approvals" in approval_migration
    assert "approval_decisions" in approval_migration
    assert "ck_response_approval_required_count" in approval_migration
    config_invariants_migration = (
        ROOT / "alembic/versions/r0033_config_intelligence_invariants.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "r0032_four_eye_production_approvals"' in config_invariants_migration
    assert "uq_production_config_policy_published_asset" in config_invariants_migration
    assert "uq_production_config_snapshot_current_asset_environment" in config_invariants_migration
    response_aux_source = (ROOT / "gateway/api_gateway/routers/response_aux.py").read_text(
        encoding="utf-8"
    )
    assert "/response-approvals/pending" in response_aux_source
    assert '"pending_secondary"' in response_aux_source
