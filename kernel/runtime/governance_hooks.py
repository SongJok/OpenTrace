"""Helpers to record runtime degradation on RuntimeContext / request metadata."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from infra.observability.runtime_degraded import record_runtime_degradation

logger = get_logger(__name__)


def metadata_sink_from_ctx(ctx: Any) -> dict[str, Any] | None:
    if ctx is None:
        return None
    md = getattr(ctx, "metadata", None)
    if md is None:
        try:
            ctx.metadata = {}
            md = ctx.metadata
        except Exception:
            return None
    if not isinstance(md, dict):
        return None
    return md


def degrade_ctx(
    ctx: Any,
    *,
    subsystem: str,
    detail: str,
    exc: BaseException | None = None,
) -> None:
    """Append structured degradation to ctx.metadata.semantic_observability."""
    md = metadata_sink_from_ctx(ctx)
    if md is not None:
        record_runtime_degradation(md, subsystem=subsystem, detail=detail, exc=exc)
    elif exc is not None:
        logger.warning("runtime_degradation_no_ctx", subsystem=subsystem, detail=detail, error=str(exc))
    else:
        logger.warning("runtime_degradation_no_ctx", subsystem=subsystem, detail=detail)


def degrade_request_meta(
    request: Any,
    *,
    subsystem: str,
    detail: str,
    exc: BaseException | None = None,
) -> dict[str, Any]:
    """Ensure request.metadata exists and record degradation; return metadata dict."""
    md = dict(getattr(request, "metadata", None) or {})
    record_runtime_degradation(md, subsystem=subsystem, detail=detail, exc=exc)
    try:
        request.metadata = md
    except Exception as exc:
        logger.warning("degrade_request_meta_assign_failed", error=str(exc))
    return md