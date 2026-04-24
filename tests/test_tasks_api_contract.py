import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TasksApiContractTests(unittest.TestCase):
    def _read(self, rel: str) -> str:
        return (ROOT / rel).read_text(encoding="utf-8")

    def test_tasks_router_has_required_endpoints(self):
        txt = self._read("gateway/api_gateway/routers/tasks.py")
        self.assertIn('@router.post("/tasks")', txt)
        self.assertIn('@router.get("/tasks")', txt)
        self.assertIn('@router.get("/tasks/{task_id}")', txt)
        self.assertIn('@router.post("/tasks/pause")', txt)
        self.assertIn('@router.post("/tasks/resume")', txt)
        self.assertIn('@router.post("/tasks/cancel")', txt)

    def test_main_includes_tasks_router(self):
        txt = self._read("gateway/api_gateway/main.py")
        self.assertIn("tasks.router", txt)


if __name__ == "__main__":
    unittest.main()
