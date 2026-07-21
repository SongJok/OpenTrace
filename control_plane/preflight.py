"""HTTP/API preflight — re-export control plane gate for gateway."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from kernel.cognitive_supervisor.control_plane_gate import (
    evaluate_request_control_plane,
    evaluate_request_control_plane_async,
)

logger = get_logger(__name__)


def preflight_kernel_request(request: Any) -> dict[str, Any]:
    """Evaluate tenant quota/compliance before kernel.run."""
    return evaluate_request_control_plane(request)


def preflight_from_metadata(
    *,
    user_id: str | None,
    session_id: str | None,
    metadata: dict[str, Any],
    query: str = "",
) -> dict[str, Any]:
    """Build a minimal request namespace for gate evaluation."""
    from types import SimpleNamespace

    md = dict(metadata)
    if query and not md.get("pii_detected"):
        try:
            from governance.pii_detector import detect_pii_signals

            sig = detect_pii_signals(query)
            md["pii_detected"] = sig.detected
            md["pii_types"] = list(sig.types)
        except Exception as exc:
            logger.warning("preflight_pii_scan_skipped", error=str(exc))
    req = SimpleNamespace(
        user_id=user_id,
        session_id=session_id,
        metadata=md,
    )
    return preflight_kernel_request(req)


async def preflight_from_metadata_async(
    *,
    user_id: str | None,
    session_id: str | None,
    metadata: dict[str, Any],
    query: str = "",
) -> dict[str, Any]:
    """Async preflight — Redis-backed quota when enterprise_quota_redis_enabled."""
    from types import SimpleNamespace

    md = dict(metadata)
    if query and not md.get("pii_detected"):
        try:
            from governance.pii_detector import detect_pii_signals

            sig = detect_pii_signals(query)
            md["pii_detected"] = sig.detected
            md["pii_types"] = list(sig.types)
        except Exception as exc:
            logger.warning("preflight_pii_scan_skipped", error=str(exc))
    req = SimpleNamespace(user_id=user_id, session_id=session_id, metadata=md)
    return await evaluate_request_control_plane_async(req)