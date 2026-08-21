"""MCP、Native、REST 与 RPC 适配器共享的生产级契约。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from services.production_intelligence.domain import OperationRisk


@dataclass(frozen=True, slots=True)
class ConnectorOperationSpec:
    name: str
    description: str
    domain: str
    input_schema: dict[str, Any]
    risk: str = OperationRisk.READ.value
    required_permissions: tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    max_output_bytes: int = 262_144
    evidence_types: tuple[str, ...] = ()
    verification_evidence_types: tuple[str, ...] = ()
    supports_idempotency: bool = False


@dataclass(frozen=True, slots=True)
class ConnectorExecutionContext:
    tenant_id: str
    workspace_id: str
    user_id: str
    response_id: str | None = None
    role: str = "user"
    is_superuser: bool = False
    environment: str = "shared"
    trace_id: str = ""
    approved: bool = False
    permissions: tuple[str, ...] = ()
    idempotency_key: str | None = None


@dataclass(frozen=True, slots=True)
class ConnectorEvidence:
    evidence_type: str
    source_ref: str
    title: str
    summary: str
    observed_at: datetime
    source_kind: str = "external"
    asset_id: str | None = None
    environment: str = "shared"
    authority: str = "external_observation"
    permission_class: str = "internal"
    confidence: float = 0.5
    payload: dict[str, Any] = field(default_factory=dict)
    expires_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class ConnectorResult:
    status: str
    data: dict[str, Any] = field(default_factory=dict)
    evidence: tuple[ConnectorEvidence, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class EnterpriseConnectorAdapter(Protocol):
    """适配器不得自行放宽 OperationSpec 或绕过 Gateway。"""

    adapter_key: str

    def operations(self) -> tuple[ConnectorOperationSpec, ...]: ...

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        context: ConnectorExecutionContext,
        connector_config: dict[str, Any],
        secret_ref: str | None,
    ) -> ConnectorResult: ...
