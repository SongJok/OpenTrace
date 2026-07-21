"""Capability OS dispatch pipeline contract (phase 4)."""

from __future__ import annotations

from types import SimpleNamespace

class TestCapabilityDispatchPipeline:
    def test_validate_planned_capabilities_default_allowed(self):
        from kernel.capability_runtime.dispatch_pipeline import validate_planned_capabilities

        gate = validate_planned_capabilities(["model.answer", "web.search"])
        assert gate["allowed"] is True

    def test_record_capability_outcomes_no_crash(self):
        from kernel.capability_runtime.dispatch_pipeline import record_capability_outcomes

        results = [
            SimpleNamespace(
                capability_type="web.search",
                agent_type="web",
                status="ok",
                latency_ms=100,
                evidence_objects=[],
            )
        ]
        record_capability_outcomes(results, query_preview="test query")

    def test_collect_from_plan_subtasks(self):
        from kernel.capability_runtime.dispatch_pipeline import collect_planned_capability_types

        plan = SimpleNamespace(
            subtasks=[
                SimpleNamespace(capability_type="data.query"),
                SimpleNamespace(capability_type="rag.retrieve"),
            ]
        )
        caps = collect_planned_capability_types(plan, None)
        assert "data.query" in caps or "data_query" in str(caps)