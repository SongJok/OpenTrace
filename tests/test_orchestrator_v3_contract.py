import unittest


class OrchestratorV3ContractTests(unittest.TestCase):
    def test_v3_wrapper_exists_and_exports_class(self):
        """v3 is now a backward-compatibility wrapper around v4, living in orchestrator.py."""
        path = "kernel/orchestrator.py"
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("class CognitiveOrchestrator", code)
        self.assertIn("CognitiveOrchestratorV4", code)

    def test_v3_wrapper_delegates_to_v4(self):
        path = "kernel/orchestrator.py"
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("OrchestratorV4Request", code)
        self.assertIn("OrchestratorV4Response", code)
        self.assertIn(".process(", code)


if __name__ == "__main__":
    unittest.main()
