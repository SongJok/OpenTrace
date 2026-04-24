import unittest


class OrchestratorV3ContractTests(unittest.TestCase):
    def test_v3_file_exists_and_exports_class(self):
        path = "kernel/orchestrator_v3.py"
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("class CognitiveOrchestratorV3", code)
        self.assertIn("orchestrator_version", code)
        self.assertIn("\"v3\"", code)

    def test_v3_contains_fusion_and_critic_metadata(self):
        path = "kernel/orchestrator_v3.py"
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn('meta["fusion"]', code)
        self.assertIn('meta["critic"]', code)


if __name__ == "__main__":
    unittest.main()
