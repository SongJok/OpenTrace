import unittest
from tests.orchestrator_v4_source import read_orchestrator_v4_implementation


class ConflictSurfacingContractTests(unittest.TestCase):
    def test_fusion_engine_exposes_alternate_contexts(self):
        with open("kernel/fusion_engine/models.py", "r", encoding="utf-8") as f:
            models = f.read()
        with open("kernel/fusion_engine/engine.py", "r", encoding="utf-8") as f:
            engine = f.read()

        self.assertIn("alternate_contexts: list[str]", models)
        self.assertIn("[disagreement]", engine)
        self.assertIn("conflict_mode", engine)

    def test_orchestrator_quality_mode_appends_disagreement_section(self):
        code = read_orchestrator_v4_implementation()
        self.assertIn('str(adaptive_profile.get("name", "balanced") or "balanced") == "quality"', code)
        self.assertIn('分歧说明：', code)
        self.assertIn('其他候选证据：', code)


if __name__ == "__main__":
    unittest.main()
