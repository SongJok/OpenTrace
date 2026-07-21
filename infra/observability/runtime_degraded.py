"""Record non-fatal runtime failures into turn metadata (governance must not fail silently)."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger

logger = get_logger(__name__)


def append_turn_degradation(
    semantic_observability: dict[str, Any] | None,
    *,
    subsystem: str,
    detail: str,
    exc: BaseException | None = None,
) -> None:
    """Append to semantic_observability.degradations (GovernanceCenter turn bundle)."""
    msg = detail if not exc else f"{detail}: {exc}"
    logger.warning("runtime_degradation", subsystem=subsystem, detail=msg)
    if not isinstance(semantic_observability, dict):
        return
    trail = semantic_observability.setdefault("degradations", [])
    if not isinstance(trail, list):
        trail = []
        semantic_observability["degradations"] = trail
    entry: dict[str, Any] = {"subsystem": subsystem, "detail": msg[:500]}
    if exc is not None:
        entry["error_type"] = type(exc).__name__
    trail.append(entry)
    if len(trail) > 32:
        semantic_observability["degradations"] = trail[-32:]


def record_runtime_degradation(
    meta_out: dict[str, Any] | None,
    *,
    subsystem: str,
    detail: str,
    exc: BaseException | None = None,
) -> None:
    """Append structured degradation entry; also logs at warning."""
    msg = detail if not exc else f"{detail}: {exc}"
    logger.warning("runtime_degradation", subsystem=subsystem, detail=msg)
    if not isinstance(meta_out, dict):
        return
    obs = meta_out.setdefault("semantic_observability", {})
    if not isinstance(obs, dict):
        return
    trail = obs.setdefault("degradations", [])
    if not isinstance(trail, list):
        trail = []
        obs["degradations"] = trail
    entry = {"subsystem": subsystem, "detail": msg[:500]}
    if exc is not None:
        entry["error_type"] = type(exc).__name__
    trail.append(entry)
    if len(trail) > 32:
        obs["degradations"] = trail[-32:]


def merge_degradations_into_context(ctx: Any, meta_out: dict[str, Any]) -> None:
    """Copy degradation trail onto RuntimeContext.metadata for downstream governance."""
    if ctx is None:
        return
    try:
        obs = meta_out.get("semantic_observability") or {}
        deg = obs.get("degradations") if isinstance(obs, dict) else None
        if not deg:
            return
        md = getattr(ctx, "metadata", None) or {}
        if not isinstance(md, dict):
            return
        ctx.metadata = md
        ctx_obs = md.setdefault("semantic_observability", {})
        if isinstance(ctx_obs, dict):
            existing = ctx_obs.get("degradations") or []
            if isinstance(existing, list):
                ctx_obs["degradations"] = (existing + list(deg))[-32:]
    except Exception as exc:
        logger.warning("merge_degradations_failed", error=str(exc))


def record_degradation_in_context(
    ctx: Any,
    *,
    subsystem: str,
    detail: str,
    exc: BaseException | None = None,
) -> None:
    """Append degradation to RuntimeContext.metadata.semantic_observability."""
    if ctx is None:
        record_runtime_degradation(None, subsystem=subsystem, detail=detail, exc=exc)
        return
    md = getattr(ctx, "metadata", None)
    if not isinstance(md, dict):
        try:
            ctx.metadata = {}
            md = ctx.metadata
        except Exception:
            record_runtime_degradation(None, subsystem=subsystem, detail=detail, exc=exc)
            return
    record_runtime_degradation(md, subsystem=subsystem, detail=detail, exc=exc)


def record_degradation_or_log(
    meta_out: dict[str, Any] | None,
    *,
    subsystem: str,
    detail: str,
    exc: BaseException | None = None,
    ctx: Any | None = None,
) -> None:
    """Prefer meta_out; fall back to ctx.metadata; always logs."""
    if isinstance(meta_out, dict):
        record_runtime_degradation(meta_out, subsystem=subsystem, detail=detail, exc=exc)
    elif ctx is not None:
        record_degradation_in_context(ctx, subsystem=subsystem, detail=detail, exc=exc)
    else:
        record_runtime_degradation(None, subsystem=subsystem, detail=detail, exc=exc)