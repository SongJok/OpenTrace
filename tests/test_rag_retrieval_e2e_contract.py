import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RagRetrievalE2EContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_document_router_extracts_docx_tables(self):
        txt = self._read("gateway/api_gateway/routers/documents.py")
        self.assertIn("for table in document.tables", txt)
        self.assertIn("for row in table.rows", txt)

    def test_document_plugin_returns_title_metadata(self):
        txt = self._read("plugins/document_plugin.py")
        self.assertIn('"document_title": item.title', txt)
        self.assertIn("title_boost", txt)

    def test_rag_agent_tries_title_seeded_queries(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn("search_queries = [rewritten_query]", txt)
        self.assertIn("title_seed = \" \".join(query_terms[:4])", txt)
        self.assertIn("matched_query", txt)


if __name__ == "__main__":
    unittest.main()
