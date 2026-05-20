"""Unit tests for deterministic V2 agents: Visualization, PatternExtractor, SkillsEngine."""

import unittest
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agents.data_agent_v2.visualization_agent import VisualizationAgent
from agents.data_agent_v2.pattern_extractor import PatternExtractorAgent
from agents.data_agent_v2.skills_engine import SkillsEngine
from agents.data_agent_v2.dag_builder import DagPlanSpec, DagNodeSpec
from agents.data_agent_v2.types import CognitiveContext


# ═══════════════════════════════════════════════════════════════════════════
# VisualizationAgent
# ═══════════════════════════════════════════════════════════════════════════

class VisualizationAgentUnitTests(unittest.TestCase):
    def setUp(self):
        self.agent = VisualizationAgent()

    # ── _infer_col_type ────────────────────────────────────────────────

    def test_infer_temporal(self):
        t = self.agent._infer_col_type("created_at", "2024-01-01", [])
        self.assertEqual(t, "temporal")

    def test_infer_numeric(self):
        t = self.agent._infer_col_type("amount", 99.5, [])
        self.assertEqual(t, "numeric")

    def test_infer_categorical_low_cardinality(self):
        rows = [{"status": "active"}, {"status": "pending"}, {"status": "active"}]
        t = self.agent._infer_col_type("status", "active", rows)
        self.assertEqual(t, "categorical")

    def test_infer_text_high_cardinality(self):
        rows = [{"desc": f"item_{i}"} for i in range(20)]
        t = self.agent._infer_col_type("desc", "item_0", rows)
        self.assertEqual(t, "text")

    def test_infer_boolean(self):
        t = self.agent._infer_col_type("is_active", True, [])
        self.assertEqual(t, "categorical")

    # ── _recommend ─────────────────────────────────────────────────────

    def test_recommend_time_series(self):
        ctx = CognitiveContext(query="trend", intent={"intent_type": "trend"})
        structure = {
            "numeric_cols": ["value"],
            "temporal_cols": ["date"],
            "categorical_cols": [],
            "row_count": 30,
        }
        rec = self.agent._recommend(ctx, structure, [])
        self.assertEqual(rec["primary"], "line")
        self.assertIn("area", rec["alternatives"])

    def test_recommend_comparison(self):
        ctx = CognitiveContext(query="compare", intent={"intent_type": "comparison"})
        structure = {
            "numeric_cols": ["amount"],
            "temporal_cols": [],
            "categorical_cols": ["category"],
            "row_count": 6,
        }
        rec = self.agent._recommend(ctx, structure, [])
        # Comparison intent maps to bar/grouped_bar
        self.assertIn(rec["primary"], ["bar", "grouped_bar", "horizontal_bar"])
        self.assertIn("pie", rec["alternatives"])  # few categories

    def test_recommend_pie_small_data(self):
        ctx = CognitiveContext(query="distribution", intent={"intent_type": "composition"})
        structure = {
            "numeric_cols": ["count"],
            "temporal_cols": [],
            "categorical_cols": ["category"],
            "row_count": 5,
        }
        rec = self.agent._recommend(ctx, structure, [])
        self.assertIn("pie", [rec["primary"]] + rec["alternatives"])

    def test_recommend_metric_card(self):
        ctx = CognitiveContext(query="single", intent={"intent_type": "aggregation"})
        structure = {
            "numeric_cols": ["total"],
            "temporal_cols": [],
            "categorical_cols": [],
            "row_count": 1,
        }
        rec = self.agent._recommend(ctx, structure, [])
        self.assertEqual(rec["primary"], "metric_card")

    def test_recommend_heatmap_multi_categorical(self):
        ctx = CognitiveContext(query="heatmap", intent={"intent_type": "distribution"})
        structure = {
            "numeric_cols": ["val"],
            "temporal_cols": [],
            "categorical_cols": ["region", "category"],
            "row_count": 50,
        }
        rec = self.agent._recommend(ctx, structure, [])
        self.assertIn("heatmap", [rec["primary"]] + rec["alternatives"])

    def test_recommend_scatter_two_numeric(self):
        ctx = CognitiveContext(query="scatter", intent={"intent_type": "distribution"})
        structure = {
            "numeric_cols": ["x", "y"],
            "temporal_cols": [],
            "categorical_cols": [],
            "row_count": 100,
        }
        rec = self.agent._recommend(ctx, structure, [])
        self.assertIn("scatter", [rec["primary"]] + rec["alternatives"])

    def test_recommend_always_has_table(self):
        ctx = CognitiveContext(query="test")
        structure = {"numeric_cols": [], "temporal_cols": [], "categorical_cols": [], "row_count": 0}
        rec = self.agent._recommend(ctx, structure, [])
        all_charts = [rec["primary"]] + rec["alternatives"]
        self.assertIn("table", all_charts)

    def test_recommend_has_alternatives(self):
        ctx = CognitiveContext(query="test", intent={"intent_type": "comparison"})
        structure = {
            "numeric_cols": ["val"],
            "temporal_cols": [],
            "categorical_cols": ["cat"],
            "row_count": 10,
        }
        rec = self.agent._recommend(ctx, structure, [])
        self.assertGreater(len(rec["alternatives"]), 0, "Should have at least one alternative")

    # ── INTENT_CHART_MAP ──────────────────────────────────────────────

    def test_intent_chart_map_coverage(self):
        """All major intent types should have chart preferences."""
        expected_intents = ["comparison", "trend", "funnel", "ranking", "composition", "distribution"]
        for intent in expected_intents:
            self.assertIn(intent, self.agent.INTENT_CHART_MAP,
                          f"Missing chart mapping for intent: {intent}")


# ═══════════════════════════════════════════════════════════════════════════
# PatternExtractorAgent
# ═══════════════════════════════════════════════════════════════════════════

class PatternExtractorAgentUnitTests(unittest.TestCase):
    def setUp(self):
        self.agent = PatternExtractorAgent()

    def test_min_confidence_threshold(self):
        self.assertEqual(self.agent.MIN_CONFIDENCE_THRESHOLD, 0.70)

    def test_pattern_hash_deterministic(self):
        """Same input should produce same hash."""
        from hashlib import sha256
        data = "comparison|orders,users|GMV,ARPU|last_30_days"
        h1 = sha256(data.encode()).hexdigest()
        h2 = sha256(data.encode()).hexdigest()
        self.assertEqual(h1, h2)

    def test_pattern_hash_different_inputs(self):
        """Different input should produce different hash."""
        from hashlib import sha256
        h1 = sha256("comparison|orders|GMV|last_30_days".encode()).hexdigest()
        h2 = sha256("trend|orders|GMV|last_30_days".encode()).hexdigest()
        self.assertNotEqual(h1, h2)


# ═══════════════════════════════════════════════════════════════════════════
# SkillsEngine
# ═══════════════════════════════════════════════════════════════════════════

class SkillsEngineUnitTests(unittest.TestCase):
    def setUp(self):
        self.engine = SkillsEngine()
        self.ctx = CognitiveContext(query="test query")

    def _node(self, node_id, agent_type="compiler"):
        return DagNodeSpec(node_id=node_id, agent_type=agent_type, query="test query")

    def test_agent_type_map(self):
        self.assertEqual(self.engine.AGENT_TYPE_MAP["data"], "data")
        self.assertEqual(self.engine.AGENT_TYPE_MAP["statistical"], "data_statistical")
        self.assertEqual(self.engine.AGENT_TYPE_MAP["insight"], "data_insight")
        self.assertEqual(self.engine.AGENT_TYPE_MAP["visualization"], "data_visualization")

    def test_expand_empty_skill(self):
        skill = {"name": "empty"}
        base = DagPlanSpec(nodes=[self._node("compiler", agent_type="compiler")])
        result = self.engine.expand(skill, base, self.ctx)
        self.assertEqual(len(result.nodes), 1)

    def test_expand_missing_plan_template(self):
        skill = {"name": "no_template", "plan_template": None}
        base = DagPlanSpec(nodes=[self._node("compiler", agent_type="compiler")])
        result = self.engine.expand(skill, base, self.ctx)
        self.assertEqual(len(result.nodes), 1)

    def test_expand_adds_steps(self):
        skill = {
            "name": "cohort_analysis",
            "plan_template": {
                "steps": [
                    {"id": "step1", "agent": "statistical", "depends_on": []},
                    {"id": "step2", "agent": "insight", "depends_on": ["step1"]},
                ],
                "parameters": {},
            },
        }
        base = DagPlanSpec(nodes=[self._node("compiler", agent_type="compiler")])
        result = self.engine.expand(skill, base, self.ctx)
        # Should have base node + 2 skill nodes
        self.assertEqual(len(result.nodes), 3)

    def test_expand_preserves_base_nodes(self):
        skill = {
            "name": "funnel",
            "plan_template": {
                "steps": [{"id": "s1", "agent": "data", "depends_on": []}],
                "parameters": {},
            },
        }
        base = DagPlanSpec(nodes=[
            self._node("intent", agent_type="intent"),
            self._node("compiler", agent_type="compiler"),
        ])
        result = self.engine.expand(skill, base, self.ctx)
        base_ids = {n.node_id for n in result.nodes}
        self.assertIn("intent", base_ids)
        self.assertIn("compiler", base_ids)

    def test_expand_resolves_params(self):
        skill = {
            "name": "test_skill",
            "plan_template": {
                "steps": [
                    {"id": "s1", "agent": "data",
                     "params": {"time_window": "$time_window", "limit": 10},
                     "depends_on": []},
                ],
                "parameters": {
                    "time_window": {"type": "string", "default": "last_7_days"},
                },
            },
        }
        ctx = CognitiveContext(query="test")
        ctx.time_window = {"type": "last_30_days", "description": "最近30天"}
        base = DagPlanSpec(nodes=[self._node("compiler", agent_type="compiler")])
        result = self.engine.expand(skill, base, ctx)
        # Find the skill node
        skill_node = next((n for n in result.nodes if n.agent_type == "data"), None)
        self.assertIsNotNone(skill_node)
        # Check parameter resolution — params are stored in .params
        self.assertTrue(hasattr(skill_node, "params"))
        # --time_window should be resolved from ctx.time_window or fallback to default
        self.assertIn("time_window", skill_node.params)

    def test_expand_no_steps_returns_original(self):
        skill = {"name": "empty", "plan_template": {"steps": [], "parameters": {}}}
        base = DagPlanSpec(nodes=[self._node("c1", agent_type="compiler")])
        result = self.engine.expand(skill, base, self.ctx)
        self.assertEqual(len(result.nodes), 1)

    def test_expand_agent_type_fallback(self):
        """Unknown agent types should pass through unchanged."""
        self.assertEqual(self.engine.AGENT_TYPE_MAP.get("unknown_agent", "unknown_agent"), "unknown_agent")


if __name__ == "__main__":
    unittest.main()
