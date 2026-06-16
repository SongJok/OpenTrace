import unittest
from tests.orchestrator_v4_source import read_orchestrator_v4_implementation


class AdaptiveProfileRuntimeContractTests(unittest.TestCase):
    def test_orchestrator_metadata_contains_adaptive_profile(self):
        code = read_orchestrator_v4_implementation()
        self.assertIn('"adaptive_profile": adaptive_profile', code)
        self.assertIn('"name": "identity"', code)

    def test_health_runtime_exposes_adaptive_mode(self):
        with open("gateway/api_gateway/routers/health.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("adaptive_mode_enabled", code)
        self.assertIn("kernel_adaptive_mode_enabled", code)


if __name__ == "__main__":
    unittest.main()
