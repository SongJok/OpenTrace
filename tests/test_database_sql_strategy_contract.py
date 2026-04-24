import unittest


class DatabaseSqlStrategyContractTests(unittest.TestCase):
    def test_sql_dialect_supports_supported_sources(self):
        with open('kernel/data_cognition/sql_dialect.py', 'r', encoding='utf-8') as f:
            code = f.read()

        self.assertIn("clickhouse", code)
        self.assertIn("doris", code)
        self.assertIn("postgres", code)
        self.assertIn("mysql", code)
        self.assertIn("render_time_window", code)

    def test_data_query_uses_dialect(self):
        with open('gateway/api_gateway/routers/data.py', 'r', encoding='utf-8') as f:
            code = f.read()

        self.assertIn('detect_sql_dialect', code)
        self.assertIn('render_time_window', code)
        self.assertIn('SQLPlanner().plan', code)
        self.assertIn('SQLRewriter().rewrite', code)
        self.assertIn('data_source_id', code)

    def test_database_analysis_uses_dialect_window(self):
        with open('gateway/api_gateway/routers/databases.py', 'r', encoding='utf-8') as f:
            code = f.read()

        self.assertIn('detect_sql_dialect', code)
        self.assertIn('render_time_window', code)
        self.assertIn('clickhouse', code)
        self.assertIn('doris', code)


if __name__ == '__main__':
    unittest.main()
