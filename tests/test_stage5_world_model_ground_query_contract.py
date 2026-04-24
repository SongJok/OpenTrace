import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage5WorldModelGroundQueryContractTests(unittest.TestCase):
    def test_world_model_has_ground_query_and_time_semantics(self):
        txt = (ROOT / "kernel/cognition/world_model.py").read_text(encoding="utf-8")
        self.assertIn("def ground_query", txt)
        self.assertIn("_ground_time_phrase", txt)
        self.assertIn("last_quarter", txt)

    def test_orchestrator_uses_ground_query(self):
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        self.assertIn("grounded_entities = world_model.ground_query(req.query)", txt)


if __name__ == "__main__":
    unittest.main()
