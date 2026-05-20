"""Unit tests for StatisticalAgent — fully deterministic agent with stats, outliers, trends."""

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.data_agent_v2.statistical_agent import StatisticalAgent
from agents.data_agent_v2.types import CognitiveContext


class StatisticalAgentUnitTests(unittest.TestCase):
    def setUp(self):
        self.agent = StatisticalAgent()

    # ── _find_numeric_columns ─────────────────────────────────────────

    def test_find_numeric_columns(self):
        rows = [
            {"id": 1, "name": "Alice", "amount": 99.5, "count": 3},
            {"id": 2, "name": "Bob", "amount": 150.0, "count": 5},
        ]
        cols = self.agent._find_numeric_columns(rows)
        self.assertIn("id", cols)
        self.assertIn("amount", cols)
        self.assertIn("count", cols)
        self.assertNotIn("name", cols)

    def test_find_numeric_columns_empty(self):
        self.assertEqual(self.agent._find_numeric_columns([]), [])

    # ── _find_dimension_columns ───────────────────────────────────────

    def test_find_dimension_columns(self):
        rows = [
            {"level": "VIP", "status": "active", "amount": 100},
            {"level": "NORMAL", "status": "active", "amount": 50},
            {"level": "VIP", "status": "pending", "amount": 200},
        ]
        dims = self.agent._find_dimension_columns(rows, ["amount"])
        self.assertIn("level", dims)
        self.assertIn("status", dims)
        self.assertNotIn("amount", dims)

    # ── _compute_stats ────────────────────────────────────────────────

    def test_compute_stats_uniform(self):
        stats = self.agent._compute_stats([10.0, 10.0, 10.0, 10.0])
        self.assertEqual(stats["count"], 4)
        self.assertEqual(stats["mean"], 10.0)
        self.assertEqual(stats["median"], 10.0)
        self.assertEqual(stats["std"], 0.0)
        self.assertEqual(stats["min"], 10.0)
        self.assertEqual(stats["max"], 10.0)

    def test_compute_stats_varied(self):
        stats = self.agent._compute_stats([5.0, 10.0, 15.0, 20.0])
        self.assertEqual(stats["count"], 4)
        self.assertEqual(stats["mean"], 12.5)
        self.assertEqual(stats["min"], 5.0)
        self.assertEqual(stats["max"], 20.0)
        self.assertAlmostEqual(stats["median"], 12.5)
        self.assertGreater(stats["std"], 0)

    def test_compute_stats_odd_count(self):
        stats = self.agent._compute_stats([1.0, 2.0, 100.0])
        self.assertEqual(stats["count"], 3)
        self.assertEqual(stats["median"], 2.0)

    def test_compute_stats_single_value(self):
        stats = self.agent._compute_stats([42.0])
        self.assertEqual(stats["count"], 1)
        self.assertEqual(stats["mean"], 42.0)
        self.assertEqual(stats["min"], 42.0)
        self.assertEqual(stats["max"], 42.0)

    def test_compute_stats_empty(self):
        self.assertEqual(self.agent._compute_stats([]), {})

    def test_compute_stats_percentiles(self):
        values = [float(i) for i in range(1, 101)]  # 1.0 .. 100.0
        stats = self.agent._compute_stats(values)
        self.assertAlmostEqual(stats["p25"], 25.75, delta=1)
        self.assertAlmostEqual(stats["p75"], 75.25, delta=1)
        self.assertAlmostEqual(stats["p95"], 95.05, delta=1)

    def test_compute_stats_cv(self):
        stats = self.agent._compute_stats([10.0, 12.0, 14.0, 16.0])
        self.assertGreater(stats["cv"], 0)
        self.assertLess(stats["cv"], 1)

    # ── _detect_outliers_iqr ──────────────────────────────────────────

    def test_detect_outliers_no_outliers(self):
        outliers = self.agent._detect_outliers_iqr([1.0, 2.0, 3.0, 4.0, 5.0])
        self.assertEqual(len(outliers), 0)

    def test_detect_outliers_has_outlier(self):
        outliers = self.agent._detect_outliers_iqr([10.0, 11.0, 12.0, 13.0, 100.0])
        self.assertEqual(len(outliers), 1)
        self.assertEqual(outliers[0][1], 100.0)

    def test_detect_outliers_low_outlier(self):
        outliers = self.agent._detect_outliers_iqr([-50.0, 10.0, 11.0, 12.0, 13.0])
        self.assertEqual(len(outliers), 1)
        self.assertEqual(outliers[0][1], -50.0)

    def test_detect_outliers_too_few_values(self):
        self.assertEqual(self.agent._detect_outliers_iqr([1.0, 2.0]), [])

    # ── _detect_trend ─────────────────────────────────────────────────

    def test_detect_trend_increasing(self):
        trend = self.agent._detect_trend([10.0, 20.0, 30.0, 40.0])
        self.assertEqual(trend["direction"], "increasing")
        self.assertGreater(trend["strength"], 0.5)

    def test_detect_trend_decreasing(self):
        trend = self.agent._detect_trend([40.0, 30.0, 20.0, 10.0])
        self.assertEqual(trend["direction"], "decreasing")
        self.assertGreater(trend["strength"], 0.5)

    def test_detect_trend_stable(self):
        trend = self.agent._detect_trend([10.0, 9.0, 11.0, 10.0])
        self.assertEqual(trend["direction"], "flat")

    def test_detect_trend_insufficient_data(self):
        trend = self.agent._detect_trend([1.0])
        self.assertEqual(trend["direction"], "insufficient_data")

    def test_detect_trend_change_pct(self):
        # Need at least 3 points for full trend analysis
        trend = self.agent._detect_trend([100.0, 110.0, 120.0])
        self.assertAlmostEqual(trend["change_pct"], 20.0, delta=1)

    def test_detect_trend_fields_exist(self):
        trend = self.agent._detect_trend([10.0, 15.0, 12.0, 18.0])
        for field in ("direction", "strength", "strength_label", "slope", "first_value", "last_value", "change_pct"):
            self.assertIn(field, trend, f"Missing field: {field}")

    # ── _compare_groups ───────────────────────────────────────────────

    def test_compare_groups(self):
        rows = [
            {"group": "A", "val": 100}, {"group": "A", "val": 120},
            {"group": "B", "val": 50}, {"group": "B", "val": 60},
        ]
        ctx = CognitiveContext(query="test")
        result = self.agent._compare_groups(rows, ["val"], ["group"], ctx)
        self.assertIn("group", result)
        self.assertIn("val", result["group"])
        comp = result["group"]["val"]
        self.assertIn("max_group", comp)
        self.assertIn("min_group", comp)
        self.assertIn("groups", comp)
        self.assertEqual(comp["max_group"], "A")  # A has mean 110 > B mean 55

    def test_compare_groups_single_group(self):
        rows = [{"g": "X", "v": 10}, {"g": "X", "v": 20}]
        ctx = CognitiveContext(query="test")
        result = self.agent._compare_groups(rows, ["v"], ["g"], ctx)
        self.assertEqual(result, {})

    def test_compare_groups_no_dimensions(self):
        rows = [{"v": 10}, {"v": 20}]
        ctx = CognitiveContext(query="test")
        result = self.agent._compare_groups(rows, ["v"], [], ctx)
        self.assertEqual(result, {})

    # ── _extract_numeric_values ───────────────────────────────────────

    def test_extract_numeric_values(self):
        rows = [{"x": 1.0}, {"x": 2.5}, {"x": None}, {"x": "3.5"}, {"x": True}]
        vals = self.agent._extract_numeric_values(rows, "x")
        self.assertEqual(vals, [1.0, 2.5, 3.5])

    def test_extract_numeric_values_all_none(self):
        vals = self.agent._extract_numeric_values([{"x": None}, {"x": None}], "x")
        self.assertEqual(vals, [])


if __name__ == "__main__":
    unittest.main()
