import unittest


class FusionCriticFlagsContractTests(unittest.TestCase):
    def test_settings_has_v3_flags(self):
        path = "infra/config/settings.py"
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("kernel_fusion_enabled", code)
        self.assertIn("kernel_critic_enabled", code)
        self.assertIn("kernel_critic_max_retry", code)

    def test_kernel_supports_v3_routing(self):
        path = "kernel/cognitive_kernel.py"
        with open(path, "r", encoding="utf-8") as f:
            code = f.read()
        self.assertIn("orchestrator_version", code)
        self.assertIn('== "v3"', code)
        self.assertIn("CognitiveOrchestratorV3", code)


if __name__ == "__main__":
    unittest.main()
