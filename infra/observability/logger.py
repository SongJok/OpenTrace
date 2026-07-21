"""
Structured logger — gracefully degrades to stdlib if structlog not installed.
"""
from __future__ import annotations

import logging
import re
import sys
from typing import Any

from infra.observability.request_context import get_log_context

_STRUCTLOG_AVAILABLE = False
try:
    import structlog
    _STRUCTLOG_AVAILABLE = True
except ImportError:
    pass


_SENSITIVE_KEYS = {"password", "token", "authorization", "api_key", "secret"}


def _mask_sensitive(v: Any) -> Any:
    if isinstance(v, dict):
        out = {}
        for k, val in v.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = "***"
            else:
                out[k] = _mask_sensitive(val)
        return out
    if isinstance(v, list):
        return [_mask_sensitive(x) for x in v]
    if isinstance(v, str):
        # best-effort token masking
        return re.sub(r"(Bearer\s+)[A-Za-z0-9\-\._~\+/]+=*", r"\1***", v)
    return v


def _inject_request_context(logger: Any, method: str, event_dict: dict) -> dict:
    event_dict.update({k: v for k, v in get_log_context().items() if v})
    return event_dict


def _add_otel_trace_id(logger: Any, method: str, event_dict: dict) -> dict:
    try:
        from opentelemetry import trace
        span = trace.get_current_span()
        ctx = span.get_span_context()
        if ctx.is_valid:
            event_dict.setdefault("trace_id", format(ctx.trace_id, "032x"))
            event_dict.setdefault("span_id", format(ctx.span_id, "016x"))
    except Exception:  # noqa: BLE001
        pass
    return event_dict


def _mask_processor(logger: Any, method: str, event_dict: dict) -> dict:
    return _mask_sensitive(event_dict)


def configure_logging(level: str = "INFO", json_logs: bool = True) -> None:
    log_level = logging.getLevelName(level)
    logging.basicConfig(
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    if not _STRUCTLOG_AVAILABLE:
        return

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        _inject_request_context,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_otel_trace_id,
        _mask_processor,
        structlog.processors.StackInfoRenderer(),
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if json_logs
        else structlog.dev.ConsoleRenderer(colors=False)
    )

    structlog.configure(
        processors=shared_processors + [renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    if not _STRUCTLOG_AVAILABLE:
        return logging.getLogger(name)
    return structlog.get_logger(name)
