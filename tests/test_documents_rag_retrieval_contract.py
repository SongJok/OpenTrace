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
        self.assertIn('row_text = " ".join', txt)

    def test_document_plugin_has_lexical_hybrid_scoring(self):
        txt = self._read("plugins/document_plugin.py")
        self.assertIn("def lexical_overlap_score", txt)
        self.assertIn("def title_boost", txt)
        self.assertIn("score = max(", txt)
        self.assertIn(".limit(", txt)

    def test_rag_agent_keeps_document_chunk_metadata(self):
        txt = self._read("agents/rag_agent.py")
        self.assertIn('"chunk_index": meta.get("chunk_index")', txt)
        self.assertIn('"document_id": meta.get("document_id")', txt)

    def test_document_retrieval_uses_central_read_scope(self):
        txt = self._read("plugins/document_retrieval.py")
        self.assertIn("accessible_document_predicate", txt)
        self.assertIn("user_id=user_id", txt)

    def test_document_retrieval_tenant_equality_columns(self):
        txt = self._read("infra/security/resource_scope.py")
        self.assertIn("Document.tenant_id == tenant_id", txt)
        self.assertIn("Document.workspace_id == workspace_id", txt)

    def test_document_model_has_tenant_columns(self):
        txt = self._read("infra/storage/models.py")
        self.assertIn("tenant_id: Mapped[str]", txt)
        self.assertIn('__tablename__ = "documents"', txt)

    def test_documents_upload_sets_tenant_from_request(self):
        txt = self._read("gateway/api_gateway/routers/documents.py")
        self.assertIn("build_tenant_metadata", txt)
        self.assertIn("tenant_id=doc_tenant", txt)

    def test_document_plugin_llmwiki_uses_central_read_scope(self):
        txt = self._read("plugins/document_plugin.py")
        self.assertIn("accessible_document_predicate", txt)


if __name__ == "__main__":
    unittest.main()
