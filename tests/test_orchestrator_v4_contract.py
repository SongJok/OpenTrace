import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class OrchestratorV4ContractTests(unittest.TestCase):
    def test_v4_files_exist(self):
        self.assertTrue((ROOT / "kernel/orchestrator_v4.py").exists())
        self.assertTrue((ROOT / "kernel/plan_agent.py").exists())
        self.assertTrue((ROOT / "kernel/dispatcher.py").exists())
        self.assertTrue((ROOT / "agents/base.py").exists())
        self.assertTrue((ROOT / "agents/data_agent.py").exists())
        self.assertTrue((ROOT / "agents/web_agent.py").exists())

    def test_kernel_supports_v4_routing(self):
        txt = (ROOT / "kernel/cognitive_kernel.py").read_text(encoding="utf-8")
        self.assertIn("CognitiveOrchestratorV4", txt)
        self.assertIn("orchestrator_v4", txt)
        self.assertNotIn("orchestrator_v2", txt)
        self.assertNotIn("orchestrator_v3", txt)

    def test_v4_has_database_and_rag_logic(self):
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        rag_txt = (ROOT / "agents/rag_agent.py").read_text(encoding="utf-8")
        data_txt = (ROOT / "agents/data_agent.py").read_text(encoding="utf-8")
        plan_txt = (ROOT / "kernel/plan_agent.py").read_text(encoding="utf-8")
        sp_txt = (ROOT / "kernel/data_cognition/semantic_parser.py").read_text(encoding="utf-8")
        self.assertIn("data_intent", txt)
        self.assertIn("SubTask(", txt)
        self.assertIn('agent_type="data"', txt)
        self.assertIn('selected_data_source_id', plan_txt)
        self.assertIn('data_source_id', plan_txt)
        self.assertIn('doc_evidence_count', rag_txt)
        self.assertIn('memory_intent', rag_txt)
        self.assertIn('show', data_txt)
        # Structured intent detection moved from data_agent.py to semantic_parser.py
        self.assertIn('build_structured_database_query', sp_txt)
        self.assertIn('check_structured_intent', data_txt)


if __name__ == "__main__":
    unittest.main()
