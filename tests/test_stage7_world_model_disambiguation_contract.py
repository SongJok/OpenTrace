import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage7WorldModelDisambiguationContractTests(unittest.TestCase):
    def test_world_model_has_english_rules_and_priority(self):
        txt = (ROOT / "kernel/cognition/world_model.py").read_text(encoding="utf-8")
        self.assertIn("english_region_rules", txt)
        self.assertIn("priority =", txt)
        self.assertIn("time_range", txt)
        self.assertIn("region", txt)

    def test_decision_trace_has_source_ratio(self):
        txt = (ROOT / "frontend/src/components/ChatMessage.tsx").read_text(encoding="utf-8")
        self.assertIn("DB 证据", txt)
        self.assertIn("Doc / Web", txt)
        self.assertIn("sourceRatio.db", txt)


if __name__ == "__main__":
    unittest.main()
