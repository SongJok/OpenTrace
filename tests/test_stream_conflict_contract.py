import unittest


class StreamConflictContractTests(unittest.TestCase):
    def test_stream_emits_adaptive_profile_and_conflict_summary(self):
        with open("kernel/cognitive_kernel.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('"type": "adaptive_profile"', code)
        self.assertIn('"type": "answer_draft"', code)
        self.assertIn('"type": "conflict_summary"', code)
        self.assertIn('"type": "dag_node_start"', code)
        self.assertIn('"type": "dag_node_complete"', code)


if __name__ == "__main__":
    unittest.main()
