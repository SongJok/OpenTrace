import unittest

from kernel.data_cognition.sql_reflector import SQLReflector
from kernel.data_cognition.types import SemanticContext, ValidationResult


class TestSQLReflector(unittest.TestCase):
    def setUp(self):
        self.reflector = SQLReflector()

    def test_empty_rows_detected(self):
        result = self.reflector.validate_result("SELECT 1", [], "有多少用户")
        self.assertFalse(result.passed)
        self.assertTrue(any("0 rows" in issue for issue in result.issues))

    def test_valid_result_passes(self):
        rows = [{"count": 1523}]
        result = self.reflector.validate_result("SELECT COUNT(*) FROM users", rows, "有多少用户")
        self.assertTrue(result.passed)

    def test_negative_value_flagged(self):
        rows = [{"balance": -500}]
        result = self.reflector.validate_result("SELECT balance FROM accounts", rows, "余额多少")
        self.assertFalse(result.passed)
        self.assertTrue(any("negative" in issue for issue in result.issues))

    def test_huge_value_flagged(self):
        rows = [{"total": 99_999_999_999}]
        result = self.reflector.validate_result("SELECT total FROM orders", rows, "总订单数")
        self.assertFalse(result.passed)
        self.assertTrue(any("extremely large" in issue for issue in result.issues))

    def test_time_column_missing(self):
        ctx = SemanticContext(
            time_macros=[{"pattern": "最近一个月", "column": "created_at"}],
        )
        result = self.reflector.validate_result(
            "SELECT COUNT(*) FROM users", [{"count": 0}], "最近一个月有多少用户", semantic_ctx=ctx,
        )
        self.assertFalse(result.passed)
        self.assertTrue(any("created_at" in issue for issue in result.issues))

    def test_time_column_present(self):
        ctx = SemanticContext(
            time_macros=[{"pattern": "最近一个月", "column": "created_at"}],
        )
        result = self.reflector.validate_result(
            "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '30 days'",
            [{"count": 1523}],
            "最近一个月有多少用户",
            semantic_ctx=ctx,
        )
        self.assertTrue(result.passed)


if __name__ == "__main__":
    unittest.main()
