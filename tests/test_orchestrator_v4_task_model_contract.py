import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OrchestratorV4TaskModelContractTests(unittest.TestCase):
    def test_v4_contains_task_model_update_and_replan_flag(self):
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        self.assertIn("TaskModel()", txt)
        self.assertIn("update_from_agent_result", txt)
        self.assertIn("replan_triggered", txt)


if __name__ == "__main__":
    unittest.main()
