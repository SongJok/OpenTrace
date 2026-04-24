import unittest


class Phase1RuntimeContractTests(unittest.TestCase):
    def test_dispatcher_has_runtime_supervisor_and_retry(self):
        with open("kernel/dispatcher.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("class RuntimeSupervisor", code)
        self.assertIn("kernel_agent_runtime_supervisor_enabled", code)
        self.assertIn("kernel_agent_max_retry", code)
        self.assertIn("for attempt in range(self.max_retry + 1)", code)

    def test_orchestrator_v4_emits_answer_draft_and_metrics(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("answer_draft", code)
        self.assertIn("first_token_ms", code)
        self.assertIn("supervisor_retry_count", code)
        self.assertIn("adaptive_profile", code)
        self.assertIn("get_profile_defaults", code)

    def test_stream_path_forwards_answer_draft_event(self):
        with open("kernel/cognitive_kernel.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('"type": "answer_draft"', code)


if __name__ == "__main__":
    unittest.main()
