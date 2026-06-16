import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RagWebFallbackContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_plan_agent_marks_rag_high_priority_and_fallback_enabled(self):
        txt = self._read("kernel/plan_agent.py")
        self.assertIn('priority="high"', txt)
        self.assertIn('min_evidence_score', txt)
        self.assertIn('fallback_to_web', txt)

    def test_dispatcher_contains_quality_gate_and_web_fallback(self):
        txt = self._read("kernel/dispatcher.py")
        # Phase 2 removed RAG→web fallback pattern; Dispatcher now delegates to
        # ExecutionRuntime when available and uses RuntimeSupervisor for quality.
        self.assertIn("RuntimeSupervisor", txt)
        self.assertIn("self.supervisor", txt)
        self.assertIn("ExecutionRuntime", txt)

    def test_rag_agent_exposes_quality_metadata(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('"quality"', txt)
        self.assertIn('avg_score', txt)
        self.assertIn('max_score', txt)


if __name__ == "__main__":
    unittest.main()
