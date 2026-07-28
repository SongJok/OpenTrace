"""
OpenTelemetry bootstrap — fully optional, gracefully degrades if not installed.
"""

from __future__ import annotations

import functools
import logging
from typing import Any

logger = logging.getLogger(__name__)

_OTEL_AVAILABLE = False
try:
    from opentelemetry import trace as _ot_trace
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.trace.sampling import ALWAYS_ON, ParentBased

    _OTEL_AVAILABLE = True
except ImportError:
    pass

_provider: Any = None


# ---------------------------------------------------------------------------
# No-op span / tracer for when OTel is not available
# ---------------------------------------------------------------------------
class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class _NoopTracer:
    def start_as_current_span(self, name: str, **kwargs):
        return _NoopSpan()


def setup_tracing(
    service_name: str = "opentrace",
    otlp_endpoint: str = "http://localhost:4317",
    enabled: bool = True,
    console_fallback: bool = False,
) -> Any:
    global _provider
    if not _OTEL_AVAILABLE:
        logger.info("OpenTelemetry not installed — tracing disabled")
        return None

    resource = Resource(attributes={SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource, sampler=ParentBased(root=ALWAYS_ON))

    if enabled:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            logger.info("OTLP tracing enabled → %s", otlp_endpoint)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OTLP exporter failed (%s); tracing disabled.", exc)
            return None

    _ot_trace.set_tracer_provider(provider)
    _provider = provider
    return provider


def get_tracer(name: str) -> Any:
    """Return a named tracer, or a no-op tracer if OTel is unavailable."""
    if not _OTEL_AVAILABLE:
        return _NoopTracer()
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except Exception:
        return _NoopTracer()


def get_current_span() -> Any:
    if not _OTEL_AVAILABLE:
        return _NoopSpan()
    try:
        from opentelemetry import trace

        return trace.get_current_span()
    except Exception:
        return _NoopSpan()


def traced_async(span_name: str):
    """为异步边界创建 OTel span；无 SDK 时保持零开销兼容。"""

    def decorator(func):
        @functools.wraps(func)
        async def wrapped(*args, **kwargs):
            with get_tracer(func.__module__).start_as_current_span(span_name) as span:
                try:
                    return await func(*args, **kwargs)
                except Exception as exc:
                    if hasattr(span, "record_exception"):
                        span.record_exception(exc)
                    raise

        return wrapped

    return decorator
