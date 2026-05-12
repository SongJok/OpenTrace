import unittest


class Phase1AdaptiveModeContractTests(unittest.TestCase):
    def test_settings_has_adaptive_mode_flag(self):
        with open("infra/config/settings.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("kernel_adaptive_mode_enabled", code)
        self.assertIn("kernel_answer_draft_confidence_threshold", code)
        self.assertIn("kernel_answer_draft_max_chars", code)

    def test_orchestrator_uses_adaptive_profile(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("def _get_adaptive_profile", code)
        self.assertIn("adaptive_profile = self._get_adaptive_profile(req.query, user_tags=all_tags)", code)
        self.assertIn('"rag_min_score"', code)
        self.assertIn('"draft_threshold"', code)

    def test_rag_agent_accepts_min_score_from_task_params(self):
        with open("agents/rag_agent.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('task.params.get("min_score"', code)


if __name__ == "__main__":
    unittest.main()
