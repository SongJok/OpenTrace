from tests.orchestrator_v4_source import read_orchestrator_v4_implementation
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage4GroundingAndAnnotationsContractTests(unittest.TestCase):
    def test_orchestrator_v4_has_world_model_grounding(self):
        txt = read_orchestrator_v4_implementation()
        self.assertIn("WorldModel()", txt)
        self.assertIn("grounded_entities", txt)
        self.assertIn("ground_query(req.query)", txt)

    def test_v4_metadata_contains_structured_annotations(self):
        txt = read_orchestrator_v4_implementation()
        self.assertIn('"annotations"', txt)
        self.assertIn('validated_resp.fragments', txt)

    def test_stream_final_answer_carries_annotations(self):
        # After TTFT optimization, stream() delegates to orchestrator_v4.stream()
        # which emits final_answer with annotations
        txt = read_orchestrator_v4_implementation()
        self.assertIn('"annotations"', txt)
        self.assertIn('"final_answer"', txt)

        kernel_code = (ROOT / "kernel/cognitive_kernel.py").read_text(encoding="utf-8")
        self.assertIn("get_runtime_gateway", kernel_code)
        self.assertIn("annotations", kernel_code)


if __name__ == "__main__":
    unittest.main()
