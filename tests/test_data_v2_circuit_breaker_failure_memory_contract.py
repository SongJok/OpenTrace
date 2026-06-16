"""Data V2 low-confidence circuit breaker records failure_memory."""

from __future__ import annotations

from agents.data_agent_v2.types import LowConfidenceError
from kernel.agent_runtime.data_v2_failure_memory import (
    CIRCUIT_BREAKER_FAILURE_TYPE,
    record_data_v2_circuit_breaker,
)
from kernel.capability_intelligence.failure_memory import failure_memory


def test_circuit_breaker_records_failure_memory():
    failure_memory.reset()
    record_data_v2_circuit_breaker(
        query="各渠道销售额",
        confidence=0.2,
        threshold=0.4,
        detail="sql=True rows=0",
        data_source_id="ds-1",
        trace_id="tr-1",
        latency_ms=100,
    )
    stats = failure_memory.get_stats("data_query")
    assert stats.total_failures >= 1
    recent = failure_memory.get_recent_failures("data_query", window_seconds=3600)
    assert any(r.failure_type == CIRCUIT_BREAKER_FAILURE_TYPE for r in recent)


def test_low_confidence_error_shape():
    exc = LowConfidenceError(0.1, 0.4, detail="test")
    assert exc.confidence == 0.1
    assert exc.threshold == 0.4