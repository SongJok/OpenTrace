"""基于官方 MCP Python SDK v2 的 Streamable HTTP 适配器。"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urlsplit

from connectors.contracts import (
    ConnectorEvidence,
    ConnectorExecutionContext,
    ConnectorOperationSpec,
    ConnectorResult,
)
from connectors.network_security import validate_network_target

MCPInvoker = Callable[[str, str, dict[str, Any], dict[str, str], float], Awaitable[Any]]


class SecretHeaderResolver(Protocol):
    async def resolve_headers(self, secret_ref: str | None) -> dict[str, str]: ...


class EnvironmentBearerSecretResolver:
    """默认仅支持环境变量引用；Vault/KMS 由部署方注入实现。"""

    async def resolve_headers(self, secret_ref: str | None) -> dict[str, str]:
        if not secret_ref:
            return {}
        if not secret_ref.startswith("env://"):
            raise RuntimeError("mcp_secret_provider_not_configured")
        variable = secret_ref.removeprefix("env://")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,127}", variable):
            raise RuntimeError("mcp_environment_secret_ref_invalid")
        value = os.getenv(variable)
        if not value:
            raise RuntimeError("mcp_environment_secret_missing")
        return {"Authorization": f"Bearer {value}"}


def _operation_spec_from_config(
    operation: str, connector_config: dict[str, Any]
) -> ConnectorOperationSpec | None:
    for raw in connector_config.get("operation_specs") or []:
        if not isinstance(raw, dict) or str(raw.get("name") or "") != operation:
            continue
        return ConnectorOperationSpec(
            name=operation,
            description=str(raw.get("description") or operation)[:1000],
            domain=str(raw.get("domain") or "business"),
            input_schema=dict(raw.get("input_schema") or {}),
            risk=str(raw.get("risk") or "read"),
            required_permissions=tuple(str(item) for item in raw.get("required_permissions") or []),
            timeout_seconds=max(0.1, min(float(raw.get("timeout_seconds") or 30.0), 120.0)),
            max_output_bytes=max(1024, min(int(raw.get("max_output_bytes") or 262_144), 1_048_576)),
            evidence_types=tuple(str(item) for item in raw.get("evidence_types") or []),
            verification_evidence_types=tuple(
                str(item) for item in raw.get("verification_evidence_types") or []
            ),
            supports_idempotency=bool(raw.get("supports_idempotency", False)),
        )
    return None


async def _invoke_mcp_v2(
    endpoint: str,
    operation: str,
    arguments: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> Any:
    try:
        import httpx2
        from mcp import Client
        from mcp.client.streamable_http import streamable_http_client
    except (ImportError, AttributeError) as exc:  # pragma: no cover - 由部署依赖覆盖
        raise RuntimeError("mcp_v2_runtime_unavailable") from exc

    parsed = urlsplit(endpoint)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    async with httpx2.AsyncClient(
        headers={"Origin": origin, **headers},
        follow_redirects=False,
        timeout=timeout_seconds,
    ) as http_client:
        transport = streamable_http_client(endpoint, http_client=http_client)
        async with Client(transport, read_timeout_seconds=timeout_seconds) as client:
            return await client.call_tool(
                operation,
                arguments,
                read_timeout_seconds=timeout_seconds,
            )


def _result_payload(raw: Any) -> tuple[bool, dict[str, Any], str]:
    is_error = bool(getattr(raw, "is_error", False))
    structured = getattr(raw, "structured_content", None)
    if structured is None:
        structured = getattr(raw, "structuredContent", None)
    content_texts: list[str] = []
    for block in list(getattr(raw, "content", None) or []):
        text = getattr(block, "text", None)
        if isinstance(text, str) and text:
            content_texts.append(text[:20_000])
    rendered = "\n".join(content_texts)[:40_000]
    if isinstance(structured, dict):
        payload = dict(structured)
    elif rendered:
        try:
            decoded = json.loads(rendered)
        except json.JSONDecodeError:
            decoded = None
        payload = dict(decoded) if isinstance(decoded, dict) else {"content": rendered}
    else:
        payload = {}
    return is_error, payload, rendered


def _parse_observed_at(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _evidence_from_payload(
    *,
    operation: str,
    spec: ConnectorOperationSpec,
    payload: dict[str, Any],
    context: ConnectorExecutionContext,
) -> tuple[ConnectorEvidence, ...]:
    raw_items = payload.get("evidence")
    items = raw_items if isinstance(raw_items, list) else []
    evidence: list[ConnectorEvidence] = []
    allowed_types = set(spec.evidence_types)
    for index, raw in enumerate(items[:100]):
        if not isinstance(raw, dict):
            continue
        evidence_type = str(raw.get("evidence_type") or raw.get("type") or "")
        if allowed_types and evidence_type not in allowed_types:
            continue
        source_ref = str(raw.get("source_ref") or raw.get("resource") or "")
        summary = str(raw.get("summary") or raw.get("content") or "")[:10_000]
        title = str(raw.get("title") or f"{operation} 证据 {index + 1}")[:255]
        observed_at = _parse_observed_at(raw.get("observed_at") or raw.get("timestamp"))
        expires_at = _parse_observed_at(raw.get("expires_at")) if raw.get("expires_at") else None
        if (
            not evidence_type
            or not source_ref
            or not summary
            or observed_at is None
            or (raw.get("expires_at") and expires_at is None)
        ):
            continue
        evidence.append(
            ConnectorEvidence(
                evidence_type=evidence_type,
                source_ref=source_ref,
                title=title,
                summary=summary,
                observed_at=observed_at,
                source_kind="mcp",
                asset_id=str(raw.get("asset_id") or "") or None,
                environment=str(raw.get("environment") or context.environment),
                authority=str(raw.get("authority") or "external_observation"),
                permission_class=str(raw.get("permission_class") or "internal"),
                confidence=float(raw.get("confidence") or 0.5),
                payload=dict(raw.get("payload") or {}),
                expires_at=expires_at,
            )
        )
    return tuple(evidence)


class MCPStreamableHTTPAdapter:
    """声明式 MCP Adapter；远端发现不能自动扩大本地允许操作集合。"""

    adapter_key = "mcp"
    dynamic_operations = True

    def __init__(
        self,
        *,
        invoker: MCPInvoker | None = None,
        secret_resolver: SecretHeaderResolver | None = None,
    ) -> None:
        self._invoker = invoker or _invoke_mcp_v2
        self._secret_resolver = secret_resolver or EnvironmentBearerSecretResolver()
        self._validate_network = invoker is None

    def operations(self) -> tuple[ConnectorOperationSpec, ...]:
        return ()

    def operation_spec(
        self, operation: str, connector_config: dict[str, Any]
    ) -> ConnectorOperationSpec | None:
        return _operation_spec_from_config(operation, connector_config)

    async def execute(
        self,
        operation: str,
        arguments: dict[str, Any],
        *,
        context: ConnectorExecutionContext,
        connector_config: dict[str, Any],
        secret_ref: str | None,
    ) -> ConnectorResult:
        endpoint = str(connector_config.get("endpoint") or "").strip()
        if not endpoint:
            raise RuntimeError("mcp_endpoint_required")
        if self._validate_network:
            await validate_network_target(endpoint, connector_config, error_prefix="mcp")
        spec = self.operation_spec(operation, connector_config)
        if spec is None:
            raise RuntimeError("mcp_operation_not_declared")
        headers = await self._secret_resolver.resolve_headers(secret_ref)
        if spec.supports_idempotency and context.idempotency_key:
            headers = {**headers, "Idempotency-Key": context.idempotency_key}
        raw = await self._invoker(
            endpoint,
            operation,
            dict(arguments),
            headers,
            float(spec.timeout_seconds),
        )
        is_error, payload, rendered = _result_payload(raw)
        if is_error:
            return ConnectorResult(
                status="failed",
                data={"error": rendered[:2000] or "mcp_tool_error"},
            )
        evidence = _evidence_from_payload(
            operation=operation,
            spec=spec,
            payload=payload,
            context=context,
        )
        return ConnectorResult(
            status="completed",
            data=payload,
            evidence=evidence,
            metadata={"transport": "mcp_streamable_http", "operation": operation},
        )
