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
        self.assertIn("instantiate_builtin_agents", txt)
        self.assertIn("self.agents", txt)
        from agents.bootstrap import expected_builtin_agent_types

        expected = set(expected_builtin_agent_types())
        from kernel.agent_runtime.manifest import get_manifest

        manifest = get_manifest()
        manifest_expected = set(manifest.worker_agent_types)
        self.assertEqual(expected, manifest_expected)
        self.assertTrue({"data", "rag", "web_intelligence", "tool"}.issubset(expected))
        self.assertIn("rules", manifest.bootstrap_agent_types)
        self.assertNotIn("rules", manifest.bus_eligible_agent_types())


if __name__ == "__main__":
    unittest.main()
