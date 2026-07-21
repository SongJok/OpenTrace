import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class MemoryApiContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_memories_router_has_crud_and_settings(self):
        txt = self._read("gateway/api_gateway/routers/memories.py")
        self.assertIn('@router.get("/memories")', txt)
        self.assertIn('@router.post("/memories")', txt)
        self.assertIn('@router.patch("/memories/{memory_id}")', txt)
        self.assertIn('@router.delete("/memories/{memory_id}")', txt)
        self.assertIn('@router.get("/memories/settings")', txt)
        self.assertIn('@router.post("/memories/settings")', txt)

    def test_memory_router_included_in_main(self):
        txt = self._read("gateway/api_gateway/main.py")
        self.assertIn("memories.router", txt)


if __name__ == "__main__":
    unittest.main()
