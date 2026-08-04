"""Responses 主链的企业准入与回合结算。"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from control_plane import get_enterprise_control_plane
from infra.errors import AppException, ErrorCodes
from infra.observability.logger import get_logger
from infra.observability.turn_metering import get_turn_tokens
from tenant.billing_runtime import apply_billing_to_metadata
from tenant.tenant_context import resolve_tenant_context
from tenant.usage_metering import get_usage_metering

logger = get_logger(__name__)
ADMISSION_VERSION = "responses-enterprise-beta-v1"


def accumulate_response_attempt_usage(
    response_metadata: dict[str, Any] | None,
    result_metadata: dict[str, Any] | None = None,
    *,
    attempt_usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    """把本次 Worker 尝试的 token 累加到可恢复 Response 元数据。"""

    merged = {**dict(response_metadata or {}), **dict(result_metadata or {})}
    previous = dict((response_metadata or {}).get("usage_accumulator") or {})
    current = get_turn_tokens() if attempt_usage is None else dict(attempt_usage)
    prompt_tokens = int(previous.get("prompt_tokens") or 0) + int(current.get("prompt_tokens") or 0)
    completion_tokens = int(previous.get("completion_tokens") or 0) + int(
        current.get("completion_tokens") or 0
    )
    if not current.get("prompt_tokens") and not current.get("completion_tokens"):
        prompt_tokens = max(prompt_tokens, int(merged.get("prompt_tokens") or 0))
        completion_tokens = max(completion_tokens, int(merged.get("completion_tokens") or 0))
    merged["prompt_tokens"] = prompt_tokens
    merged["completion_tokens"] = completion_tokens
    merged["usage_accumulator"] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
    }
    return merged


async def evaluate_response_admission(
    *,
    query: str,
    user_id: str,
    session_id: str,
    tenant_id: str,
    workspace_id: str,
    org_id: str,
    tenant_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """在创建 Response 前完成 PII、合规和原子配额准入。"""

    metadata = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "org_id": org_id,
        **dict(tenant_policy or {}),
    }
    pii_types: list[str] = []
    try:
        from governance.pii_detector import detect_pii_signals

        signal = detect_pii_signals(query)
        metadata["pii_detected"] = bool(signal.detected)
        pii_types = [str(item) for item in signal.types]
    except Exception as exc:  # noqa: BLE001
        logger.warning("responses_admission_pii_scan_failed", error=str(exc))
        raise AppException(
            ErrorCodes.INTERNAL_ERROR.code,
            message="企业敏感信息检查暂时不可用",
            details={"stage": "pii_detection"},
        ) from exc

    control_plane = get_enterprise_control_plane()
    decision = await control_plane.evaluate_turn_async(
        user_id=user_id,
        session_id=session_id,
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
        capability_type="responses",
        pii_detected=bool(metadata["pii_detected"]),
        data_region=str(metadata.get("data_residency") or ""),
        metadata=metadata,
    )
    snapshot = decision.to_dict()
    if not decision.allowed:
        violations = list(decision.violations)
        quota_denied = any(item.startswith("quota_") for item in violations)
        code = ErrorCodes.RATE_LIMITED if quota_denied else ErrorCodes.PERMISSION_DENIED
        raise AppException(
            code.code,
            message="企业策略拒绝了本次请求",
            details={"violations": violations, "admission": snapshot},
        )

    context = resolve_tenant_context(
        user_id=user_id,
        session_id=session_id,
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
        metadata=metadata,
    )
    reservation = await control_plane.consume_turn_quota_async(context, cost=0.0)
    if not reservation.allowed:
        raise AppException(
            ErrorCodes.RATE_LIMITED.code,
            message="企业配额不足",
            details={"violations": list(reservation.violations), "admission": snapshot},
        )
    snapshot["quota_reservation"] = reservation.to_dict()
    snapshot["pii"] = {"detected": bool(metadata["pii_detected"]), "types": pii_types}
    snapshot["version"] = ADMISSION_VERSION
    snapshot["evaluated_at"] = datetime.now(UTC).isoformat()
    return snapshot


def settle_response_usage(
    *,
    response_id: str,
    response_metadata: dict[str, Any] | None,
    result_metadata: dict[str, Any] | None,
    user_id: str,
    conversation_id: str,
    tenant_id: str,
    workspace_id: str,
    org_id: str,
    goal_id: str | None,
    capability_type: str,
    include_current_attempt: bool = True,
) -> dict[str, Any]:
    """合并实际 token、账单归属与用量记录，并返回可持久化快照。"""

    base = {**dict(response_metadata or {}), **dict(result_metadata or {})}
    existing = dict(base.get("enterprise_settlement") or {})
    if existing.get("response_id") == response_id:
        return base
    merged = accumulate_response_attempt_usage(
        response_metadata,
        result_metadata,
        attempt_usage=(
            None if include_current_attempt else {"prompt_tokens": 0, "completion_tokens": 0}
        ),
    )
    merged = apply_billing_to_metadata(
        merged,
        capability_type=capability_type,
        goal_id=goal_id or "",
    )
    context = resolve_tenant_context(
        user_id=user_id,
        session_id=conversation_id,
        tenant_id=tenant_id,
        org_id=org_id,
        workspace_id=workspace_id,
        goal_id=goal_id,
    )
    usage = get_usage_metering().record_turn(
        context,
        session_id=conversation_id,
        goal_id=goal_id or "",
        capability_type=capability_type,
        prompt_tokens=int(merged.get("prompt_tokens") or 0),
        completion_tokens=int(merged.get("completion_tokens") or 0),
        estimated_cost=float(merged.get("turn_cost") or 0.0),
    )
    merged["enterprise_settlement"] = {
        "version": ADMISSION_VERSION,
        "response_id": response_id,
        "settled_at": datetime.now(UTC).isoformat(),
        "usage": usage.to_dict(),
        "billing_attribution": dict(merged.get("billing_attribution") or {}),
    }
    return merged
