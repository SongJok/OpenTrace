import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentBusE2EContractTests(unittest.TestCase):
    def test_bus_module_exists(self):
        self.assertTrue((ROOT / "infra/message_bus/agent_bus.py").exists())

    def test_dispatcher_supports_bus_mode(self):
        txt = (ROOT / "kernel/dispatcher.py").read_text(encoding="utf-8")
        self.assertIn("bus_enabled", txt)
        self.assertIn("publish_task", txt)
        self.assertIn("wait_for_result", txt)

    def test_worker_has_data_and_rag_consumers(self):
        txt = (ROOT / "agents/worker.py").read_text(encoding="utf-8")
        self.assertIn("instantiate_builtin_agents", txt)
        self.assertIn("register_builtin_agents", txt)
        self.assertIn("self.agents", txt)
        from agents.bootstrap import expected_builtin_agent_types

        types = expected_builtin_agent_types()
        self.assertIn("data", types)
        self.assertIn("rag", types)


if __name__ == "__main__":
    unittest.main()
