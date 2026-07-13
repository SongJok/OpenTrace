import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DocumentUploadSearchContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_upload_pipeline_targets_docx_and_search_endpoint(self):
        txt = self._read("gateway/api_gateway/routers/documents.py")
        self.assertIn('@router.post("/documents"', txt)
        self.assertIn('@router.post("/documents/search"', txt)
        self.assertIn('await _ingest(db, doc, text)', txt)
        self.assertIn('db.add(DocumentChunk(', txt)
        self.assertIn('document_id=doc.id', txt)

    def test_rag_agent_uses_documents_source_by_default(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('sources = task.params.get("sources", ["knowledge", "documents", "semantic_memory"])', txt)
        self.assertIn('if "documents" in sources:', txt)

    def test_document_plugin_hybrid_scoring_is_document_title_aware(self):
        txt = self._read("plugins/document_plugin.py")
        self.assertIn("def lexical_overlap_score", txt)
        self.assertIn("def title_boost", txt)
        self.assertIn('"document_title": item.title', txt)
        self.assertIn("async def search_llmwiki", txt)

    def test_document_upload_triggers_llmwiki_generation(self):
        txt = self._read("gateway/api_gateway/routers/documents.py")
        self.assertIn("background_tasks.add_task(generate_llmwiki_entries, doc.id)", txt)
        self.assertIn("delete(DocumentLLMWiki).where(DocumentLLMWiki.document_id == doc.id)", txt)


if __name__ == "__main__":
    unittest.main()
