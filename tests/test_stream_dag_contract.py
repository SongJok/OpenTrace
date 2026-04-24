import unittest


class StreamDagContractTests(unittest.TestCase):
    def test_orchestrator_accepts_event_callback(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("async def process(self, req: OrchestratorV4Request, event_cb=None)", code)
        self.assertIn("event_cb=None", code)
        self.assertIn("process(self, req: OrchestratorV4Request", code)

    def test_dispatcher_and_scheduler_emit_dag_events(self):
        with open("kernel/dispatcher.py", "r", encoding="utf-8") as f:
            dispatcher = f.read()
        with open("kernel/dag_scheduler.py", "r", encoding="utf-8") as f:
            scheduler = f.read()

        self.assertIn("event_cb=event_cb", dispatcher)
        self.assertIn('"type": "dag_node_start"', scheduler)
        self.assertIn('"type": "dag_node_complete"', scheduler)

    def test_stream_path_emits_dag_events(self):
        with open("kernel/cognitive_kernel.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('"type": "dag_node_start"', code)
        self.assertIn('"type": "dag_node_complete"', code)
        self.assertIn('"type": "adaptive_profile"', code)


if __name__ == "__main__":
    unittest.main()
