import unittest


class ConflictAnnotationContractTests(unittest.TestCase):
    def test_fusion_output_has_evidence_map(self):
        with open("kernel/fusion_engine/models.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("evidence_map: list[dict[str, Any]]", code)

    def test_orchestrator_emits_conflict_annotation(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('"id": "conflict_summary"', code)
        self.assertIn('"mode": "quality_disagreement"', code)
        self.assertIn('"evidence_map": fusion.evidence_map', code)


if __name__ == "__main__":
    unittest.main()
