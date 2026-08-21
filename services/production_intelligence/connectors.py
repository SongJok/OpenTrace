"""持久化 Connector 目录与安全配置校验。"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from connectors.registry import connector_registry
from connectors.runtime import (
    ConnectorRuntimePolicyError,
    with_normalized_runtime_policy,
)
from infra.storage.models import EnterpriseConnector
from services.production_intelligence.asset_graph import ProductionScope
from services.production_intelligence.audit import append_audit
from services.production_intelligence.domain import (
    CONNECTOR_KINDS,
    CONNECTOR_TRANSPORTS,
    DATA_CLASSIFICATIONS,
    OPERATION_RISKS,
)

_SECRET_REF_PREFIXES = (
    "env://",
    "vault://",
    "aws-secrets://",
    "gcp-secret://",
    "k8s-secret://",
)
_SENSITIVE_CONFIG_KEYS = ("password", "secret", "token", "api_key", "authorization", "credential")


class ConnectorCatalogError(ValueError):
    pass


def _contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            if any(marker in str(key).lower() for marker in _SENSITIVE_CONFIG_KEYS):
                return True
            if _contains_sensitive_key(item):
                return True
    elif isinstance(value, list):
        return any(_contains_sensitive_key(item) for item in value)
    return False


def _validate_endpoint(endpoint: str | None) -> str | None:
    if not endpoint:
        return None
    normalized = endpoint.strip()
    parsed = urlsplit(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConnectorCatalogError("connector_endpoint_must_be_http_url")
    if parsed.username or parsed.password:
        raise ConnectorCatalogError("connector_endpoint_credentials_forbidden")
    if parsed.query or parsed.fragment:
        raise ConnectorCatalogError("connector_endpoint_components_forbidden")
    return normalized


def _normalized_connector_config(*, transport: str, config: dict[str, Any]) -> dict[str, Any]:
    normalized = with_normalized_runtime_policy(config)
    if transport == "mcp":
        configured_adapter = str(normalized.get("adapter_key") or "").strip().lower()
        if configured_adapter not in {"", "mcp"}:
            raise ConnectorCatalogError("mcp_adapter_key_mismatch")
        normalized["adapter_key"] = "mcp"
    return normalized


def _validate_names(
    *, allowed_operations: Sequence[str], allowed_environments: Sequence[str]
) -> None:
    if len(allowed_operations) > 64 or len(allowed_environments) > 16:
        raise ConnectorCatalogError("connector_catalog_limits_exceeded")
    if any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", str(item or ""))
        for item in allowed_operations
    ):
        raise ConnectorCatalogError("connector_operation_name_invalid")
    if any(
        not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,31}", str(item or ""))
        for item in allowed_environments
    ):
        raise ConnectorCatalogError("connector_environment_name_invalid")


def _validate_write_spec(spec: Any) -> None:
    if spec.risk == "read":
        return
    if (
        not spec.evidence_types
        or not spec.verification_evidence_types
        or not set(spec.verification_evidence_types).issubset(set(spec.evidence_types))
        or not spec.supports_idempotency
    ):
        raise ConnectorCatalogError("native_write_operation_verification_required")


def _validate_operation_declarations(
    *, transport: str, allowed_operations: Sequence[str], config: dict[str, Any]
) -> None:
    _validate_names(allowed_operations=allowed_operations, allowed_environments=())
    if transport != "mcp":
        adapter_key = str(config.get("adapter_key") or "").strip().lower()
        if not adapter_key or adapter_key == "mcp":
            raise ConnectorCatalogError("native_connector_adapter_key_required")
        adapter = connector_registry.get(adapter_key)
        if adapter is None:
            raise ConnectorCatalogError(f"connector_adapter_not_registered:{adapter_key}")
        native_specs = {item.name: item for item in adapter.operations()}
        dynamic_resolver = getattr(adapter, "operation_spec", None)
        for operation in allowed_operations:
            spec = (
                dynamic_resolver(str(operation), config)
                if callable(dynamic_resolver)
                else native_specs.get(str(operation))
            )
            if spec is None:
                raise ConnectorCatalogError("native_connector_operation_not_declared")
            _validate_write_spec(spec)
        return
    if str(config.get("adapter_key") or "") != "mcp":
        raise ConnectorCatalogError("mcp_adapter_key_mismatch")
    raw_specs = config.get("operation_specs")
    if not isinstance(raw_specs, list) or not raw_specs:
        raise ConnectorCatalogError("mcp_operation_specs_required")
    declared_mcp_operations: set[str] = set()
    for raw in raw_specs:
        if not isinstance(raw, dict):
            raise ConnectorCatalogError("mcp_operation_spec_invalid")
        name = str(raw.get("name") or "").strip()
        domain = str(raw.get("domain") or "").strip()
        risk = str(raw.get("risk") or "read").strip()
        input_schema = raw.get("input_schema")
        required_permissions = raw.get("required_permissions") or []
        evidence_types = raw.get("evidence_types") or []
        verification_evidence_types = raw.get("verification_evidence_types") or []
        try:
            timeout_seconds = float(raw.get("timeout_seconds") or 30.0)
            max_output_bytes = int(raw.get("max_output_bytes") or 262_144)
        except (TypeError, ValueError) as exc:
            raise ConnectorCatalogError("mcp_operation_spec_invalid") from exc
        if (
            not name
            or len(name) > 128
            or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
            or name in declared_mcp_operations
            or domain not in {*CONNECTOR_KINDS, "asset"}
            or risk not in OPERATION_RISKS
            or not isinstance(input_schema, dict)
            or input_schema.get("type") != "object"
            or input_schema.get("additionalProperties") is not False
            or not isinstance(input_schema.get("properties", {}), dict)
            or len(input_schema.get("properties", {})) > 100
            or not isinstance(required_permissions, list)
            or any(
                not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", item)
                for item in required_permissions
            )
            or not isinstance(evidence_types, list)
            or any(
                not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", item)
                for item in evidence_types
            )
            or not isinstance(verification_evidence_types, list)
            or any(
                not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", item)
                for item in verification_evidence_types
            )
            or not set(verification_evidence_types).issubset(set(evidence_types))
            or (risk != "read" and not evidence_types)
            or (risk != "read" and not verification_evidence_types)
            or (risk != "read" and raw.get("supports_idempotency") is not True)
            or not 0.1 <= timeout_seconds <= 120.0
            or not 1024 <= max_output_bytes <= 1_048_576
        ):
            raise ConnectorCatalogError("mcp_operation_spec_invalid")
        declared_mcp_operations.add(name)
    if not set(allowed_operations).issubset(declared_mcp_operations):
        raise ConnectorCatalogError("mcp_allowed_operation_not_declared")


def _validate_readiness(
    *,
    status: str,
    transport: str,
    endpoint: str | None,
    allowed_operations: Sequence[str],
    allowed_environments: Sequence[str],
    config: dict[str, Any],
) -> None:
    _validate_names(
        allowed_operations=allowed_operations,
        allowed_environments=allowed_environments,
    )
    if status not in {"disabled", "enabled", "degraded"}:
        raise ConnectorCatalogError("connector_status_invalid")
    if status != "enabled":
        return
    if not allowed_operations:
        raise ConnectorCatalogError("enabled_connector_operations_required")
    if not allowed_environments:
        raise ConnectorCatalogError("enabled_connector_environments_required")
    adapter = connector_registry.get(str(config.get("adapter_key") or ""))
    endpoint_required = transport == "mcp" or bool(getattr(adapter, "endpoint_required", False))
    if endpoint_required and not endpoint:
        raise ConnectorCatalogError("enabled_connector_endpoint_required")
    if endpoint:
        parsed = urlsplit(endpoint)
        local_http = (
            parsed.scheme == "http"
            and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            and bool(config.get("allow_local_http"))
        )
        if parsed.scheme != "https" and not local_http:
            raise ConnectorCatalogError("enabled_connector_https_required")
        allowed_hosts = {
            str(item).strip().lower()
            for item in config.get("allowed_hosts") or []
            if str(item).strip()
        }
        if not allowed_hosts or str(parsed.hostname or "").lower() not in allowed_hosts:
            raise ConnectorCatalogError("enabled_connector_host_allowlist_required")


def connector_to_dict(row: EnterpriseConnector) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "connector_kind": row.connector_kind,
        "transport": row.transport,
        "endpoint": row.endpoint,
        "has_secret_ref": bool(row.secret_ref),
        "status": row.status,
        "allowed_operations": list(row.allowed_operations or []),
        "allowed_environments": list(row.allowed_environments or []),
        "data_classification": row.data_classification,
        "config": dict(row.config or {}),
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class ConnectorCatalogService:
    def __init__(self, db: AsyncSession, scope: ProductionScope) -> None:
        self.db = db
        self.scope = scope

    def _scope_filter(self):
        return (
            EnterpriseConnector.tenant_id == self.scope.tenant_id,
            EnterpriseConnector.workspace_id == self.scope.workspace_id,
        )

    async def get(self, connector_id: str) -> EnterpriseConnector | None:
        return await self.db.scalar(
            select(EnterpriseConnector).where(
                EnterpriseConnector.id == connector_id, *self._scope_filter()
            )
        )

    async def require(self, connector_id: str) -> EnterpriseConnector:
        row = await self.get(connector_id)
        if row is None:
            raise ConnectorCatalogError("connector_not_found")
        return row

    async def list(
        self, *, connector_kind: str | None = None, status: str | None = None
    ) -> list[EnterpriseConnector]:
        stmt = select(EnterpriseConnector).where(*self._scope_filter())
        if connector_kind:
            if connector_kind not in CONNECTOR_KINDS:
                raise ConnectorCatalogError("unsupported_connector_kind")
            stmt = stmt.where(EnterpriseConnector.connector_kind == connector_kind)
        if status:
            stmt = stmt.where(EnterpriseConnector.status == status)
        rows = await self.db.execute(stmt.order_by(EnterpriseConnector.name))
        return list(rows.scalars().all())

    @staticmethod
    def _validate(
        *,
        connector_kind: str,
        transport: str,
        secret_ref: str | None,
        classification: str,
        config: dict[str, Any],
    ) -> None:
        if connector_kind not in CONNECTOR_KINDS:
            raise ConnectorCatalogError("unsupported_connector_kind")
        if transport not in CONNECTOR_TRANSPORTS:
            raise ConnectorCatalogError("unsupported_connector_transport")
        if classification not in DATA_CLASSIFICATIONS:
            raise ConnectorCatalogError("unsupported_data_classification")
        if secret_ref and not secret_ref.startswith(_SECRET_REF_PREFIXES):
            raise ConnectorCatalogError("connector_secret_ref_invalid")
        if _contains_sensitive_key(config):
            raise ConnectorCatalogError("plaintext_secret_in_connector_config")
        try:
            with_normalized_runtime_policy(config)
        except ConnectorRuntimePolicyError as exc:
            raise ConnectorCatalogError(str(exc)) from exc

    async def create(
        self,
        *,
        name: str,
        connector_kind: str,
        transport: str,
        endpoint: str | None,
        secret_ref: str | None,
        status: str,
        allowed_operations: Sequence[str],
        allowed_environments: Sequence[str],
        data_classification: str,
        config: dict[str, Any],
    ) -> EnterpriseConnector:
        if not name.strip():
            raise ConnectorCatalogError("connector_name_required")
        normalized_config = _normalized_connector_config(transport=transport, config=config)
        normalized_endpoint = _validate_endpoint(endpoint)
        self._validate(
            connector_kind=connector_kind,
            transport=transport,
            secret_ref=secret_ref,
            classification=data_classification,
            config=normalized_config,
        )
        _validate_operation_declarations(
            transport=transport,
            allowed_operations=allowed_operations,
            config=normalized_config,
        )
        _validate_readiness(
            status=status,
            transport=transport,
            endpoint=normalized_endpoint,
            allowed_operations=allowed_operations,
            allowed_environments=allowed_environments,
            config=normalized_config,
        )
        existing = await self.db.scalar(
            select(EnterpriseConnector).where(
                *self._scope_filter(), EnterpriseConnector.name == name.strip()
            )
        )
        if existing is not None:
            raise ConnectorCatalogError("connector_already_exists")
        row = EnterpriseConnector(
            id=str(uuid.uuid4()),
            tenant_id=self.scope.tenant_id,
            workspace_id=self.scope.workspace_id,
            name=name.strip(),
            connector_kind=connector_kind,
            transport=transport,
            endpoint=normalized_endpoint,
            secret_ref=secret_ref,
            status=status,
            allowed_operations=sorted(set(allowed_operations)),
            allowed_environments=sorted(set(allowed_environments)),
            data_classification=data_classification,
            config=normalized_config,
            created_by=self.scope.user_id,
        )
        self.db.add(row)
        await self.db.flush()
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="enterprise_connector.created",
            resource_type="enterprise_connector",
            resource_id=row.id,
            payload={
                "name": row.name,
                "connector_kind": row.connector_kind,
                "transport": row.transport,
                "status": row.status,
                "has_secret_ref": bool(row.secret_ref),
            },
        )
        return row

    async def update(self, connector_id: str, changes: dict[str, Any]) -> EnterpriseConnector:
        row = await self.require(connector_id)
        allowed = {
            "name",
            "transport",
            "endpoint",
            "secret_ref",
            "status",
            "allowed_operations",
            "allowed_environments",
            "data_classification",
            "config",
        }
        unknown = set(changes) - allowed
        if unknown:
            raise ConnectorCatalogError(f"unsupported_connector_fields:{','.join(sorted(unknown))}")
        candidate = {
            "connector_kind": row.connector_kind,
            "transport": changes.get("transport", row.transport),
            "secret_ref": changes.get("secret_ref", row.secret_ref),
            "classification": changes.get("data_classification", row.data_classification),
            "config": _normalized_connector_config(
                transport=str(changes.get("transport", row.transport)),
                config=dict(changes.get("config", row.config or {})),
            ),
        }
        self._validate(**candidate)
        _validate_operation_declarations(
            transport=str(candidate["transport"]),
            allowed_operations=list(
                changes.get("allowed_operations", row.allowed_operations or [])
            ),
            config=dict(candidate["config"]),
        )
        candidate_endpoint = _validate_endpoint(changes.get("endpoint", row.endpoint))
        candidate_operations = list(changes.get("allowed_operations", row.allowed_operations or []))
        candidate_environments = list(
            changes.get("allowed_environments", row.allowed_environments or [])
        )
        _validate_readiness(
            status=str(changes.get("status", row.status)),
            transport=str(candidate["transport"]),
            endpoint=candidate_endpoint,
            allowed_operations=candidate_operations,
            allowed_environments=candidate_environments,
            config=dict(candidate["config"]),
        )
        for key, value in changes.items():
            if key == "name":
                value = str(value).strip()
                if not value:
                    raise ConnectorCatalogError("connector_name_required")
            elif key == "endpoint":
                value = _validate_endpoint(value)
            elif key in {"allowed_operations", "allowed_environments"}:
                value = sorted(set(value or []))
            elif key == "config":
                value = candidate["config"]
            setattr(row, key, value)
        if "transport" in changes and "config" not in changes:
            row.config = candidate["config"]
        append_audit(
            self.db,
            user_id=self.scope.user_id,
            action="enterprise_connector.updated",
            resource_type="enterprise_connector",
            resource_id=row.id,
            payload={"fields": sorted(changes)},
        )
        await self.db.flush()
        return row
