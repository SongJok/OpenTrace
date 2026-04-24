import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentsRagRetrievalContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_docx_extraction_includes_table_text(self):
        txt = self._read("gateway/api_gateway/routers/documents.py")
        self.assertIn("for table in document.tables", txt)
        self.assertIn("for row in table.rows", txt)
        self.assertIn("row_text = \" \".join", txt)

    def test_document_plugin_has_lexical_hybrid_scoring(self):
        txt = self._read("plugins/document_plugin.py")
        self.assertIn("def lexical_overlap_score", txt)
        self.assertIn("def title_boost", txt)
        self.assertIn("score = max(", txt)
        self.assertIn(".limit(1000)", txt)

    def test_rag_agent_keeps_document_chunk_metadata(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('"chunk_index": meta.get("chunk_index")', txt)
        self.assertIn('"document_id": meta.get("document_id")', txt)


if __name__ == "__main__":
    unittest.main()
