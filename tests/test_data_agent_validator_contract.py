import unittest

from kernel.data_cognition.sql_validator import SQLValidationError, SQLValidator


class DataAgentValidatorContractTests(unittest.TestCase):
    def setUp(self):
        self.v = SQLValidator(default_limit=50)

    def test_select_without_limit_auto_appends_limit(self):
        out = self.v.validate("SELECT * FROM users")
        self.assertIn("LIMIT 50", out)

    def test_forbid_write_sql(self):
        with self.assertRaises(SQLValidationError):
            self.v.validate("DELETE FROM users")

    def test_forbid_multi_statement(self):
        with self.assertRaises(SQLValidationError):
            self.v.validate("SELECT 1; SELECT 2")

    def test_forbid_real_comments(self):
        with self.assertRaises(SQLValidationError):
            self.v.validate("SELECT * FROM users -- comment")
        with self.assertRaises(SQLValidationError):
            self.v.validate("SELECT * FROM users /* comment */")

    def test_dash_in_string_literal_allowed(self):
        # SQL containing -- inside string literals should NOT trigger comment detection
        out = self.v.validate("SELECT * FROM users WHERE name = 'test--value'")
        self.assertIn("test--value", out)

    def test_star_slash_in_string_literal_allowed(self):
        out = self.v.validate("SELECT * FROM users WHERE path = 'a/*b*/c'")
        self.assertIn("a/*b*/c", out)


if __name__ == "__main__":
    unittest.main()
