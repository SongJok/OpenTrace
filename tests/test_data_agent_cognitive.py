"""Integration tests for DataAgent cognitive pipeline components (unit-level, no DB required)."""
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from kernel.data_cognition.sql_dialect import detect_sql_dialect
from kernel.data_cognition.sql_planner import SQLPlanner
from kernel.data_cognition.sql_ranker import SQLRanker
from kernel.data_cognition.sql_reflector import SQLReflector
from kernel.data_cognition.semantic_layer import SemanticLayer
from kernel.data_cognition.types import CandidateSQL, SemanticContext


class TestSemanticLayerIntegration(unittest.TestCase):
    def test_full_semantic_resolution(self):
        """Simulate: '最近一个月内有多少用户等级处于天帝？'"""
        config = {
            "dimensions": {
                "用户等级": {
                    "column": "tier",
                    "table": "users",
                    "value_map": {"天帝": "TIAN_DI"},
                }
            },
            "time_macros": [
                {"pattern": "最近一个月", "column": "created_at", "days": 30},
            ],
            "metrics": {
                "用户": "COUNT(DISTINCT user_id)",
            },
        }
        layer = SemanticLayer(config)
        dialect = detect_sql_dialect("postgres")
        ctx = layer.resolve("最近一个月内有多少用户等级处于天帝？", dialect=dialect)

        # Dimensions should be resolved
        self.assertIn("用户等级", ctx.dimension_mappings)
        # Time macros should be resolved
        self.assertEqual(len(ctx.time_macros), 1)
        self.assertIn("created_at", ctx.time_macros[0]["sql"])
        # Metrics should be resolved
        self.assertIn("用户", ctx.metric_defs)


class TestRankerIntegration(unittest.TestCase):
    def test_ranking_with_full_context(self):
        """Test ranking with semantic context, simulating candidate selection."""
        ctx = SemanticContext(
            dimension_mappings={
                "用户等级": {"column": "tier", "conditions": ["tier = 'TIAN_DI'"]},
            },
            time_macros=[{"pattern": "最近一个月", "column": "created_at", "days": 30}],
        )
        candidates = [
            CandidateSQL(
                sql="SELECT COUNT(*) FROM users WHERE tier = 'TIAN_DI' AND created_at >= NOW() - INTERVAL '30 days' LIMIT 100",
                features={"historical_success_rate": 0.98},
            ),
            CandidateSQL(
                sql="SELECT COUNT(DISTINCT user_id) FROM user_profile WHERE level = 'TIAN_DI' LIMIT 100",
            ),
            CandidateSQL(
                sql="SELECT * FROM users",
            ),
        ]
        ranker = SQLRanker()
        ranked = ranker.rank(candidates, semantic_ctx=ctx)

        # The best candidate should have the semantic mapping and time filter
        self.assertIn("tier = 'TIAN_DI'", ranked[0].sql)
        self.assertIn("created_at", ranked[0].sql)


class TestReflectorIntegration(unittest.TestCase):
    def test_reflection_detects_empty_result(self):
        reflector = SQLReflector()
        result = reflector.validate_result(
            "SELECT COUNT(*) FROM users WHERE tier = 'unknown' LIMIT 100",
            [],
            "有多少用户等级处于天帝",
        )
        self.assertFalse(result.passed)
        self.assertGreater(len(result.issues), 0)

    def test_successful_validation(self):
        reflector = SQLReflector()
        result = reflector.validate_result(
            "SELECT COUNT(*) FROM users WHERE tier = 'TIAN_DI' LIMIT 100",
            [{"count": 1523}],
            "有多少用户等级处于天帝",
        )
        self.assertTrue(result.passed)


class TestSQLPlannerCandidateGeneration(unittest.TestCase):
    def test_candidate_sql_structure(self):
        """Test that CandidateSQL has expected structure."""
        c = CandidateSQL(
            sql="SELECT COUNT(*) FROM users LIMIT 100",
            score=0.5,
            features={"dialect": "postgres"},
            source_template="template1",
        )
        self.assertEqual(c.sql, "SELECT COUNT(*) FROM users LIMIT 100")
        self.assertEqual(c.score, 0.5)
        self.assertIn("dialect", c.features)


if __name__ == "__main__":
    unittest.main()
