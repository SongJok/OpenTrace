import unittest
from tests.orchestrator_v4_source import read_orchestrator_v4_implementation


class DependencyPlanningContractTests(unittest.TestCase):
    def test_subtask_supports_depends_on(self):
        with open("kernel/plan_agent.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("depends_on: list[str] = field(default_factory=list)", code)

    def test_plan_agent_attaches_dependencies(self):
        with open("kernel/plan_agent.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("def _attach_dependencies", code)
        self.assertIn('s.agent_type == "rag"', code)
        self.assertIn('s.agent_type == "tool"', code)
        self.assertIn('s.depends_on =', code)

    def test_orchestrator_passes_dependencies_to_dag_path(self):
        code = read_orchestrator_v4_implementation()
        self.assertIn("depends_on", code)
        self.assertIn("plan.subtasks", code)


if __name__ == "__main__":
    unittest.main()
