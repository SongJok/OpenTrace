import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage4GroundingAndAnnotationsContractTests(unittest.TestCase):
    def test_orchestrator_v4_has_world_model_grounding(self):
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        self.assertIn("WorldModel()", txt)
        self.assertIn("grounded_entities", txt)
        self.assertIn("ground_query(req.query)", txt)

    def test_v4_metadata_contains_structured_annotations(self):
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        self.assertIn('"annotations"', txt)
        self.assertIn('validated_resp.fragments', txt)

    def test_stream_final_answer_carries_annotations(self):
        # After TTFT optimization, stream() delegates to orchestrator_v4.stream()
        # which emits final_answer with annotations
        txt = (ROOT / "kernel/orchestrator_v4.py").read_text(encoding="utf-8")
        self.assertIn('"annotations"', txt)
        self.assertIn('"final_answer"', txt)

        # Verify cognitive_kernel.py delegates to orchestrator.stream()
        kernel_code = (ROOT / "kernel/cognitive_kernel.py").read_text(encoding="utf-8")
        self.assertIn("orchestrator.stream", kernel_code)


if __name__ == "__main__":
    unittest.main()
