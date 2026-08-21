"""受治理生产操作的发现、参数绑定与审批后执行。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.contracts import ConnectorExecutionContext, ConnectorOperationSpec
from connectors.gateway import ConnectorGatewayError, GovernedConnectorGateway
from connectors.registry import connector_registry
from infra.storage.models import EnterpriseConnector, ProductionAsset, User
from services.production_intelligence.asset_graph import ProductionScope
from services.production_intelligence.audit import mask_sensitive
from services.production_intelligence.policy import CapabilityPolicy

_ACTION_PREFIX = "production-action-v1"


class ProductionActionError(ValueError):
    """动作引用、范围或声明不满足安全约束。"""

    def __init__(self, message: str, *, outcome_unknown: bool = False) -> None:
        super().__init__(message)
        self.outcome_unknown = outcome_unknown


@dataclass(frozen=True, slots=True)
class ProductionActionReference:
    connector_id: str
    operation: str
    asset_id: str
    environment: str


def make_action_ref(*, connector_id: str, operation: str, asset_id: str, environment: str) -> str:
    """动作引用只标识已声明目录项，不携带身份、凭据或任意参数。"""

    parts = (_ACTION_PREFIX, connector_id, operation, asset_id or "none", environment)
    if any(not part or ":" in part for part in parts):
        raise ProductionActionError("production_action_reference_invalid")
    return ":".join(parts)


def parse_action_ref(value: str) -> ProductionActionReference:
    parts = str(value or "").split(":")
    if len(parts) != 5 or parts[0] != _ACTION_PREFIX:
        raise ProductionActionError("production_action_reference_invalid")
    _, connector_id, operation, asset_id, environment = parts
    if not connector_id or not operation or not environment:
        raise ProductionActionError("production_action_reference_invalid")
    return ProductionActionReference(
        connector_id=connector_id,
        operation=operation,
        asset_id="" if asset_id == "none" else asset_id,
        environment=environment,
    )


def operation_spec(connector: EnterpriseConnector, operation: str) -> ConnectorOperationSpec | None:
    adapter_key = str((connector.config or {}).get("adapter_key") or connector.connector_kind)
    adapter = connector_registry.get(adapter_key)
    if adapter is None:
        return None
    dynamic = getattr(adapter, "operation_spec", None)
    if callable(dynamic):
        spec = dynamic(operation, dict(connector.config or {}))
        if spec is not None:
            return spec
    return next((item for item in adapter.operations() if item.name == operation), None)


def bind_operation_arguments(
    schema: dict[str, Any],
    *,
    query: str,
    environment: str,
    asset: ProductionAsset | None,
    connector: EnterpriseConnector,
    operation: str,
) -> dict[str, Any] | None:
    """仅从平台可信资产、连接器声明和用户原始请求构造写操作参数。"""

    properties = dict(schema.get("properties") or {})
    required = {str(item) for item in schema.get("required") or []}
    declared = dict((connector.config or {}).get("operation_bindings") or {}).get(operation, {})
    declared_bindings = dict(declared) if isinstance(declared, dict) else {}
    bindings: dict[str, Any] = {
        "query": query,
        "reason": query,
        "justification": query,
        "environment": environment,
        "env": environment,
        "asset_id": getattr(asset, "id", None),
        "service": getattr(asset, "external_key", None) or getattr(asset, "name", None),
        "service_name": getattr(asset, "name", None),
        "resource": getattr(asset, "external_key", None) or getattr(asset, "name", None),
        "target": getattr(asset, "external_key", None) or getattr(asset, "name", None),
        "deployment_id": getattr(asset, "external_key", None),
        "config_key": getattr(asset, "external_key", None),
        **declared_bindings,
    }
    arguments: dict[str, Any] = {}
    for name, property_schema in properties.items():
        value = bindings.get(name)
        if value is None and isinstance(property_schema, dict) and "default" in property_schema:
            value = property_schema["default"]
        if value is not None:
            arguments[name] = value
    if required - set(arguments):
        return None
    return arguments


def _role_has_permissions(spec: ConnectorOperationSpec, *, role: str, is_superuser: bool) -> bool:
    if is_superuser or not spec.required_permissions:
        return True
    normalized = CapabilityPolicy.normalize_role(role, is_superuser=is_superuser)
    return set(spec.required_permissions).issubset({f"role:{normalized}"})


async def discover_production_actions(
    db: AsyncSession,
    *,
    scope: ProductionScope,
    user: User,
    query: str,
    assets: list[ProductionAsset],
    limit: int = 12,
) -> list[dict[str, Any]]:
    """只公开当前角色可申请审批且参数可由平台完整绑定的动作。"""

    rows = await db.execute(
        select(EnterpriseConnector).where(
            EnterpriseConnector.tenant_id == scope.tenant_id,
            EnterpriseConnector.workspace_id == scope.workspace_id,
            EnterpriseConnector.status == "enabled",
        )
    )
    connectors = list(rows.scalars().all())
    policy = CapabilityPolicy()
    catalog: list[dict[str, Any]] = []
    candidate_assets: list[ProductionAsset | None] = list(assets[:8]) or [None]
    for connector in connectors:
        for asset in candidate_assets:
            environment = str(getattr(asset, "environment", None) or "shared")
            if connector.allowed_environments and environment not in set(
                connector.allowed_environments
            ):
                continue
            for operation in connector.allowed_operations or []:
                spec = operation_spec(connector, str(operation))
                if (
                    spec is None
                    or spec.risk == "read"
                    or not spec.evidence_types
                    or not spec.verification_evidence_types
                    or not spec.supports_idempotency
                ):
                    continue
                decision = policy.authorize(
                    role=str(user.role or "user"),
                    is_superuser=bool(user.is_superuser),
                    domain=spec.domain,
                    risk=spec.risk,
                    classification=connector.data_classification,
                    environment=environment,
                )
                if not decision.allowed or not decision.approval_required:
                    continue
                if not _role_has_permissions(
                    spec,
                    role=str(user.role or "user"),
                    is_superuser=bool(user.is_superuser),
                ):
                    continue
                arguments = bind_operation_arguments(
                    spec.input_schema,
                    query=query,
                    environment=environment,
                    asset=asset,
                    connector=connector,
                    operation=spec.name,
                )
                if arguments is None:
                    continue
                catalog.append(
                    {
                        "action_ref": make_action_ref(
                            connector_id=connector.id,
                            operation=spec.name,
                            asset_id=str(getattr(asset, "id", None) or ""),
                            environment=environment,
                        ),
                        "label": spec.description[:255],
                        "connector_name": connector.name,
                        "operation": spec.name,
                        "risk": spec.risk,
                        "environment": environment,
                        "asset_name": str(getattr(asset, "name", None) or "共享资源"),
                        "argument_keys": sorted(arguments),
                        "verification_evidence_types": list(spec.verification_evidence_types),
                        "approval_required": True,
                    }
                )
                if len(catalog) >= max(1, min(limit, 24)):
                    return catalog
    return catalog


async def execute_production_action(
    db: AsyncSession,
    *,
    scope: ProductionScope,
    response_id: str,
    user: User,
    action_ref: str,
    query: str,
    trace_id: str,
    gateway: GovernedConnectorGateway | None = None,
) -> dict[str, Any]:
    """仅供 Responses 持久审批恢复路径调用，执行后强制检查验证证据。"""

    reference = parse_action_ref(action_ref)
    connector = await db.scalar(
        select(EnterpriseConnector).where(
            EnterpriseConnector.id == reference.connector_id,
            EnterpriseConnector.tenant_id == scope.tenant_id,
            EnterpriseConnector.workspace_id == scope.workspace_id,
            EnterpriseConnector.status == "enabled",
        )
    )
    if connector is None:
        raise ProductionActionError("production_action_connector_not_found")
    if reference.operation not in set(connector.allowed_operations or []):
        raise ProductionActionError("production_action_operation_not_allowed")
    asset = None
    if reference.asset_id:
        asset = await db.scalar(
            select(ProductionAsset).where(
                ProductionAsset.id == reference.asset_id,
                ProductionAsset.tenant_id == scope.tenant_id,
                ProductionAsset.workspace_id == scope.workspace_id,
                ProductionAsset.status == "active",
            )
        )
        if asset is None:
            raise ProductionActionError("production_action_asset_not_found")
        if asset.environment != reference.environment:
            raise ProductionActionError("production_action_environment_mismatch")
    spec = operation_spec(connector, reference.operation)
    if (
        spec is None
        or spec.risk == "read"
        or not spec.evidence_types
        or not spec.verification_evidence_types
        or not spec.supports_idempotency
    ):
        raise ProductionActionError("production_action_write_spec_required")
    arguments = bind_operation_arguments(
        spec.input_schema,
        query=query,
        environment=reference.environment,
        asset=asset,
        connector=connector,
        operation=spec.name,
    )
    if arguments is None:
        raise ProductionActionError("production_action_arguments_unresolvable")
    try:
        stable_action_key = hashlib.sha256(action_ref.encode("utf-8")).hexdigest()[:32]
        action_idempotency_key = f"production-action:{response_id}:{stable_action_key}"
        result = await (gateway or GovernedConnectorGateway()).execute(
            db,
            connector_id=connector.id,
            operation=spec.name,
            arguments=arguments,
            context=ConnectorExecutionContext(
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                user_id=user.id,
                response_id=response_id,
                role=str(user.role or "user"),
                is_superuser=bool(user.is_superuser),
                environment=reference.environment,
                trace_id=trace_id,
                approved=True,
                idempotency_key=action_idempotency_key,
            ),
        )
    except ConnectorGatewayError as exc:
        raise ProductionActionError(str(exc), outcome_unknown=exc.outcome_unknown) from exc

    evidence = [
        {
            "evidence_type": item.evidence_type,
            "source_ref": item.source_ref,
            "asset_id": item.asset_id,
            "environment": item.environment,
            "title": item.title,
            "summary": item.summary,
            "observed_at": item.observed_at.isoformat(),
            "confidence": item.confidence,
            "verification": mask_sensitive(dict(item.payload or {})),
        }
        for item in result.evidence[:50]
    ]
    verification_types = set(spec.verification_evidence_types)
    verified_items = []
    for item in result.evidence:
        payload = dict(item.payload or {})
        nested = payload.get("verification")
        verification = dict(nested) if isinstance(nested, dict) else payload
        status = str(
            verification.get("status") or verification.get("verification_status") or ""
        ).lower()
        verified_key = str(
            verification.get("idempotency_key") or verification.get("action_idempotency_key") or ""
        )
        if (
            item.evidence_type in verification_types
            and item.environment == reference.environment
            and (not reference.asset_id or item.asset_id == reference.asset_id)
            and status in {"verified", "passed"}
            and verified_key == action_idempotency_key
        ):
            verified_items.append(item)
    verified = bool(verified_items)
    return {
        "status": "completed" if verified else "incomplete",
        "action_ref": action_ref,
        "connector": connector.name,
        "operation": spec.name,
        "risk": spec.risk,
        "environment": reference.environment,
        "asset_id": reference.asset_id or None,
        "result": mask_sensitive(result.data),
        "evidence": evidence,
        "verification_status": "verified" if verified else "evidence_missing",
        "verification_evidence_types": sorted(verification_types),
        "verified_evidence_count": len(verified_items),
        "requires_reconciliation": not verified,
        "error": None if verified else "production_action_verification_evidence_missing",
    }
