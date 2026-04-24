import unittest


class HealthRuntimeMetricsContractTests(unittest.TestCase):
    def test_runtime_health_has_metric_fields(self):
        with open("gateway/api_gateway/routers/health.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("avg_agent_latency_ms", code)
        self.assertIn("avg_first_token_ms", code)
        self.assertIn("avg_orchestrator_latency_ms", code)
        self.assertIn("supervisor_retry_total", code)
        self.assertIn("metric_samples", code)
        self.assertIn("runtime_metrics_store.snapshot()", code)


if __name__ == "__main__":
    unittest.main()
