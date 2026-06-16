"""DataAgentV2 Supervisor 契约测试 — 流水线结构、DAG 拓扑与配置开关。"""

import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class DataAgentV2SupervisorContractTests(unittest.TestCase):
    """Verify Supervisor exists, pipeline steps, and configuration gating."""

    def setUp(self):
        self.v2_dir = ROOT / "agents" / "data_agent_v2"

    # ── File existence ──────────────────────────────────────────────────

    def test_all_v2_files_exist(self):
        expected = [
            "__init__.py",
            "types.py",
            "supervisor.py",
            "dag_builder.py",
            "knowledge_retriever.py",
            "intent_agent.py",
            "entity_agent.py",
            "metric_agent.py",
            "time_reasoning_agent.py",
            "join_agent.py",
            "semantic_agent.py",
            "planner_agent.py",
            "sql_compiler_agent.py",
            "verification_agent.py",
            "reflection_agent.py",
            "error_classifier.py",
            "data_critic.py",
            "statistical_agent.py",
            "insight_agent.py",
            "visualization_agent.py",
            "skills_engine.py",
            "feedback_collector.py",
            "pattern_extractor.py",
            "knowledge_updater.py",
            "metric_refiner.py",
        ]
        for name in expected:
            path = self.v2_dir / name
            self.assertTrue(path.exists(), f"Missing: {path}")

    def test_type_definitions_exist(self):
        types_path = self.v2_dir / "types.py"
        txt = types_path.read_text()
        self.assertIn("class CognitiveContext", txt)
        self.assertIn("pack_cognitive_result", txt)
        self.assertIn("unpack_cognitive_context", txt)
        self.assertIn("learning_signals", txt)
        self.assertIn("statistical_report", txt)
        self.assertIn("insights", txt)
        self.assertIn("visualization_config", txt)

    def test_type_cognitive_context_fields(self):
        """Verify CognitiveContext has all layer-specific fields."""
        types_path = self.v2_dir / "types.py"
        txt = types_path.read_text()

        # Knowledge layer fields
        self.assertIn("matched_metrics", txt)
        self.assertIn("matched_skills", txt)
        self.assertIn("matched_relationships", txt)
        self.assertIn("column_semantics", txt)
        self.assertIn("pattern_hit", txt)

        # Reasoning layer fields
        self.assertIn("intent:", txt)
        self.assertIn("entities:", txt)
        self.assertIn("metrics:", txt)
        self.assertIn("time_window:", txt)
        self.assertIn("join_paths:", txt)
        self.assertIn("compiled_sql:", txt)

        # Learning layer fields
        self.assertIn("learning_signals:", txt)
        self.assertIn("refined_metrics:", txt)

        # Analytics fields
        self.assertIn("statistical_report:", txt)
        self.assertIn("insights:", txt)
        self.assertIn("visualization_config:", txt)

    # ── Config flags ────────────────────────────────────────────────────

    def test_all_feature_flags_defined(self):
        """Verify all 28 config flags exist in settings."""
        config_path = ROOT / "infra" / "config" / "settings.py"
        txt = config_path.read_text()

        expected_flags = [
            "data_agent_v2_enabled",
            "data_agent_v2_fallback_to_v1",
            "data_agent_v2_knowledge_retriever_enabled",
            "data_agent_v2_use_metric_definitions",
            "data_agent_v2_use_schema_metadata",
            "data_agent_v2_use_table_relationships",
            "data_agent_v2_use_analytical_skills",
            "data_agent_v2_intent_enabled",
            "data_agent_v2_entity_enabled",
            "data_agent_v2_metric_enabled",
            "data_agent_v2_time_enabled",
            "data_agent_v2_join_enabled",
            "data_agent_v2_semantic_enabled",
            "data_agent_v2_planner_enabled",
            "data_agent_v2_compiler_enabled",
            "data_agent_v2_verifier_enabled",
            "data_agent_v2_reflection_enabled",
            "data_agent_v2_dag_parallel_enabled",
            "data_agent_v2_supervisor_max_retries",
            "data_agent_v2_learning_enabled",
            "data_agent_v2_pattern_memory_enabled",
            "data_agent_v2_auto_metric_refinement_enabled",
            "data_agent_v2_auto_schema_enrichment_enabled",
            "data_agent_v2_statistical_enabled",
            "data_agent_v2_insight_enabled",
            "data_agent_v2_visualization_enabled",
            "data_agent_v2_skill_execution_enabled",
            "data_agent_v2_critic_enabled",
        ]
        for flag in expected_flags:
            self.assertIn(flag, txt, f"Missing config flag: {flag}")

    # ── Supervisor pipeline structure ───────────────────────────────────

    def test_supervisor_has_pipeline_steps(self):
        supervisor_path = self.v2_dir / "supervisor.py"
        txt = supervisor_path.read_text()

        step_markers = [
            "_run_knowledge_layer",
            "_run_reflection",
            "_apply_critic",
            "_expand_skills",
            "_run_advanced_analytics",
            "_run_agent",
            "_run_learning_pipeline",
            "_run_feedback_collector",
            "_run_pattern_extractor",
            "_run_knowledge_updater",
            "_build_final_result",
            "_compute_confidence",
        ]
        for marker in step_markers:
            self.assertIn(marker, txt, f"Missing pipeline step: {marker}")

    def test_supervisor_has_advanced_analytics(self):
        supervisor_path = self.v2_dir / "supervisor.py"
        txt = supervisor_path.read_text()
        self.assertIn("_run_advanced_analytics", txt)
        self.assertIn("StatisticalAgent", txt)
        self.assertIn("InsightAgent", txt)
        self.assertIn("VisualizationAgent", txt)
        self.assertIn("_expand_skills", txt)

    def test_supervisor_has_learning_pipeline(self):
        supervisor_path = self.v2_dir / "supervisor.py"
        txt = supervisor_path.read_text()
        self.assertIn("_run_learning_pipeline", txt)
        self.assertIn("_run_feedback_collector", txt)
        self.assertIn("_run_pattern_extractor", txt)
        self.assertIn("_run_knowledge_updater", txt)

    def test_supervisor_has_critic_integration(self):
        supervisor_path = self.v2_dir / "supervisor.py"
        txt = supervisor_path.read_text()
        self.assertIn("_apply_critic", txt)
        self.assertIn("critic", txt.lower())

    def test_supervisor_confidence_has_analytics_bonuses(self):
        supervisor_path = self.v2_dir / "supervisor.py"
        txt = supervisor_path.read_text()
        self.assertIn("statistical_report", txt)
        self.assertIn("insights", txt)

    # ── DAG topology ────────────────────────────────────────────────────

    def test_dag_builder_levels(self):
        dag_path = self.v2_dir / "dag_builder.py"
        txt = dag_path.read_text()
        self.assertIn("intent", txt.lower())
        self.assertIn("entity", txt.lower())
        self.assertIn("metric", txt.lower())
        self.assertIn("time", txt.lower())
        self.assertIn("join", txt.lower())
        self.assertIn("semantic", txt.lower())
        self.assertIn("planner", txt.lower())
        self.assertIn("compiler", txt.lower())
        self.assertIn("verification", txt.lower())

    def test_dag_builder_has_analytics_agents(self):
        dag_path = self.v2_dir / "dag_builder.py"
        txt = dag_path.read_text()
        self.assertIn("statistical", txt)
        self.assertIn("insight", txt)
        self.assertIn("visualization", txt)
        self.assertIn("skill_execution", txt)


if __name__ == "__main__":
    unittest.main()
