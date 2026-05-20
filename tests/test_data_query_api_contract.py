import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class DataQueryApiContractTests(unittest.TestCase):
    def test_data_router_has_required_endpoints(self):
        txt = (ROOT / "gateway/api_gateway/routers/data.py").read_text(encoding="utf-8")
        self.assertIn('@router.post("/data/query")', txt)
        self.assertIn('@router.post("/data/schema/sync")', txt)
        self.assertIn('@router.get("/data/schema")', txt)
        self.assertIn('data_source_id: str', txt)
        self.assertIn('from agents.data_agent import DataAgent', txt)
        self.assertIn('data_agent_v2_enabled', txt)
        self.assertIn('DataAgent().execute', txt)
        self.assertIn('SQLPlanner().plan', txt)
        self.assertIn('SQLRewriter().rewrite', txt)

    def test_data_router_registered_in_main(self):
        txt = (ROOT / "gateway/api_gateway/main.py").read_text(encoding="utf-8")
        self.assertIn("data.router", txt)


if __name__ == "__main__":
    unittest.main()
