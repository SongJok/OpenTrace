import unittest


class DagSpeculativeContractTests(unittest.TestCase):
    def test_settings_include_dag_flags(self):
        with open("infra/config/settings.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("kernel_agent_dag_scheduling_enabled", code)
        self.assertIn("kernel_agent_speculative_execution_enabled", code)

    def test_plan_and_dag_modules_exist(self):
        with open("kernel/dag_plan.py", "r", encoding="utf-8") as f:
            plan = f.read()
        with open("kernel/dag_scheduler.py", "r", encoding="utf-8") as f:
            scheduler = f.read()

        self.assertIn("class DagNode", plan)
        self.assertIn("class DagPlan", plan)
        self.assertIn("class DagScheduler", scheduler)
        self.assertIn("speculative_execution", scheduler)

    def test_dispatcher_switches_to_dag_path(self):
        with open("kernel/dispatcher.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("kernel_agent_dag_scheduling_enabled", code)
        self.assertIn("DagScheduler", code)
        self.assertIn("DagPlan", code)

    def test_orchestrator_sets_dependencies_when_dag_enabled(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("kernel_agent_dag_scheduling_enabled", code)
        self.assertIn("depends_on", code)
        self.assertIn("node_", code)


if __name__ == "__main__":
    unittest.main()
