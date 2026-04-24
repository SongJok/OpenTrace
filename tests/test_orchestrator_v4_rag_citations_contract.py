import unittest


class OrchestratorV4RagCitationsContractTests(unittest.TestCase):
    def test_has_rag_citation_builder_and_append_logic(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("def _build_rag_citations", code)
        self.assertIn("参考来源：", code)
        self.assertIn("cits = r.metadata.get(\"citations\")", code)
        self.assertIn("rag_citations.extend", code)
        self.assertIn("answer = self._format_rag_answer", code)


if __name__ == "__main__":
    unittest.main()
