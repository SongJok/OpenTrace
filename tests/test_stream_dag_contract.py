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
        # After TTFT optimization, events flow through orchestrator_v4.stream()
        # DAG events come from dag_scheduler.py via event_cb
        with open("kernel/dag_scheduler.py", "r", encoding="utf-8") as f:
            dag_code = f.read()
        self.assertIn('"type": "dag_node_start"', dag_code)
        self.assertIn('"type": "dag_node_complete"', dag_code)

        # adaptive_profile is emitted by orchestrator_v4.py's stream method
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            v4_code = f.read()
        self.assertIn('"type": "adaptive_profile"', v4_code)

        # Verify cognitive_kernel.py delegates to orchestrator.stream()
        with open("kernel/cognitive_kernel.py", "r", encoding="utf-8") as f:
            kernel_code = f.read()
        self.assertIn("orchestrator.stream", kernel_code)


if __name__ == "__main__":
    unittest.main()
