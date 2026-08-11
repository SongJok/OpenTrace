import unittest


class DatabaseSqlStrategyContractTests(unittest.TestCase):
    def test_sql_dialect_supports_supported_sources(self):
        with open("kernel/data_cognition/sql_dialect.py", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("clickhouse", code)
        self.assertIn("doris", code)
        self.assertIn("postgres", code)
        self.assertIn("mysql", code)
        self.assertIn("render_time_window", code)

    def test_data_query_uses_data_agent_dialect(self):
        with open("services/sql_assets.py", encoding="utf-8") as f:
            service_code = f.read()
        with open("data_agent/adapters/opentrace/evidence.py", encoding="utf-8") as f:
            evidence_code = f.read()

        self.assertIn("DataAgentService", service_code)
        self.assertIn("OpenTraceEvidenceProvider", service_code)
        self.assertIn("OpenTraceSQLGenerator", service_code)
        self.assertIn("_sqlglot_dialect", service_code)
        self.assertIn("SQLValidator", service_code)
        self.assertIn("data_source_id", service_code)
        self.assertIn("self.data_source.source_type", evidence_code)
        self.assertIn("dialect=dialect", evidence_code)

    def test_database_analysis_uses_dialect_window(self):
        with open("gateway/api_gateway/routers/databases.py", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("detect_sql_dialect", code)
        self.assertIn("render_time_window", code)
        self.assertIn("clickhouse", code)
        self.assertIn("doris", code)


if __name__ == "__main__":
    unittest.main()
