"""DataClarificationGate detect() 信号逻辑的单元测试。"""
import unittest


class ClarificationGateDetectionTests(unittest.TestCase):
    """Test the pure-signal vagueness detection without LLM calls."""

    def _make_ctx(self, **kwargs):
        """Build a minimal mock CognitiveContext for testing detect()."""
        from dataclasses import dataclass, field

        @dataclass
        class MockCtx:
            query: str = ""
            table_names: list = field(default_factory=list)
            table_columns: dict = field(default_factory=dict)
            intent: dict | None = None
            entities: list | None = None
            metrics: list | None = None

        defaults = {
            "query": "test query",
            "table_names": ["dim_user", "orders"],
            "intent": None,
            "entities": None,
            "metrics": None,
        }
        defaults.update(kwargs)
        return MockCtx(**defaults)

    def setUp(self):
        from kernel.clarification_gate import DataClarificationGate
        self.gate = DataClarificationGate()

    # ── Rule 1: no_entities AND no_metrics → must clarify ────────────────

    def test_empty_entities_and_metrics_triggers_clarification(self):
        ctx = self._make_ctx(
            query="帮我查一下数据",
            entities=[],
            metrics=[],
        )
        result = self.gate.detect(ctx)
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["reason"], "no_entities_and_no_metrics")

    def test_entities_with_no_mapped_table_triggers_clarification(self):
        ctx = self._make_ctx(
            query="看看最近情况",
            entities=[{"mention": "用户", "mapped_table": ""}],
            metrics=[],
        )
        result = self.gate.detect(ctx)
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["reason"], "no_entities_and_no_metrics")

    # ── Rule 2: no_entities AND generic pattern → clarify ────────────────

    def test_no_entities_with_generic_pattern_triggers_clarification(self):
        ctx = self._make_ctx(
            query="帮我看看数据有什么",
            entities=[],
            metrics=[
                {"mention": "数量", "mapped_column": "count", "agg": "COUNT"},
            ],
        )
        result = self.gate.detect(ctx)
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["reason"], "no_entities_and_generic")

    # ── Rule 3: low confidence AND raw_lookup → clarify ─────────────────

    def test_low_confidence_raw_lookup_triggers_clarification(self):
        ctx = self._make_ctx(
            query="查点东西",
            intent={"intent_type": "raw_lookup", "confidence": 0.3},
            entities=[
                {"mention": "用户", "mapped_table": "dim_user"},
            ],
            metrics=[],
        )
        result = self.gate.detect(ctx)
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["reason"], "low_confidence_raw_lookup")

    # ── Rule 4: analytical no table no dims → clarify ────────────────────

    def test_analytical_no_entities_no_dimensions_triggers_clarification(self):
        ctx = self._make_ctx(
            query="统计一下分布情况",
            intent={
                "intent_type": "distribution",
                "confidence": 0.85,
                "dimensions": [],
            },
            entities=[],
            metrics=[],
        )
        result = self.gate.detect(ctx)
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["reason"], "analytical_no_table_no_dims")

    # ── Non-trigger: query is clear enough ───────────────────────────────

    def test_clear_query_does_not_trigger_clarification(self):
        ctx = self._make_ctx(
            query="统计 dim_user 表中各 grade_name 的用户数量",
            intent={
                "intent_type": "aggregation",
                "confidence": 0.85,
                "dimensions": ["grade_name"],
            },
            entities=[
                {"mention": "用户", "mapped_table": "dim_user"},
            ],
            metrics=[
                {"mention": "数量", "mapped_column": "id", "agg": "COUNT"},
            ],
        )
        result = self.gate.detect(ctx)
        self.assertFalse(result["needs_clarification"])

    def test_entities_present_no_metrics_but_not_generic_does_not_trigger(self):
        """Having entities but no metrics is OK if not a generic pattern."""
        ctx = self._make_ctx(
            query="查看 dim_user 表的所有数据",
            intent={
                "intent_type": "raw_lookup",
                "confidence": 0.7,
            },
            entities=[
                {"mention": "dim_user", "mapped_table": "dim_user"},
            ],
            metrics=[],
        )
        result = self.gate.detect(ctx)
        self.assertFalse(result["needs_clarification"])

    # ── Signal extraction ────────────────────────────────────────────────

    def test_signals_include_all_dimensions(self):
        ctx = self._make_ctx(
            query="hi",
            entities=[],
            metrics=[],
            intent={"intent_type": "raw_lookup", "confidence": 0.3},
        )
        result = self.gate.detect(ctx)
        for key in ("no_entities", "no_metrics", "low_intent_confidence",
                     "raw_lookup_intent", "too_short", "generic_pattern"):
            self.assertIn(key, result, f"Signal {key} missing from detect result")

    def test_too_short_detection(self):
        ctx = self._make_ctx(query="查", entities=[], metrics=[])
        result = self.gate.detect(ctx)
        self.assertTrue(result["too_short"])

    def test_too_short_but_has_entities_does_not_trigger(self):
        ctx = self._make_ctx(
            query="查表",
            entities=[{"mention": "dim_user", "mapped_table": "dim_user"}],
            metrics=[],
        )
        result = self.gate.detect(ctx)
        # too_short is true but no_entities is false → no trigger
        self.assertTrue(result["too_short"])
        self.assertFalse(result["needs_clarification"])


if __name__ == "__main__":
    unittest.main()
