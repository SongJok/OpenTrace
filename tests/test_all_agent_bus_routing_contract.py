import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AllAgentBusRoutingContractTests(unittest.TestCase):
    def test_dispatcher_routes_all_agents_when_bus_enabled(self):
        txt = (ROOT / "kernel/dispatcher.py").read_text(encoding="utf-8")
        self.assertIn("if self.bus_enabled:", txt)
        self.assertNotIn("subtask.agent_type in {\"data\", \"rag\"}", txt)

    def test_worker_contains_all_v4_agents(self):
        txt = (ROOT / "agents/worker.py").read_text(encoding="utf-8")
        self.assertIn('"data": DataAgent()', txt)
        self.assertIn('"rag": RagAgent()', txt)
        self.assertIn('"web": WebAgent()', txt)
        self.assertIn('"tool": ToolAgent()', txt)


if __name__ == "__main__":
    unittest.main()
