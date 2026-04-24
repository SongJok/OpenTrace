import unittest


class FusionCriticAdaptiveContractTests(unittest.TestCase):
    def test_fusion_input_accepts_adaptive_profile(self):
        with open("kernel/fusion_engine/models.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("adaptive_profile: dict[str, Any]", code)

    def test_fusion_engine_uses_profile_name_logic(self):
        with open("kernel/fusion_engine/engine.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('profile_name = str(profile.get("name", "balanced")', code)
        self.assertIn('freshness_bonus', code)
        self.assertIn('quality', code)
        self.assertIn('speed', code)

    def test_critic_input_and_engine_support_adaptive_profile(self):
        with open("kernel/critic_engine/models.py", "r", encoding="utf-8") as f:
            models = f.read()
        with open("kernel/critic_engine/engine.py", "r", encoding="utf-8") as f:
            engine = f.read()

        self.assertIn("adaptive_profile: dict[str, object] | None = None", models)
        self.assertIn('profile_name = str((data.adaptive_profile or {}).get("name", "balanced")', engine)
        self.assertIn('quality_multi_source_enforce', engine)

    def test_orchestrator_passes_adaptive_profile_into_fusion_and_critic(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('FusionInput(query=req.query, results=tool_results, adaptive_profile=adaptive_profile)', code)
        self.assertIn('CriticInput(', code)
        self.assertIn('adaptive_profile=adaptive_profile', code)


if __name__ == "__main__":
    unittest.main()
