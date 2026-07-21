import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage5ApiAnnotationsContractTests(unittest.TestCase):
    def test_response_items_carry_annotations(self):
        txt = (ROOT / "gateway/api_gateway/routers/conversations.py").read_text(encoding="utf-8")
        self.assertIn("annotations: list[dict]", txt)
        self.assertIn('item_payload.get("annotations")', txt)


if __name__ == "__main__":
    unittest.main()
