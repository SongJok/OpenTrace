"""语义层管理 API 与自动抽取逻辑的测试。"""
import unittest

from gateway.api_gateway.routers.databases import _auto_extract_semantics_from_schema


class TestAutoSemanticExtract(unittest.TestCase):
    def test_empty_schema(self):
        result = _auto_extract_semantics_from_schema({"tables": []})
        self.assertEqual(result["dimensions"], {})
        self.assertEqual(result["metrics"], {})

    def test_dimension_from_column_comment(self):
        schema = {
            "tables": [
                {
                    "name": "users",
                    "comment": "用户表",
                    "columns": [
                        {"name": "tier", "comment": "用户等级字段"},
                        {"name": "status", "comment": "状态字段"},
                        {"name": "name", "comment": "姓名"},
                    ],
                }
            ]
        }
        result = _auto_extract_semantics_from_schema(schema)
        # Key is derived from comment text
        self.assertIn("用户等级", result["dimensions"])
        self.assertEqual(result["dimensions"]["用户等级"]["column"], "tier")
        self.assertEqual(result["dimensions"]["用户等级"]["table"], "users")
        self.assertIn("状态", result["dimensions"])

    def test_metric_from_column_comment(self):
        schema = {
            "tables": [
                {
                    "name": "orders",
                    "comment": "订单表",
                    "columns": [
                        {"name": "amount", "comment": "金额字段"},
                        {"name": "count", "comment": "数量字段"},
                    ],
                }
            ]
        }
        result = _auto_extract_semantics_from_schema(schema)
        self.assertIn("金额", result["metrics"])
        self.assertIn("SUM(amount)", result["metrics"]["金额"])

    def test_combined_extraction(self):
        schema = {
            "tables": [
                {
                    "name": "users",
                    "comment": "用户表",
                    "columns": [
                        {"name": "user_id", "comment": "用户ID"},
                        {"name": "tier", "comment": "用户等级字段"},
                        {"name": "created_at", "comment": "注册时间"},
                    ],
                },
                {
                    "name": "orders",
                    "comment": "订单表",
                    "columns": [
                        {"name": "amount", "comment": "金额字段"},
                        {"name": "order_count", "comment": "数量字段"},
                    ],
                },
            ]
        }
        result = _auto_extract_semantics_from_schema(schema)
        self.assertGreater(len(result["dimensions"]), 0)
        self.assertGreater(len(result["metrics"]), 0)

    def test_english_keywords(self):
        schema = {
            "tables": [
                {
                    "name": "products",
                    "comment": "product catalog",
                    "columns": [
                        {"name": "category", "comment": "product category type"},
                        {"name": "price", "comment": "revenue amount"},
                    ],
                }
            ]
        }
        result = _auto_extract_semantics_from_schema(schema)
        self.assertTrue(len(result["dimensions"]) > 0 or len(result["metrics"]) > 0)


if __name__ == "__main__":
    unittest.main()
