import unittest


class RagFusionOutputContractTests(unittest.TestCase):
    def test_orchestrator_v4_never_exposes_raw_rag_chunks_payload(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("elif r.agent_type == \"rag\":", code)
        self.assertIn("chunks = (r.metadata or {}).get(\"chunks\")", code)
        self.assertIn("Skip creating document ToolResult when no chunks found", code)

    def test_fusion_engine_masks_document_structured_payload(self):
        with open("kernel/fusion_engine/engine.py", "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn('src == "document"', code)
        self.assertIn("未检索到可直接引用的内部文档内容。", code)

    def test_fusion_engine_prioritizes_llmwiki_source(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            orchestrator_code = f.read()
        with open("kernel/fusion_engine/engine.py", "r", encoding="utf-8") as f:
            fusion_code = f.read()
        self.assertIn('source="llmwiki"', orchestrator_code)
        self.assertIn("source_priority=1", orchestrator_code)
        self.assertIn('"llmwiki": 1.05', fusion_code)


if __name__ == "__main__":
    unittest.main()
