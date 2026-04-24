import unittest


class SqlPostprocessContractTests(unittest.TestCase):
    def test_normalize_sql_helper_exists_and_used(self):
        with open('kernel/data_cognition/sql_postprocess.py', 'r', encoding='utf-8') as f:
            code = f.read()

        self.assertIn('normalize_sql_for_dialect', code)
        self.assertIn('TOP', code.upper())

        with open('gateway/api_gateway/routers/data.py', 'r', encoding='utf-8') as f:
            router = f.read()

        self.assertIn('normalize_sql_for_dialect', router)
        self.assertIn('SQLValidator', router)
        self.assertIn('SQLRewriter', router)


if __name__ == '__main__':
    unittest.main()
