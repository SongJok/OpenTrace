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
        self.assertIn("re.findall", txt)
        self.assertIn("def _rewrite_query", txt)

    def test_rag_agent_rewrite_query_normalizes_chinese(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("def _rewrite_query", txt)
        self.assertIn('"怎么做", "如何操作"', txt)
        self.assertIn('"有没有", "是否有"', txt)
        self.assertIn('"啥是", "什么是"', txt)
        self.assertIn("rewritten_query", txt)

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

    def test_classify_query_type_exists_and_returns_typed_dict(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("def _classify_query_type", txt)
        self.assertIn('"query_type"', txt)
        self.assertIn('"hints"', txt)
        self.assertIn('"definition"', txt)
        self.assertIn('"fact"', txt)
        self.assertIn('"procedure"', txt)
        self.assertIn('"comparison"', txt)
        self.assertIn('"memory"', txt)
        self.assertIn('"general"', txt)
        # Verify hints for each type
        self.assertIn('"prefer_llmwiki"', txt)
        self.assertIn('"lower_threshold"', txt)
        self.assertIn('"prefer_documents"', txt)
        self.assertIn('"higher_precision"', txt)

    def test_document_evidence_gate_is_imported_and_used(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("from plugins.document_retrieval import DocumentEvidenceGate, ScoredDocumentChunk", txt)
        self.assertIn("DocumentEvidenceGate", txt)
        self.assertIn("evidence_gate", txt)

    def test_evidence_items_include_tier_field(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('"evidence_tier"', txt)
        self.assertIn('"factual"', txt)
        self.assertIn('"supporting"', txt)
        self.assertIn('"contextual"', txt)

    def test_memory_evidence_downgraded_for_non_memory_queries(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("is_memory_intent", txt)
        # Memory tier should be contextual for non-memory queries
        self.assertIn('"contextual"', txt)
        # Memory score should be reduced for non-memory intent
        self.assertIn("memory_score - 0.15", txt)

    def test_quality_metadata_includes_answerable_and_gap(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('"top1_top3_gap"', txt)
        self.assertIn('"answerable"', txt)
        self.assertIn('"gated"', txt)
        self.assertIn('"query_type"', txt)

    def test_confidence_calculation_uses_score_distribution(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("source_diversity", txt)
        self.assertIn("score_spread", txt)
        self.assertIn("top1_top3_gap", txt)

    def test_synonym_map_includes_expanded_terms(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('"管理员"', txt)
        self.assertIn('"审核"', txt)
        self.assertIn('"规则"', txt)
        self.assertIn('"流程"', txt)
        self.assertIn('"条件"', txt)
        self.assertIn('"原因"', txt)


if __name__ == "__main__":
    unittest.main()
