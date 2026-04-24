import unittest


class AdaptiveProfileRuntimeContractTests(unittest.TestCase):
    def test_orchestrator_metadata_contains_adaptive_profile(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('"adaptive_profile": adaptive_profile', code)
        self.assertIn('"adaptive_profile": {"name": "identity"', code)

    def test_health_runtime_exposes_adaptive_mode(self):
        with open("gateway/api_gateway/routers/health.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("adaptive_mode_enabled", code)
        self.assertIn("kernel_adaptive_mode_enabled", code)


if __name__ == "__main__":
    unittest.main()
