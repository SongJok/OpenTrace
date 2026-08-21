"""内置 Prometheus HTTP API 只读适配器。"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from connectors.contracts import (
    ConnectorEvidence,
    ConnectorExecutionContext,
    ConnectorOperationSpec,
    ConnectorResult,
)
from connectors.mcp import EnvironmentBearerSecretResolver, SecretHeaderResolver
from connectors.network_security import validate_network_target

PrometheusRequester = Callable[
    [str, dict[str, str], dict[str, str], float, int], Awaitable[dict[str, Any]]
]

_PROMETHEUS_NAME_RE = re.compile(r"[a-zA-Z_:][a-zA-Z0-9_:]{0,127}")
_LABEL_NAME_RE = re.compile(r"[a-zA-Z_][a-zA-Z0-9_]{0,63}")


def _promql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _validated_name(value: Any, *, label: bool = False) -> str:
    normalized = str(value or "").strip()
    pattern = _LABEL_NAME_RE if label else _PROMETHEUS_NAME_RE
    if not pattern.fullmatch(normalized):
        raise RuntimeError("prometheus_metric_configuration_invalid")
    return normalized


async def _request_prometheus(
    endpoint: str,
    params: dict[str, str],
    headers: dict[str, str],
    timeout_seconds: float,
    max_response_bytes: int,
) -> dict[str, Any]:
    url = f"{endpoint.rstrip('/')}/api/v1/query"
    async with httpx.AsyncClient(
        headers=headers,
        follow_redirects=False,
        timeout=timeout_seconds,
    ) as client:
        async with client.stream("GET", url, params=params) as response:
            if response.status_code >= 400:
                raise RuntimeError(f"prometheus_http_error:{response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > max_response_bytes:
                    raise RuntimeError("prometheus_response_too_large")
    try:
        decoded = json.loads(bytes(body))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("prometheus_response_invalid_json") from exc
    if not isinstance(decoded, dict):
        raise RuntimeError("prometheus_response_invalid")
    return decoded


def _vector_samples(payload: dict[str, Any], *, max_series: int) -> list[dict[str, Any]]:
    if payload.get("status") != "success":
        raise RuntimeError("prometheus_query_failed")
    data = payload.get("data")
    if not isinstance(data, dict) or data.get("resultType") != "vector":
        raise RuntimeError("prometheus_vector_result_required")
    raw_results = data.get("result")
    if not isinstance(raw_results, list):
        raise RuntimeError("prometheus_result_invalid")
    if len(raw_results) > max_series:
        raise RuntimeError("prometheus_series_limit_exceeded")

    samples: list[dict[str, Any]] = []
    for raw in raw_results:
        if not isinstance(raw, dict):
            continue
        value = raw.get("value")
        if not isinstance(value, list) or len(value) != 2:
            continue
        try:
            observed_at = datetime.fromtimestamp(float(value[0]), tz=UTC)
            numeric_value = float(value[1])
        except (TypeError, ValueError, OverflowError):
            continue
        if not math.isfinite(numeric_value):
            continue
        labels = {
            str(key)[:64]: str(item)[:256]
            for key, item in dict(raw.get("metric") or {}).items()
            if _LABEL_NAME_RE.fullmatch(str(key))
        }
        samples.append(
            {
                "value": numeric_value,
                "observed_at": observed_at,
                "labels": labels,
            }
        )
    return samples


class PrometheusHTTPAdapter:
    """通过受限 PromQL 模板查询 HTTP 5xx 比率，不接受任意 PromQL。"""

    adapter_key = "prometheus"
    endpoint_required = True

    def __init__(
        self,
        *,
        requester: PrometheusRequester | None = None,
        secret_resolver: SecretHeaderResolver | None = None,
    ) -> None:
        self._requester = requester or _request_prometheus
        self._secret_resolver = secret_resolver or EnvironmentBearerSecretResolver()
        self._validate_network = requester is None

    def operations(self) -> tuple[ConnectorOperationSpec, ...]:
        return (
            ConnectorOperationSpec(
                name="query_http_error_ratio",
                description="查询受控服务在指定窗口内的 HTTP 5xx 请求比率",
                domain="observability",
                input_schema={
                    "type": "object",
                    "properties": {
                        "service": {"type": "string", "minLength": 1, "maxLength": 128},
                        "environment": {"type": "string", "minLength": 1, "maxLength": 32},
                        "asset_id": {"type": "string", "minLength": 1, "maxLength": 36},
                        "window_seconds": {
                            "type": "integer",
                            "minimum": 60,
                            "maximum": 3600,
                            "default": 300,
                        },
                    },
                    "required": ["service", "environment"],
                    "additionalProperties": False,
                },
                timeout_seconds=30.0,
                max_output_bytes=262_144,
                evidence_types=("metric",),
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
        if operation != "query_http_error_ratio":
            raise RuntimeError("prometheus_operation_not_declared")
        endpoint = str(connector_config.get("endpoint") or "").strip()
        if not endpoint:
            raise RuntimeError("prometheus_endpoint_required")
        if self._validate_network:
            await validate_network_target(endpoint, connector_config, error_prefix="prometheus")
        environment = str(arguments.get("environment") or "")
        if environment != context.environment:
            raise RuntimeError("prometheus_environment_scope_mismatch")

        metric = _validated_name(
            connector_config.get("request_counter_metric") or "http_server_requests_total"
        )
        service_label = _validated_name(
            connector_config.get("service_label") or "service", label=True
        )
        environment_label = _validated_name(
            connector_config.get("environment_label") or "environment", label=True
        )
        status_label = _validated_name(connector_config.get("status_label") or "status", label=True)
        service = _promql_string(str(arguments["service"]))
        environment_value = _promql_string(environment)
        window_seconds = max(60, min(int(arguments.get("window_seconds") or 300), 3600))
        selector = (
            f'{metric}{{{service_label}="{service}",' f'{environment_label}="{environment_value}"}}'
        )
        error_selector = (
            f'{metric}{{{service_label}="{service}",'
            f'{environment_label}="{environment_value}",{status_label}=~"5.."}}'
        )
        promql = (
            f"sum(rate({error_selector}[{window_seconds}s])) / "
            f"clamp_min(sum(rate({selector}[{window_seconds}s])), 1e-12)"
        )
        timeout_seconds = max(
            0.1, min(float(connector_config.get("request_timeout_seconds") or 25.0), 120.0)
        )
        max_response_bytes = max(
            4096,
            min(int(connector_config.get("max_response_bytes") or 1_048_576), 4_194_304),
        )
        max_series = max(1, min(int(connector_config.get("max_series") or 100), 100))
        headers = await self._secret_resolver.resolve_headers(secret_ref)
        payload = await self._requester(
            endpoint,
            {"query": promql},
            headers,
            timeout_seconds,
            max_response_bytes,
        )
        samples = _vector_samples(payload, max_series=max_series)
        projected = [
            {
                "value": item["value"],
                "observed_at": item["observed_at"].isoformat(),
                "labels": item["labels"],
            }
            for item in samples
        ]
        if not samples:
            return ConnectorResult(
                status="completed",
                data={"query_status": "no_data", "series": []},
                metadata={"transport": "prometheus_http_api", "operation": operation},
            )

        latest_observation = max(item["observed_at"] for item in samples)
        maximum_ratio = max(float(item["value"]) for item in samples)
        graph_url = f"{endpoint.rstrip('/')}/graph?g0.expr={quote(promql, safe='')}&g0.tab=0"
        evidence = ConnectorEvidence(
            evidence_type="metric",
            source_ref=graph_url,
            title=f"{arguments['service']} HTTP 5xx 比率",
            summary=(
                f"Prometheus 返回 {len(samples)} 条时间序列；"
                f"窗口内最大观测值为 {maximum_ratio:.6g}。"
            ),
            observed_at=latest_observation,
            source_kind="prometheus",
            asset_id=str(arguments.get("asset_id") or "") or None,
            environment=environment,
            authority="production_observation",
            confidence=0.95,
            payload={
                "window_seconds": window_seconds,
                "series_count": len(samples),
                "maximum_ratio": maximum_ratio,
            },
        )
        return ConnectorResult(
            status="completed",
            data={"query_status": "completed", "series": projected},
            evidence=(evidence,),
            metadata={"transport": "prometheus_http_api", "operation": operation},
        )
