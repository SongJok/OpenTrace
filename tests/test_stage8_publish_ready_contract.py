import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage8PublishReadyContractTests(unittest.TestCase):
    def test_world_model_supports_external_lexicon_config(self):
        txt = (ROOT / "kernel/cognition/world_model.py").read_text(encoding="utf-8")
        self.assertIn("cognition_lexicon_json", txt)
        self.assertIn("_load_external_lexicon", txt)
        self.assertIn("json.loads", txt)

    def test_settings_has_cognition_lexicon_json(self):
        txt = (ROOT / "infra/config/settings.py").read_text(encoding="utf-8")
        self.assertIn("cognition_lexicon_json", txt)

    def test_decision_trace_card_has_expandable_citations(self):
        txt = (ROOT / "frontend/src/components/ChatMessage.tsx").read_text(encoding="utf-8")
        self.assertIn("展开证据明细", txt)
        self.assertIn("收起证据明细", txt)
        self.assertIn("topCitations", txt)


if __name__ == "__main__":
    unittest.main()
