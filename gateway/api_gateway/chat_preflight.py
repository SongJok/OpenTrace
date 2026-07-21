"""Shared chat preflight — PII + control plane (sync + stream)."""

from __future__ import annotations

import json
from typing import Any

from infra.errors import AppException, ErrorCodes
from infra.observability.logger import get_logger

logger = get_logger(__name__)


def run_chat_preflight(
    *,
    query: str,
    user_id: str,
    session_id: str,
    tenant_md: dict[str, Any],
) -> dict[str, Any]:
    """Mutates tenant_md with PII flags; raises AppException on policy denial."""
    md = dict(tenant_md)
    try:
        from governance.pii_detector import detect_pii_signals

        sig = detect_pii_signals(query)
        if sig.detected:
            md["pii_detected"] = True
            md["pii_types"] = list(sig.types)
    except Exception as exc:
        logger.warning("chat_preflight_pii_scan_skipped", error=str(exc))

    from control_plane.preflight import preflight_from_metadata

    pf = preflight_from_metadata(
        user_id=user_id,
        session_id=session_id or "",
        metadata=md,
        query=query,
    )
    if not pf.get("allowed", True):
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message=json.dumps(
                {
                    "policy_denied": True,
                    "control_plane": pf,
                    "violations": pf.get("violations") or [],
                },
                ensure_ascii=False,
            ),
        )
    return md


async def run_chat_preflight_async(
    *,
    query: str,
    user_id: str,
    session_id: str,
    tenant_md: dict[str, Any],
) -> dict[str, Any]:
    """Async variant — Redis-backed control plane quota when enabled."""
    md = dict(tenant_md)
    try:
        from governance.pii_detector import detect_pii_signals

        sig = detect_pii_signals(query)
        if sig.detected:
            md["pii_detected"] = True
            md["pii_types"] = list(sig.types)
    except Exception as exc:
        logger.warning("chat_preflight_pii_scan_skipped", error=str(exc))

    from control_plane.preflight import preflight_from_metadata_async

    pf = await preflight_from_metadata_async(
        user_id=user_id,
        session_id=session_id or "",
        metadata=md,
        query=query,
    )
    if not pf.get("allowed", True):
        raise AppException(
            ErrorCodes.PARAM_INVALID.code,
            message=json.dumps(
                {
                    "policy_denied": True,
                    "control_plane": pf,
                    "violations": pf.get("violations") or [],
                },
                ensure_ascii=False,
            ),
        )
    return md