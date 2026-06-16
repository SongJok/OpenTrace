import unittest
from tests.orchestrator_v4_source import read_orchestrator_v4_implementation


class OrchestratorV4RagCitationsContractTests(unittest.TestCase):
    def test_has_rag_citation_builder_and_append_logic(self):
        code = read_orchestrator_v4_implementation()
        self.assertIn("def _build_rag_citations", code)
        self.assertIn("参考来源：", code)
        self.assertIn("cits = r.metadata.get(\"citations\")", code)
        self.assertIn("rag_citations.extend", code)
        self.assertIn("answer = self._format_rag_answer", code)


if __name__ == "__main__":
    unittest.main()
