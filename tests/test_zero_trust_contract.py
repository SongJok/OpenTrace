import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ZeroTrustContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_zero_trust_module_exists(self):
        txt = self._read("infra/security/zero_trust.py")
        self.assertIn("class RiskAssessment", txt)
        self.assertIn("def assess_query_risk", txt)
        self.assertIn("def issue_permission_token", txt)
        self.assertIn("def validate_permission_token", txt)
        self.assertIn("class ToolAnomalyDetector", txt)

    def test_agent_loop_requires_durable_approval_for_side_effects(self):
        txt = self._read("kernel/agent_loop/runner.py")
        self.assertIn("SideEffect.READ", txt)
        self.assertIn("ResponseApproval", txt)
        self.assertIn('status="requires_action"', txt)


if __name__ == "__main__":
    unittest.main()
