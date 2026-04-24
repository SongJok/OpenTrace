import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RagAgentContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_rag_agent_file_exists_and_class_defined(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("class RagAgent(BaseAgent)", txt)
        self.assertIn("DocumentPlugin", txt)
        self.assertIn("UserMemory", txt)

    def test_orchestrator_v4_registers_rag_agent(self):
        txt = self._read("kernel/orchestrator_v4.py")
        self.assertIn("from agents.rag_agent import RagAgent", txt)
        self.assertIn("self.registry.register(RagAgent())", txt)

    def test_plan_agent_supports_rag_subtask_type(self):
        txt = self._read("kernel/plan_agent.py")
        self.assertIn('"rag"', txt)

    def test_rag_agent_normalizes_document_prefix_and_zh_tokenization(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("def _normalize_query", txt)
        self.assertIn("def _expand_query_terms", txt)
        self.assertIn("从文档中获取：", txt)
        self.assertIn('re.findall(r"[a-z0-9]+|[\\u4e00-\\u9fff]{2,}"', txt)

    def test_rag_agent_has_min_score_filter(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('os.getenv("RAG_MIN_SCORE", "0.35")', txt)
        # Check for min score filter and deduplication logic separately
        self.assertIn("if score < min_score:", txt)
        self.assertIn("if chunk_id in seen_chunks:", txt)

    def test_rag_agent_supports_llmwiki_parallel_retrieval(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('DocumentPlugin().search_llmwiki', txt)
        self.assertIn('"llmwiki_entries": sorted_llmwiki_entries', txt)
        self.assertIn('"vector_chunks": sorted_vector_chunks', txt)


if __name__ == "__main__":
    unittest.main()
