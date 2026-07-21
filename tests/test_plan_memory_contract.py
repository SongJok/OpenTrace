import unittest


class PlanMemoryContractTests(unittest.TestCase):
    def test_plan_memory_module_exists(self):
        with open("kernel/plan_memory.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("class PlanMemory", code)
        self.assertIn("PlanMemoryRecord", code)
        self.assertIn("recent_successful_plans", code)

    def test_plan_agent_uses_plan_memory_and_env_flag(self):
        with open("kernel/plan_agent.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("kernel_plan_memory_enabled", code)
        self.assertIn("recent_success_patterns", code)
        self.assertIn("plan_memory.add", code)


if __name__ == "__main__":
    unittest.main()
