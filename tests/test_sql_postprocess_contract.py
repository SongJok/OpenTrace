import unittest


class SqlPostprocessContractTests(unittest.TestCase):
    def test_normalize_sql_helper_exists_and_used(self):
        with open("kernel/data_cognition/sql_postprocess.py", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("normalize_sql_for_dialect", code)
        self.assertIn("TOP", code.upper())

        with open("services/sql_assets.py", encoding="utf-8") as f:
            service = f.read()

        self.assertIn("_sqlglot_dialect", service)
        self.assertIn("SQLValidator", service)
        self.assertIn("comments=False", service)


if __name__ == "__main__":
    unittest.main()
