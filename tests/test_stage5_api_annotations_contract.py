import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Stage5ApiAnnotationsContractTests(unittest.TestCase):
    def test_chat_response_schema_contains_annotations(self):
        txt = (ROOT / "gateway/api_gateway/routers/chat.py").read_text(encoding="utf-8")
        self.assertIn("annotations: list[dict[str, Any]]", txt)
        self.assertIn('result.metadata.get("annotations"', txt)


if __name__ == "__main__":
    unittest.main()
