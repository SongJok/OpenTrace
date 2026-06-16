import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage9ReleaseChecklistContractTests(unittest.TestCase):
    def test_env_example_has_cognition_lexicon_json(self):
        txt = (ROOT / ".env.example").read_text(encoding="utf-8")
        self.assertIn("COGNITION_LEXICON_JSON", txt)
        self.assertIn("canonical_name", txt)

    def test_health_router_has_runtime_cognition_endpoint(self):
        txt = (ROOT / "gateway/api_gateway/routers/health.py").read_text(encoding="utf-8")
        self.assertIn("/health/runtime", txt)
        self.assertIn("lexicon_records", txt)
        self.assertIn("annotations_enabled", txt)

    def test_runtime_health_reports_orchestrator(self):
        txt = (ROOT / "gateway/api_gateway/routers/health.py").read_text(encoding="utf-8")
        self.assertIn("resolve_orchestrator_label", txt)
        self.assertIn("RuntimeCognitionHealthResponse", txt)


if __name__ == "__main__":
    unittest.main()
