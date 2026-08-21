"""受治理 Connector 执行网关。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import uuid
from datetime import UTC
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.contracts import (
    ConnectorEvidence,
    ConnectorExecutionContext,
    ConnectorOperationSpec,
    ConnectorResult,
)
from connectors.registry import ConnectorRegistry, connector_registry
from connectors.runtime import ConnectorRuntimeControl, ConnectorRuntimePolicyError
from infra.observability.logger import get_logger
from infra.observability.metrics import (
    CONNECTOR_EVIDENCE_COUNT,
    CONNECTOR_EXECUTION_DURATION,
    CONNECTOR_EXECUTIONS_TOTAL,
    CONNECTOR_RUNTIME_DECISIONS_TOTAL,
)
from infra.storage.models import (
    EnterpriseConnector,
    ProductionAsset,
    ProductionEvidence,
    ResponseRecord,
)
from services.production_intelligence.audit import append_audit, mask_sensitive
from services.production_intelligence.policy import CapabilityPolicy, PolicyDecision

logger = get_logger(__name__)


class ConnectorGatewayError(RuntimeError):
    def __init__(self, message: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


def _matches_type(value: Any, expected: str) -> bool:
    if expected == "null":
        return value is None
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, int | float) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    return False


def _validate_value(value: Any, schema: dict[str, Any], *, path: str) -> None:
    expected = schema.get("type")
    expected_types = [expected] if isinstance(expected, str) else list(expected or [])
    if expected_types and not any(_matches_type(value, item) for item in expected_types):
        raise ConnectorGatewayError(f"connector_argument_type_invalid:{path}")
    if value is None:
        return
    if isinstance(value, str):
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise ConnectorGatewayError(f"connector_argument_too_short:{path}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise ConnectorGatewayError(f"connector_argument_too_long:{path}")
        if schema.get("enum") and value not in schema["enum"]:
            raise ConnectorGatewayError(f"connector_argument_enum_invalid:{path}")
    if isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ConnectorGatewayError(f"connector_argument_below_minimum:{path}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ConnectorGatewayError(f"connector_argument_above_maximum:{path}")
    if isinstance(value, list):
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise ConnectorGatewayError(f"connector_argument_too_many_items:{path}")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_value(item, item_schema, path=f"{path}[{index}]")
    if isinstance(value, dict):
        _validate_arguments(value, schema, path=path)


def _validate_arguments(
    arguments: dict[str, Any], schema: dict[str, Any], *, path: str = "arguments"
) -> None:
    properties = dict(schema.get("properties") or {})
    required = {str(item) for item in schema.get("required") or []}
    missing = sorted(name for name in required if name not in arguments)
    if missing:
        raise ConnectorGatewayError(f"connector_arguments_missing:{','.join(missing)}")
    unknown = set(arguments) - set(properties)
    if unknown and schema.get("additionalProperties", False) is False:
        raise ConnectorGatewayError(f"connector_arguments_unknown:{','.join(sorted(unknown))}")
    for name, value in arguments.items():
        property_schema = properties.get(name)
        if isinstance(property_schema, dict):
            _validate_value(value, property_schema, path=f"{path}.{name}")


def _content_hash(evidence: ConnectorEvidence) -> str:
    canonical = json.dumps(
        {
            "evidence_type": evidence.evidence_type,
            "source_ref": evidence.source_ref,
            "title": evidence.title,
            "summary": evidence.summary,
            "payload": mask_sensitive(evidence.payload),
        },
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _safe_source_ref(value: str) -> str:
    source_ref = value.strip()
    if not source_ref or len(source_ref) > 2048:
        raise ConnectorGatewayError("connector_evidence_source_ref_invalid")
    lowered = source_ref.lower()
    if any(marker in lowered for marker in ("token=", "password=", "api_key=", "secret=")):
        raise ConnectorGatewayError("connector_evidence_source_ref_contains_secret")
    return source_ref


def _mask_policy_text(value: str, *, data_mode: str) -> str:
    if data_mode != "masked":
        return value
    masked = re.sub(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", "***@***", value)
    return re.sub(r"(?<!\d)1[3-9]\d{9}(?!\d)", "***********", masked)


def _apply_policy_data_mode(value: Any, *, data_mode: str) -> Any:
    sensitive_markers = {
        "email",
        "phone",
        "mobile",
        "customer_name",
        "user_name",
        "real_name",
        "id_card",
        "address",
    }
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).lower()
            if data_mode == "masked" and any(
                marker in normalized_key for marker in sensitive_markers
            ):
                result[str(key)] = "***"
                continue
            if data_mode in {"summary", "aggregate"} and isinstance(item, dict | list):
                result[f"{key}_count"] = len(item)
                continue
            result[str(key)] = _apply_policy_data_mode(item, data_mode=data_mode)
        return mask_sensitive(result)
    if isinstance(value, list):
        if data_mode in {"summary", "aggregate"}:
            return {"count": len(value)}
        return [_apply_policy_data_mode(item, data_mode=data_mode) for item in value]
    if isinstance(value, str):
        return _mask_policy_text(value, data_mode=data_mode)
    return value


class GovernedConnectorGateway:
    """模型只能通过已持久化目录与已注册适配器调用外部系统。"""

    def __init__(
        self,
        *,
        registry: ConnectorRegistry | None = None,
        policy: CapabilityPolicy | None = None,
        runtime_control: ConnectorRuntimeControl | None = None,
    ) -> None:
        self.registry = registry or connector_registry
        self.policy = policy or CapabilityPolicy()
        self.runtime_control = runtime_control or ConnectorRuntimeControl()

    @staticmethod
    def _scope_filter(model: Any, context: ConnectorExecutionContext) -> tuple[Any, Any]:
        return (
            model.tenant_id == context.tenant_id,
            model.workspace_id == context.workspace_id,
        )

    async def _load_connector(
        self, db: AsyncSession, connector_id: str, context: ConnectorExecutionContext
    ) -> EnterpriseConnector:
        row = await db.scalar(
            select(EnterpriseConnector).where(
                EnterpriseConnector.id == connector_id,
                *self._scope_filter(EnterpriseConnector, context),
            )
        )
        if row is None:
            raise ConnectorGatewayError("connector_not_found")
        if row.status != "enabled":
            raise ConnectorGatewayError("connector_not_enabled")
        return row

    async def _validate_response_scope(
        self, db: AsyncSession, context: ConnectorExecutionContext
    ) -> None:
        if not context.response_id:
            return
        response = await db.scalar(
            select(ResponseRecord.id).where(
                ResponseRecord.id == context.response_id,
                ResponseRecord.tenant_id == context.tenant_id,
                ResponseRecord.workspace_id == context.workspace_id,
            )
        )
        if response is None:
            raise ConnectorGatewayError("response_scope_mismatch")

    async def _validate_evidence_assets(
        self,
        db: AsyncSession,
        evidence: tuple[ConnectorEvidence, ...],
        context: ConnectorExecutionContext,
    ) -> None:
        asset_ids = {item.asset_id for item in evidence if item.asset_id}
        if not asset_ids:
            return
        result = await db.execute(
            select(ProductionAsset.id).where(
                ProductionAsset.id.in_(asset_ids),
                ProductionAsset.tenant_id == context.tenant_id,
                ProductionAsset.workspace_id == context.workspace_id,
            )
        )
        visible = set(result.scalars().all())
        if visible != asset_ids:
            raise ConnectorGatewayError("evidence_asset_scope_mismatch")

    @staticmethod
    def _operation_spec(
        adapter, operation: str, connector_config: dict[str, Any]
    ) -> ConnectorOperationSpec:
        dynamic_resolver = getattr(adapter, "operation_spec", None)
        if callable(dynamic_resolver):
            spec = dynamic_resolver(operation, connector_config)
            if spec is not None:
                return spec
        specs = {item.name: item for item in adapter.operations()}
        spec = specs.get(operation)
        if spec is None:
            raise ConnectorGatewayError("connector_operation_not_supported")
        return spec

    async def _prepare_completed_result(
        self,
        db: AsyncSession,
        *,
        connector: EnterpriseConnector,
        spec: ConnectorOperationSpec,
        decision: PolicyDecision,
        result: ConnectorResult,
        context: ConnectorExecutionContext,
    ) -> tuple[dict[str, Any], dict[str, Any], tuple[ConnectorEvidence, ...], int]:
        """在标记运行成功前完成输出收敛、证据校验和持久化准备。"""

        sanitized_data = _apply_policy_data_mode(
            dict(result.data or {}), data_mode=decision.data_mode
        )
        sanitized_metadata = _apply_policy_data_mode(
            dict(result.metadata or {}), data_mode=decision.data_mode
        )
        sanitized_evidence: list[ConnectorEvidence] = []
        for item in result.evidence:
            observed_at = item.observed_at
            if observed_at.tzinfo is None:
                observed_at = observed_at.replace(tzinfo=UTC)
            expires_at = item.expires_at
            if expires_at is not None and expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            sanitized_evidence.append(
                ConnectorEvidence(
                    evidence_type=item.evidence_type,
                    source_ref=_safe_source_ref(item.source_ref),
                    title=_mask_policy_text(item.title.strip()[:255], data_mode=decision.data_mode),
                    summary=_mask_policy_text(item.summary.strip(), data_mode=decision.data_mode),
                    observed_at=observed_at.astimezone(UTC),
                    source_kind=item.source_kind or connector.connector_kind,
                    asset_id=item.asset_id,
                    environment=item.environment or context.environment,
                    authority=item.authority,
                    permission_class=item.permission_class,
                    confidence=float(item.confidence),
                    payload=_apply_policy_data_mode(
                        dict(item.payload or {}), data_mode=decision.data_mode
                    ),
                    expires_at=expires_at.astimezone(UTC) if expires_at is not None else None,
                )
            )
        encoded = json.dumps(
            {
                "data": sanitized_data,
                "metadata": sanitized_metadata,
                "evidence": [
                    {
                        "evidence_type": item.evidence_type,
                        "source_ref": item.source_ref,
                        "title": item.title,
                        "summary": item.summary,
                        "payload": item.payload,
                    }
                    for item in sanitized_evidence
                ],
            },
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        if len(encoded) > max(1024, min(int(spec.max_output_bytes), 1_048_576)):
            raise ConnectorGatewayError("connector_output_too_large")

        normalized_evidence = tuple(sanitized_evidence)
        await self._validate_evidence_assets(db, normalized_evidence, context)
        persisted_count = 0
        for item in normalized_evidence:
            if spec.evidence_types and item.evidence_type not in set(spec.evidence_types):
                raise ConnectorGatewayError("connector_evidence_type_not_declared")
            if not 0.0 <= float(item.confidence) <= 1.0:
                raise ConnectorGatewayError("connector_evidence_confidence_invalid")
            if not item.title or not item.summary:
                raise ConnectorGatewayError("connector_evidence_content_required")
            content_hash = _content_hash(item)
            if context.response_id:
                duplicate = await db.scalar(
                    select(ProductionEvidence.id).where(
                        ProductionEvidence.tenant_id == context.tenant_id,
                        ProductionEvidence.workspace_id == context.workspace_id,
                        ProductionEvidence.response_id == context.response_id,
                        ProductionEvidence.connector_id == connector.id,
                        ProductionEvidence.source_ref == item.source_ref,
                        ProductionEvidence.content_hash == content_hash,
                    )
                )
                if duplicate is not None:
                    continue
            db.add(
                ProductionEvidence(
                    id=str(uuid.uuid4()),
                    tenant_id=context.tenant_id,
                    workspace_id=context.workspace_id,
                    response_id=context.response_id,
                    connector_id=connector.id,
                    asset_id=item.asset_id,
                    evidence_type=item.evidence_type,
                    source_kind=item.source_kind or connector.connector_kind,
                    source_ref=item.source_ref,
                    environment=item.environment or context.environment,
                    title=item.title.strip()[:255],
                    summary=item.summary.strip(),
                    authority=item.authority,
                    permission_class=item.permission_class,
                    confidence=float(item.confidence),
                    content_hash=content_hash,
                    observed_at=item.observed_at,
                    expires_at=item.expires_at,
                    payload=dict(item.payload or {}),
                )
            )
            persisted_count += 1
        return sanitized_data, sanitized_metadata, normalized_evidence, persisted_count

    async def execute(
        self,
        db: AsyncSession,
        *,
        connector_id: str,
        operation: str,
        arguments: dict[str, Any],
        context: ConnectorExecutionContext,
    ) -> ConnectorResult:
        """执行并确保所有显式拒绝或失败都进入审计链。"""

        try:
            return await self._execute_governed(
                db,
                connector_id=connector_id,
                operation=operation,
                arguments=arguments,
                context=context,
            )
        except ConnectorGatewayError as exc:
            try:
                append_audit(
                    db,
                    user_id=context.user_id,
                    action="enterprise_connector.execution_failed",
                    resource_type="enterprise_connector",
                    resource_id=connector_id,
                    payload={
                        "operation": operation,
                        "environment": context.environment,
                        "response_id": context.response_id,
                        "reason": str(exc)[:512],
                        "outcome_unknown": exc.outcome_unknown,
                        "trace_id": context.trace_id,
                    },
                )
                await db.flush()
            except Exception as audit_exc:  # noqa: BLE001
                logger.error(
                    "Connector failure audit persistence failed",
                    reason=str(exc)[:128],
                    error=type(audit_exc).__name__,
                )
            raise

    async def _execute_governed(
        self,
        db: AsyncSession,
        *,
        connector_id: str,
        operation: str,
        arguments: dict[str, Any],
        context: ConnectorExecutionContext,
    ) -> ConnectorResult:
        connector = await self._load_connector(db, connector_id, context)
        if operation not in set(connector.allowed_operations or []):
            raise ConnectorGatewayError("connector_operation_not_allowed")
        if connector.allowed_environments and context.environment not in set(
            connector.allowed_environments
        ):
            raise ConnectorGatewayError("connector_environment_not_allowed")

        adapter_key = str((connector.config or {}).get("adapter_key") or connector.connector_kind)
        try:
            adapter = self.registry.require(adapter_key)
        except KeyError as exc:
            raise ConnectorGatewayError(str(exc)) from exc
        spec = self._operation_spec(adapter, operation, dict(connector.config or {}))
        decision = self.policy.authorize(
            role=context.role,
            is_superuser=context.is_superuser,
            domain=spec.domain,
            risk=spec.risk,
            classification=connector.data_classification,
            environment=context.environment,
        )
        if not decision.allowed:
            raise ConnectorGatewayError(f"connector_policy_denied:{decision.reason}")
        if decision.approval_required and not context.approved:
            raise ConnectorGatewayError("connector_operation_requires_durable_approval")
        granted_permissions = set(context.permissions)
        granted_permissions.add(
            f"role:{self.policy.normalize_role(context.role, is_superuser=context.is_superuser)}"
        )
        if (
            spec.required_permissions
            and not context.is_superuser
            and not set(spec.required_permissions).issubset(granted_permissions)
        ):
            raise ConnectorGatewayError("connector_required_permission_missing")
        if spec.risk != "read" and (not spec.supports_idempotency or not context.idempotency_key):
            raise ConnectorGatewayError("connector_write_idempotency_required")

        _validate_arguments(arguments, spec.input_schema)
        await self._validate_response_scope(db, context)
        try:
            admission, runtime_policy = await self.runtime_control.acquire(
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                connector_id=connector.id,
                risk=spec.risk,
                timeout_seconds=float(spec.timeout_seconds),
                config=dict(connector.config or {}),
                idempotency_key=context.idempotency_key,
            )
        except ConnectorRuntimePolicyError as exc:
            raise ConnectorGatewayError(str(exc)) from exc
        CONNECTOR_RUNTIME_DECISIONS_TOTAL.labels(
            risk=spec.risk,
            outcome=(
                "degraded" if admission.degraded else "admitted" if admission.admitted else "denied"
            ),
            reason=admission.reason,
        ).inc()
        if not admission.admitted:
            append_audit(
                db,
                user_id=context.user_id,
                action="enterprise_connector.runtime_denied",
                resource_type="enterprise_connector",
                resource_id=connector.id,
                payload={
                    "operation": operation,
                    "risk": spec.risk,
                    "environment": context.environment,
                    "response_id": context.response_id,
                    "reason": admission.reason,
                    "retry_after_ms": admission.retry_after_ms,
                    "trace_id": context.trace_id,
                },
            )
            await db.flush()
            raise ConnectorGatewayError(
                f"connector_runtime_denied:{admission.reason}:{admission.retry_after_ms}"
            )
        runtime_config = {
            **dict(connector.config or {}),
            "endpoint": connector.endpoint,
            "_policy_data_mode": decision.data_mode,
            "_connector_id": connector.id,
        }
        metric_labels = {
            "connector_kind": connector.connector_kind,
            "transport": connector.transport,
            "domain": spec.domain,
        }
        started_at = time.monotonic()
        try:
            async with asyncio.timeout(max(0.1, min(float(spec.timeout_seconds), 120.0))):
                result = await adapter.execute(
                    operation,
                    dict(arguments),
                    context=context,
                    connector_config=runtime_config,
                    secret_ref=connector.secret_ref,
                )
        except TimeoutError as exc:
            await self.runtime_control.complete(
                admission=admission,
                policy=runtime_policy,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                connector_id=connector.id,
                success=False,
            )
            CONNECTOR_EXECUTIONS_TOTAL.labels(
                **metric_labels, risk=spec.risk, status="timeout"
            ).inc()
            CONNECTOR_EXECUTION_DURATION.labels(**metric_labels, status="timeout").observe(
                time.monotonic() - started_at
            )
            raise ConnectorGatewayError(
                "connector_operation_timeout", outcome_unknown=spec.risk != "read"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            await self.runtime_control.complete(
                admission=admission,
                policy=runtime_policy,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                connector_id=connector.id,
                success=False,
            )
            CONNECTOR_EXECUTIONS_TOTAL.labels(**metric_labels, risk=spec.risk, status="error").inc()
            CONNECTOR_EXECUTION_DURATION.labels(**metric_labels, status="error").observe(
                time.monotonic() - started_at
            )
            raise ConnectorGatewayError(
                "connector_adapter_error", outcome_unknown=spec.risk != "read"
            ) from exc
        if result.status != "completed":
            await self.runtime_control.complete(
                admission=admission,
                policy=runtime_policy,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                connector_id=connector.id,
                success=False,
            )
            CONNECTOR_EXECUTIONS_TOTAL.labels(
                **metric_labels, risk=spec.risk, status="failed"
            ).inc()
            CONNECTOR_EXECUTION_DURATION.labels(**metric_labels, status="failed").observe(
                time.monotonic() - started_at
            )
            raise ConnectorGatewayError(
                f"connector_operation_failed:{result.status}",
                outcome_unknown=spec.risk != "read",
            )
        try:
            (
                sanitized_data,
                sanitized_metadata,
                normalized_evidence,
                persisted_count,
            ) = await self._prepare_completed_result(
                db,
                connector=connector,
                spec=spec,
                decision=decision,
                result=result,
                context=context,
            )
            append_audit(
                db,
                user_id=context.user_id,
                action="enterprise_connector.executed",
                resource_type="enterprise_connector",
                resource_id=connector.id,
                payload={
                    "operation": operation,
                    "risk": spec.risk,
                    "environment": context.environment,
                    "response_id": context.response_id,
                    "arguments": mask_sensitive(arguments),
                    "evidence_count": len(normalized_evidence),
                    "evidence_persisted_count": persisted_count,
                    "trace_id": context.trace_id,
                    "runtime_control": {
                        "state": admission.control_state,
                        "degraded": admission.degraded,
                    },
                },
            )
            await db.flush()
        except ConnectorGatewayError as exc:
            await self.runtime_control.complete(
                admission=admission,
                policy=runtime_policy,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                connector_id=connector.id,
                success=False,
            )
            CONNECTOR_EXECUTIONS_TOTAL.labels(
                **metric_labels, risk=spec.risk, status="invalid_output"
            ).inc()
            CONNECTOR_EXECUTION_DURATION.labels(**metric_labels, status="invalid_output").observe(
                time.monotonic() - started_at
            )
            if spec.risk != "read" and not exc.outcome_unknown:
                raise ConnectorGatewayError(str(exc), outcome_unknown=True) from exc
            raise
        except Exception as exc:  # noqa: BLE001
            await self.runtime_control.complete(
                admission=admission,
                policy=runtime_policy,
                tenant_id=context.tenant_id,
                workspace_id=context.workspace_id,
                connector_id=connector.id,
                success=False,
            )
            CONNECTOR_EXECUTIONS_TOTAL.labels(
                **metric_labels, risk=spec.risk, status="postprocess_error"
            ).inc()
            CONNECTOR_EXECUTION_DURATION.labels(
                **metric_labels, status="postprocess_error"
            ).observe(time.monotonic() - started_at)
            raise ConnectorGatewayError(
                "connector_postprocessing_error", outcome_unknown=spec.risk != "read"
            ) from exc

        runtime_outcome_recorded = await self.runtime_control.complete(
            admission=admission,
            policy=runtime_policy,
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            connector_id=connector.id,
            success=True,
        )
        CONNECTOR_EXECUTIONS_TOTAL.labels(**metric_labels, risk=spec.risk, status="completed").inc()
        CONNECTOR_EXECUTION_DURATION.labels(**metric_labels, status="completed").observe(
            time.monotonic() - started_at
        )
        CONNECTOR_EVIDENCE_COUNT.labels(
            connector_kind=connector.connector_kind, domain=spec.domain
        ).observe(len(result.evidence))
        return ConnectorResult(
            status="completed",
            data=sanitized_data,
            evidence=normalized_evidence,
            metadata={
                **sanitized_metadata,
                "policy": decision.to_dict(),
                "runtime_control": {
                    "state": admission.control_state,
                    "degraded": admission.degraded,
                    "outcome_recorded": runtime_outcome_recorded,
                },
            },
        )
