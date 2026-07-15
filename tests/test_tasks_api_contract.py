import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TasksApiContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_tasks_router_has_required_endpoints(self):
        txt = self._read("gateway/api_gateway/routers/tasks.py")
        self.assertIn('@router.post("/tasks",', txt)
        self.assertIn('@router.get("/tasks",', txt)
        self.assertIn('status_code=410', txt)
        self.assertIn('/api/v2/scheduled-tasks', txt)

        v2 = self._read("gateway/api_gateway/routers/agent_resources.py")
        self.assertIn('@router.post("/scheduled-tasks")', v2)
        self.assertIn('@router.get("/scheduled-tasks")', v2)
        self.assertIn('@router.post("/scheduled-tasks/{task_id}/actions/{action}")', v2)

    def test_main_includes_tasks_router(self):
        txt = self._read("gateway/api_gateway/main.py")
        self.assertIn("tasks.router", txt)


if __name__ == "__main__":
    unittest.main()
