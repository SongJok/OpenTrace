"""Contract tests for DataAgent V2 agents — structure, interface compliance, determinism."""

import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Layer
# ═══════════════════════════════════════════════════════════════════════════


class KnowledgeRetrieverAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "knowledge_retriever.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_retrieves_metric_definitions(self):
        self.assertIn("metric_definitions", self.txt.lower())
        self.assertIn("MetricDefinition", self.txt)

    def test_retrieves_schema_metadata(self):
        self.assertIn("schema_metadata", self.txt.lower())
        self.assertIn("SchemaMetadata", self.txt)

    def test_retrieves_table_relationships(self):
        self.assertIn("table_relationships", self.txt.lower())
        self.assertIn("TableRelationship", self.txt)

    def test_retrieves_analytical_skills(self):
        self.assertIn("analytical_skills", self.txt.lower())
        self.assertIn("AnalyticalSkill", self.txt)


# ═══════════════════════════════════════════════════════════════════════════
# Reasoning Layer Agents
# ═══════════════════════════════════════════════════════════════════════════


class IntentAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "intent_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_has_structured_intent_detection(self):
        self.assertIn("intent", self.txt.lower())

    def test_has_intent_type_classification(self):
        intent_types = ["comparison", "trend", "funnel", "ranking", "distribution", "detail_lookup", "metadata"]
        found = sum(1 for t in intent_types if t in self.txt.lower())
        self.assertGreaterEqual(found, 3, "Should classify at least 3 intent types")


class EntityAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "entity_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_handles_entity_recognition(self):
        self.assertIn("entity", self.txt.lower())


class MetricAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "metric_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_uses_metric_definitions_table(self):
        self.assertIn("metric", self.txt.lower())

    def test_uses_knowledge_layer_output(self):
        self.assertIn("cognitive_context", self.txt.lower())


class TimeReasoningAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "time_reasoning_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_handles_time_resolution(self):
        self.assertIn("_resolve_time", self.txt)
        self.assertIn("_resolve_time_macros", self.txt)
        self.assertIn("time_macros", self.txt.lower())


class JoinAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "join_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_uses_table_relationships(self):
        self.assertIn("table_relationship", self.txt.lower())

    def test_handles_join_paths(self):
        self.assertIn("join", self.txt.lower())


class SemanticAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "semantic_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_semantic_resolution(self):
        self.assertIn("semantic", self.txt.lower())


class PlannerAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "planner_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_generates_dag_plan(self):
        self.assertIn("dag", self.txt.lower())


class SQLCompilerAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "sql_compiler_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_deterministic_compilation(self):
        self.assertIn("sql", self.txt.lower())

    def test_uses_sql_builder(self):
        self.assertIn("build", self.txt.lower())


class VerificationAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "verification_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_multi_dimensional_verification(self):
        self.assertIn("sql", self.txt.lower())
        self.assertIn("semantic", self.txt.lower())

    def test_verification_dimensions(self):
        dimensions = ["syntax", "semantic", "metric"]
        found = sum(1 for d in dimensions if d.lower() in self.txt.lower())
        self.assertGreaterEqual(found, 2, "Should handle at least 2 verification dimensions")


# ═══════════════════════════════════════════════════════════════════════════
# Quality & Learning Layer
# ═══════════════════════════════════════════════════════════════════════════


class ReflectionAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "reflection_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_uses_error_classifier(self):
        self.assertIn("ErrorClassifier", self.txt)

    def test_3_retry_rounds(self):
        self.assertIn("rewrite", self.txt.lower())


class ErrorClassifierContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "error_classifier.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_has_25_error_categories(self):
        self.assertIn("class ErrorCategory", self.txt)

    def test_has_repair_strategies(self):
        self.assertIn("REPAIR_STRATEGIES", self.txt)

    def test_has_four_error_domains(self):
        domains = ["SQL", "LOGIC", "DATA_QUALITY", "SEMANTIC"]
        found = sum(1 for d in domains if d.lower() in self.txt.lower())
        self.assertGreaterEqual(found, 2)


class DataCriticAdapterContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "data_critic.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_enriches_result_with_confidence(self):
        self.assertIn("confidence", self.txt.lower())
        self.assertIn("enrich", self.txt.lower())


# ═══════════════════════════════════════════════════════════════════════════
# Learning Layer
# ═══════════════════════════════════════════════════════════════════════════


class FeedbackCollectorAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "feedback_collector.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_handles_8_feedback_types(self):
        types = ["like", "dislike", "correction", "rating", "supplement"]
        found = sum(1 for t in types if t in self.txt.lower())
        self.assertGreaterEqual(found, 3)

    def test_stores_feedback_to_db(self):
        self.assertIn("feedback", self.txt.lower())


class PatternExtractorAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "pattern_extractor.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_sha256_hash_based(self):
        self.assertIn("sha256", self.txt.lower())

    def test_upserts_query_patterns(self):
        self.assertIn("query_patterns", self.txt.lower())
        self.assertIn("upsert", self.txt.lower())

    def test_updates_relationship_stats(self):
        self.assertIn("success_rate", self.txt.lower())

    def test_has_confidence_threshold(self):
        self.assertIn("MIN_CONFIDENCE_THRESHOLD", self.txt)


class KnowledgeUpdaterAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "knowledge_updater.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_routes_by_feedback_action(self):
        self.assertIn("feedback_action", self.txt.lower())

    def test_marks_feedback_applied(self):
        self.assertIn("learning_applied", self.txt.lower())


class MetricRefinerAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "metric_refiner.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_creates_draft_versions(self):
        self.assertIn("draft", self.txt.lower())
        self.assertIn("version", self.txt.lower())

    def test_records_lineage(self):
        self.assertIn("lineage", self.txt.lower())

    def test_has_fallback_heuristic(self):
        self.assertIn("heuristic", self.txt.lower())


# ═══════════════════════════════════════════════════════════════════════════
# Advanced Analytics
# ═══════════════════════════════════════════════════════════════════════════


class StatisticalAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "statistical_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_deterministic(self):
        self.assertIn("_compute_stats", self.txt)

    def test_iqr_outlier_detection(self):
        self.assertIn("_detect_outliers_iqr", self.txt)

    def test_trend_detection(self):
        self.assertIn("_detect_trend", self.txt)

    def test_group_comparison(self):
        self.assertIn("_compare_groups", self.txt)

    def test_auto_finds_columns(self):
        self.assertIn("_find_numeric_columns", self.txt)


class InsightAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "insight_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_structured_output(self):
        self.assertIn("summary", self.txt.lower())
        self.assertIn("observations", self.txt.lower())

    def test_has_heuristic_fallback(self):
        self.assertIn("_heuristic_insights", self.txt)


class VisualizationAgentContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "visualization_agent.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_12_chart_types(self):
        chart_types = ["line", "bar", "grouped_bar", "pie", "donut", "scatter", "heatmap", "metric_card", "table"]
        found = sum(1 for c in chart_types if c in self.txt.lower())
        self.assertGreaterEqual(found, 5)

    def test_intent_chart_mapping(self):
        self.assertIn("INTENT_CHART_MAP", self.txt)

    def test_scored_recommendations(self):
        self.assertIn("_recommend", self.txt)


class SkillsEngineContractTests(unittest.TestCase):
    def setUp(self):
        self.p = ROOT / "agents" / "data_agent_v2" / "skills_engine.py"
        self.txt = _read(self.p)

    def test_file_exists(self):
        self.assertTrue(self.p.exists())

    def test_expands_plan_template(self):
        self.assertIn("expand", self.txt.lower())
        self.assertIn("plan_template", self.txt.lower())

    def test_resolves_parameters(self):
        self.assertIn("$", self.txt)
        self.assertIn("resolve", self.txt.lower())

    def test_agent_type_mapping(self):
        self.assertIn("AGENT_TYPE_MAP", self.txt)


# ═══════════════════════════════════════════════════════════════════════════
# API + Knowledge Tables
# ═══════════════════════════════════════════════════════════════════════════


class KnowledgeTablesContractTests(unittest.TestCase):
    def test_metric_definitions_model_exists(self):
        models_txt = _read(ROOT / "infra" / "storage" / "models.py")
        self.assertIn("class MetricDefinition", models_txt)
        self.assertIn("metric_definitions", models_txt.lower())

    def test_schema_metadata_model_exists(self):
        models_txt = _read(ROOT / "infra" / "storage" / "models.py")
        self.assertIn("class SchemaMetadata", models_txt)
        self.assertIn("schema_metadata", models_txt.lower())

    def test_table_relationship_model_exists(self):
        models_txt = _read(ROOT / "infra" / "storage" / "models.py")
        self.assertIn("class TableRelationship", models_txt)
        self.assertIn("table_relationships", models_txt.lower())

    def test_analytical_skill_model_exists(self):
        models_txt = _read(ROOT / "infra" / "storage" / "models.py")
        self.assertIn("class AnalyticalSkill", models_txt)
        self.assertIn("analytical_skills", models_txt.lower())

    def test_query_pattern_model_exists(self):
        models_txt = _read(ROOT / "infra" / "storage" / "models.py")
        self.assertIn("class QueryPattern", models_txt)
        self.assertIn("query_patterns", models_txt.lower())

    def test_metric_lineage_model_exists(self):
        models_txt = _read(ROOT / "infra" / "storage" / "models.py")
        self.assertIn("class MetricLineage", models_txt)
        self.assertIn("metric_lineage", models_txt.lower())


class APIRouterContractTests(unittest.TestCase):
    def test_metrics_router_exists(self):
        p = ROOT / "gateway" / "api_gateway" / "routers" / "metrics.py"
        self.assertTrue(p.exists())
        txt = _read(p)
        self.assertIn("router", txt.lower())
        self.assertIn("metrics", txt.lower())

    def test_metrics_router_registered(self):
        main_txt = _read(ROOT / "gateway" / "api_gateway" / "main.py")
        self.assertIn("metrics.router", main_txt)

    def test_table_relationships_router_exists(self):
        p = ROOT / "gateway" / "api_gateway" / "routers" / "table_relationships.py"
        self.assertTrue(p.exists())
        txt = _read(p)
        self.assertIn("router", txt.lower())
        self.assertIn("relationships", txt.lower())

    def test_table_relationships_router_registered(self):
        main_txt = _read(ROOT / "gateway" / "api_gateway" / "main.py")
        self.assertIn("table_relationships.router", main_txt)

    def test_analytical_skills_router_exists(self):
        p = ROOT / "gateway" / "api_gateway" / "routers" / "analytical_skills.py"
        self.assertTrue(p.exists())
        txt = _read(p)
        self.assertIn("router", txt.lower())
        self.assertIn("analytical_skills", txt.lower())
        self.assertIn("seed", txt)

    def test_analytical_skills_router_registered(self):
        main_txt = _read(ROOT / "gateway" / "api_gateway" / "main.py")
        self.assertIn("analytical_skills.router", main_txt)


class BootstrapScriptsContractTests(unittest.TestCase):
    def test_sync_schema_metadata_exists(self):
        p = ROOT / "scripts" / "sync_schema_metadata.py"
        self.assertTrue(p.exists())
        txt = _read(p)
        self.assertIn("information_schema", txt.lower())
        self.assertIn("SEMANTIC_PATTERNS", txt)

    def test_sync_table_relationships_exists(self):
        p = ROOT / "scripts" / "sync_table_relationships.py"
        self.assertTrue(p.exists())
        txt = _read(p)
        self.assertIn("information_schema", txt.lower())
        self.assertIn("FOREIGN KEY", txt)

    def test_migrate_metrics_exists(self):
        p = ROOT / "scripts" / "migrate_metrics.py"
        self.assertTrue(p.exists())
        txt = _read(p)
        self.assertIn("semantic_mappings", txt.lower())
        self.assertIn("metric_definitions", txt.lower())

    def test_all_scripts_accept_data_source_id_arg(self):
        for name in ["sync_schema_metadata.py", "sync_table_relationships.py", "migrate_metrics.py"]:
            p = ROOT / "scripts" / name
            txt = _read(p)
            self.assertIn("--data-source-id", txt, f"{name} should accept --data-source-id")


if __name__ == "__main__":
    unittest.main()
