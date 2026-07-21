import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AuditReplayContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_replay_manifest_and_cli_present(self):
        txt = self._read("infra/replay/manifest.py")
        self.assertIn("class ReplayManifest", txt)
        self.assertIn("class ReplayStep", txt)
        cli = self._read("scripts/opentrace_replay.py")
        self.assertIn("Usage: python scripts/opentrace_replay.py <trace_id>", cli)

    def test_audit_router_and_cleanup_present(self):
        txt = self._read("gateway/api_gateway/routers/audit.py")
        self.assertIn("/audit/logs", txt)
        self.assertIn("/audit/export", txt)
        cleanup = self._read("scripts/cleanup_retention.py")
        self.assertIn("trace_retention_days", cleanup)


if __name__ == "__main__":
    unittest.main()
