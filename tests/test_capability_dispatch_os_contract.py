"""Capability dispatch records Capability OS SLA."""

from __future__ import annotations

from types import SimpleNamespace

from kernel.capability_runtime.capability_os import get_capability_os
from kernel.capability_runtime.dispatch_pipeline import record_capability_outcomes


class TestCapabilityDispatchOS:
    def test_record_outcomes_updates_sla(self):
        os = get_capability_os()
        cap = "document_retrieval"
        before = os.get_product_state(cap)
        assert before is not None
        record_capability_outcomes(
            [
                SimpleNamespace(
                    agent_type="rag",
                    status="success",
                    latency_ms=120,
                    cost=0.05,
                    evidence_objects=[],
                )
            ],
            query_preview="test",
        )
        after = os.get_product_state(cap)
        assert after is not None
        assert after.sla.avg_latency_ms >= 0