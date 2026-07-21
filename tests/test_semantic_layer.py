import unittest

from kernel.data_cognition.semantic_layer import SemanticLayer
from kernel.data_cognition.sql_dialect import detect_sql_dialect
from kernel.data_cognition.types import SemanticContext


class TestSemanticLayer(unittest.TestCase):
    def test_empty_config_resolves(self):
        layer = SemanticLayer({})
        ctx = layer.resolve("有多少用户")
        self.assertIsInstance(ctx, SemanticContext)
        self.assertEqual(ctx.dimension_mappings, {})
        self.assertEqual(ctx.metric_defs, {})
        self.assertEqual(ctx.time_macros, [])

    def test_dimension_mapping(self):
        config = {
            "dimensions": {
                "用户等级": {
                    "column": "tier",
                    "table": "users",
                    "value_map": {"天帝": "TIAN_DI", "凡人": "MORTAL"},
                }
            }
        }
        layer = SemanticLayer(config)
        ctx = layer.resolve("有多少用户等级处于天帝")
        self.assertIn("用户等级", ctx.dimension_mappings)
        conds = ctx.dimension_mappings["用户等级"]["conditions"]
        self.assertIn("tier = 'TIAN_DI'", conds)

    def test_metric_resolution(self):
        config = {
            "metrics": {
                "用户数": "COUNT(DISTINCT user_id)"
            }
        }
        layer = SemanticLayer(config)
        ctx = layer.resolve("统计用户数")
        self.assertIn("用户数", ctx.metric_defs)
        self.assertEqual(ctx.metric_defs["用户数"], "COUNT(DISTINCT user_id)")

    def test_time_macro_resolution(self):
        config = {
            "time_macros": [
                {"pattern": "最近一个月", "column": "created_at", "days": 30}
            ]
        }
        layer = SemanticLayer(config)
        dialect = detect_sql_dialect("postgres")
        ctx = layer.resolve("最近一个月内有多少用户", dialect=dialect)
        self.assertEqual(len(ctx.time_macros), 1)
        self.assertIn("created_at", ctx.time_macros[0]["sql"])

    def test_heuristic_time_extraction(self):
        result = SemanticLayer.extract_time_intent("最近一个月有多少用户")
        self.assertIsNotNone(result)
        self.assertEqual(result["days"], 30)

        result = SemanticLayer.extract_time_intent("近7天的数据")
        self.assertIsNotNone(result)
        self.assertEqual(result["days"], 7)

        result = SemanticLayer.extract_time_intent("今天天气怎么样")
        self.assertIsNone(result)

    def test_sql_fragments(self):
        config = {
            "dimensions": {
                "等级": {"column": "tier", "value_map": {"天帝": "TIAN_DI"}},
            },
            "time_macros": [
                {"pattern": "最近一个月", "column": "created_at", "days": 30},
            ],
        }
        dialect = detect_sql_dialect("postgres")
        layer = SemanticLayer(config)
        ctx = layer.resolve("最近一个月等级为天帝的用户", dialect=dialect)
        self.assertTrue(len(ctx.resolved_sql_fragments) > 0)


if __name__ == "__main__":
    unittest.main()
