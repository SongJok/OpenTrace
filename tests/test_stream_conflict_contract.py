import unittest


class StreamConflictContractTests(unittest.TestCase):
    def test_stream_emits_adaptive_profile_and_conflict_summary(self):
        # After TTFT optimization, streaming events are emitted by orchestrator_v4.stream()
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('"type": "adaptive_profile"', code)
        self.assertIn('"type": "answer_draft"', code)
        self.assertIn('"type": "conflict_summary"', code)

        # DAG node events are emitted via event_cb from DagScheduler
        with open("kernel/dag_scheduler.py", "r", encoding="utf-8") as f:
            dag_code = f.read()
        self.assertIn('"type": "dag_node_start"', dag_code)
        self.assertIn('"type": "dag_node_complete"', dag_code)

        # Verify cognitive_kernel.py delegates to orchestrator.stream()
        with open("kernel/cognitive_kernel.py", "r", encoding="utf-8") as f:
            kernel_code = f.read()
        self.assertIn("orchestrator.stream", kernel_code)


if __name__ == "__main__":
    unittest.main()
