import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AgentBusGovernanceContractTests(unittest.TestCase):
    def test_settings_have_retry_and_dlq(self):
        txt = (ROOT / "infra/config/settings.py").read_text(encoding="utf-8")
        self.assertIn("kernel_agent_bus_max_retry", txt)
        self.assertIn("kernel_agent_bus_dlq_stream", txt)

    def test_worker_has_retry_and_dlq_logic(self):
        txt = (ROOT / "agents/worker.py").read_text(encoding="utf-8")
        self.assertIn("kernel_agent_bus_max_retry", txt)
        self.assertIn("dlq_stream", txt)
        self.assertIn("xadd", txt)


if __name__ == "__main__":
    unittest.main()
