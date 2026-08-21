"""Connector 分布式限流、并发租约与熔断控制。"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from infra.cache.redis_client import get_rate_limit_redis
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class ConnectorRuntimePolicyError(ValueError):
    """Connector runtime_policy 不满足安全边界。"""


@dataclass(frozen=True, slots=True)
class ConnectorRuntimePolicy:
    enabled: bool = True
    requests_per_minute: int = 120
    max_concurrency: int = 8
    failure_threshold: int = 5
    recovery_seconds: int = 60
    half_open_max_calls: int = 1
    lease_grace_seconds: int = 5
    read_fail_open: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "requests_per_minute": self.requests_per_minute,
            "max_concurrency": self.max_concurrency,
            "failure_threshold": self.failure_threshold,
            "recovery_seconds": self.recovery_seconds,
            "half_open_max_calls": self.half_open_max_calls,
            "lease_grace_seconds": self.lease_grace_seconds,
            "read_fail_open": self.read_fail_open,
        }


def runtime_policy_from_config(config: dict[str, Any]) -> ConnectorRuntimePolicy:
    """读取并严格校验 runtime_policy；缺省值适用于所有正式 Connector。"""

    raw = config.get("runtime_policy")
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConnectorRuntimePolicyError("connector_runtime_policy_invalid")
    allowed = {
        "enabled",
        "requests_per_minute",
        "max_concurrency",
        "failure_threshold",
        "recovery_seconds",
        "half_open_max_calls",
        "lease_grace_seconds",
        "read_fail_open",
    }
    if set(raw) - allowed:
        raise ConnectorRuntimePolicyError("connector_runtime_policy_unknown_field")
    for name in ("enabled", "read_fail_open"):
        if name in raw and not isinstance(raw[name], bool):
            raise ConnectorRuntimePolicyError("connector_runtime_policy_invalid")
    for name in (
        "requests_per_minute",
        "max_concurrency",
        "failure_threshold",
        "recovery_seconds",
        "half_open_max_calls",
        "lease_grace_seconds",
    ):
        if name in raw and (not isinstance(raw[name], int) or isinstance(raw[name], bool)):
            raise ConnectorRuntimePolicyError("connector_runtime_policy_invalid")
    try:
        policy = ConnectorRuntimePolicy(
            enabled=bool(raw.get("enabled", True)),
            requests_per_minute=int(raw.get("requests_per_minute", 120)),
            max_concurrency=int(raw.get("max_concurrency", 8)),
            failure_threshold=int(raw.get("failure_threshold", 5)),
            recovery_seconds=int(raw.get("recovery_seconds", 60)),
            half_open_max_calls=int(raw.get("half_open_max_calls", 1)),
            lease_grace_seconds=int(raw.get("lease_grace_seconds", 5)),
            read_fail_open=bool(raw.get("read_fail_open", True)),
        )
    except (TypeError, ValueError) as exc:
        raise ConnectorRuntimePolicyError("connector_runtime_policy_invalid") from exc
    bounds = (
        (1 <= policy.requests_per_minute <= 60_000),
        (1 <= policy.max_concurrency <= 1_000),
        (1 <= policy.failure_threshold <= 100),
        (1 <= policy.recovery_seconds <= 86_400),
        (1 <= policy.half_open_max_calls <= policy.max_concurrency),
        (1 <= policy.lease_grace_seconds <= 300),
    )
    if not all(bounds):
        raise ConnectorRuntimePolicyError("connector_runtime_policy_out_of_range")
    return policy


def with_normalized_runtime_policy(config: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(config)
    normalized["runtime_policy"] = runtime_policy_from_config(config).to_dict()
    return normalized


@dataclass(frozen=True, slots=True)
class RuntimeAdmission:
    admitted: bool
    request_id: str
    reason: str = "admitted"
    retry_after_ms: int = 0
    degraded: bool = False
    control_state: str = "closed"


class ConnectorRuntimeStore(Protocol):
    async def acquire(
        self,
        *,
        scope_key: str,
        request_id: str,
        policy: ConnectorRuntimePolicy,
        lease_seconds: float,
    ) -> tuple[bool, str, int]: ...

    async def record_outcome(
        self,
        *,
        scope_key: str,
        request_id: str,
        policy: ConnectorRuntimePolicy,
        success: bool,
    ) -> None: ...


_ACQUIRE_SCRIPT = """
local now = tonumber(ARGV[1])
local request_id = ARGV[2]
local rpm = tonumber(ARGV[3])
local max_concurrency = tonumber(ARGV[4])
local recovery_ms = tonumber(ARGV[5])
local half_open_max = tonumber(ARGV[6])
local lease_ms = tonumber(ARGV[7])

redis.call('ZREMRANGEBYSCORE', KEYS[1], 0, now - 60000)
redis.call('ZREMRANGEBYSCORE', KEYS[3], 0, now)

local circuit = redis.call('HMGET', KEYS[2], 'state', 'opened_at')
local state = circuit[1] or 'closed'
local opened_at = tonumber(circuit[2] or '0')
if state == 'open' then
  local remaining = recovery_ms - (now - opened_at)
  if remaining > 0 then
    return {0, 'circuit_open', remaining}
  end
  state = 'half_open'
  redis.call('HSET', KEYS[2], 'state', state)
end

local in_flight = tonumber(redis.call('ZCARD', KEYS[3]))
local concurrency_limit = max_concurrency
if state == 'half_open' then
  concurrency_limit = half_open_max
end
if in_flight >= concurrency_limit then
  return {0, state == 'half_open' and 'circuit_half_open_busy' or 'concurrency_limited', lease_ms}
end

local used = tonumber(redis.call('ZCARD', KEYS[1]))
if used >= rpm then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  local retry_after = 1000
  if oldest[2] then
    retry_after = math.max(1, 60000 - (now - tonumber(oldest[2])))
  end
  return {0, 'rate_limited', retry_after}
end

redis.call('ZADD', KEYS[1], now, request_id)
redis.call('EXPIRE', KEYS[1], 120)
redis.call('ZADD', KEYS[3], now + lease_ms, request_id)
redis.call('EXPIRE', KEYS[3], math.ceil(lease_ms / 1000) + 60)
redis.call('EXPIRE', KEYS[2], math.ceil(recovery_ms / 1000) * 4 + 60)
return {1, state, 0}
"""


_OUTCOME_SCRIPT = """
local now = tonumber(ARGV[1])
local request_id = ARGV[2]
local success = tonumber(ARGV[3])
local threshold = tonumber(ARGV[4])
local recovery_seconds = tonumber(ARGV[5])

redis.call('ZREM', KEYS[2], request_id)
local state = redis.call('HGET', KEYS[1], 'state') or 'closed'
if success == 1 then
  redis.call('HSET', KEYS[1], 'state', 'closed', 'failures', 0, 'opened_at', 0)
else
  local failures = tonumber(redis.call('HINCRBY', KEYS[1], 'failures', 1))
  if state == 'half_open' or failures >= threshold then
    redis.call('HSET', KEYS[1], 'state', 'open', 'opened_at', now)
  end
end
redis.call('EXPIRE', KEYS[1], recovery_seconds * 4 + 60)
return 1
"""


class RedisConnectorRuntimeStore:
    """使用 Redis Lua 保证多 Worker 的限流、租约和熔断状态原子更新。"""

    @staticmethod
    def _keys(scope_key: str) -> tuple[str, str, str]:
        digest = hashlib.sha256(scope_key.encode("utf-8")).hexdigest()[:32]
        prefix = f"opentrace:connector-runtime:{{{digest}}}"
        return f"{prefix}:rate", f"{prefix}:circuit", f"{prefix}:inflight"

    async def acquire(
        self,
        *,
        scope_key: str,
        request_id: str,
        policy: ConnectorRuntimePolicy,
        lease_seconds: float,
    ) -> tuple[bool, str, int]:
        import time

        redis = await get_rate_limit_redis()
        rate_key, circuit_key, inflight_key = self._keys(scope_key)
        result = await redis.r.eval(
            _ACQUIRE_SCRIPT,
            3,
            rate_key,
            circuit_key,
            inflight_key,
            int(time.time() * 1000),
            request_id,
            policy.requests_per_minute,
            policy.max_concurrency,
            policy.recovery_seconds * 1000,
            policy.half_open_max_calls,
            max(1000, int(lease_seconds * 1000)),
        )
        values = list(result or [])
        admitted = bool(int(values[0])) if values else False
        reason = str(values[1]) if len(values) > 1 else "runtime_store_invalid_response"
        retry_after_ms = int(values[2]) if len(values) > 2 else 0
        return admitted, reason, retry_after_ms

    async def record_outcome(
        self,
        *,
        scope_key: str,
        request_id: str,
        policy: ConnectorRuntimePolicy,
        success: bool,
    ) -> None:
        import time

        redis = await get_rate_limit_redis()
        _, circuit_key, inflight_key = self._keys(scope_key)
        await redis.r.eval(
            _OUTCOME_SCRIPT,
            2,
            circuit_key,
            inflight_key,
            int(time.time() * 1000),
            request_id,
            1 if success else 0,
            policy.failure_threshold,
            policy.recovery_seconds,
        )


class ConnectorRuntimeControl:
    """将存储故障转换为明确的读降级或写拒绝语义。"""

    def __init__(self, store: ConnectorRuntimeStore | None = None) -> None:
        self.store = store or RedisConnectorRuntimeStore()

    async def acquire(
        self,
        *,
        tenant_id: str,
        workspace_id: str,
        connector_id: str,
        risk: str,
        timeout_seconds: float,
        config: dict[str, Any],
        idempotency_key: str | None = None,
    ) -> tuple[RuntimeAdmission, ConnectorRuntimePolicy]:
        policy = runtime_policy_from_config(config)
        request_id = idempotency_key or str(uuid.uuid4())
        if not policy.enabled:
            return RuntimeAdmission(True, request_id, reason="runtime_policy_disabled"), policy
        scope_key = f"{tenant_id}:{workspace_id}:{connector_id}"
        lease_seconds = min(425.0, max(1.0, timeout_seconds + policy.lease_grace_seconds))
        try:
            admitted, reason, retry_after_ms = await self.store.acquire(
                scope_key=scope_key,
                request_id=request_id,
                policy=policy,
                lease_seconds=lease_seconds,
            )
        except Exception as exc:  # noqa: BLE001
            fail_open = risk == "read" and policy.read_fail_open
            logger.warning(
                "Connector runtime control unavailable",
                risk=risk,
                fail_open=fail_open,
                error=type(exc).__name__,
            )
            return (
                RuntimeAdmission(
                    fail_open,
                    request_id,
                    reason="runtime_control_unavailable",
                    degraded=fail_open,
                    control_state="unavailable",
                ),
                policy,
            )
        return (
            RuntimeAdmission(
                admitted,
                request_id,
                reason="admitted" if admitted else reason,
                retry_after_ms=retry_after_ms,
                control_state=reason if admitted else "denied",
            ),
            policy,
        )

    async def complete(
        self,
        *,
        admission: RuntimeAdmission,
        policy: ConnectorRuntimePolicy,
        tenant_id: str,
        workspace_id: str,
        connector_id: str,
        success: bool,
    ) -> bool:
        if not policy.enabled or admission.degraded or not admission.admitted:
            return True
        try:
            await self.store.record_outcome(
                scope_key=f"{tenant_id}:{workspace_id}:{connector_id}",
                request_id=admission.request_id,
                policy=policy,
                success=success,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Connector runtime outcome persistence failed",
                success=success,
                error=type(exc).__name__,
            )
            return False
