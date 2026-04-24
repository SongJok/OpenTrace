import unittest


class AdaptivePlanningContractTests(unittest.TestCase):
    def test_taskplan_contains_adaptive_profile_field(self):
        with open("kernel/plan_agent.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("adaptive_profile: dict[str, Any]", code)
        self.assertIn("return TaskPlan(subtasks=subtasks, merge_strategy=merge_strategy, max_parallel=max_parallel, adaptive_profile=adaptive_profile)", code)

    def test_quality_profile_can_expand_requirements(self):
        with open("kernel/plan_agent.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('profile_name == "quality"', code)
        self.assertIn('desired_max_parallel', code)
        self.assertIn('doc_intent', code)
        self.assertIn('web_intent', code)
        self.assertIn('data_intent', code)
        self.assertIn('selected_data_source_id', code)
        self.assertIn('data_source_id', code)
        self.assertIn('SubTask(agent_type="data"', code)

    def test_orchestrator_metadata_includes_adaptive_profile_in_plan(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('"adaptive_profile": adaptive_profile', code)
        self.assertIn('plan.adaptive_profile = adaptive_profile', code)


if __name__ == "__main__":
    unittest.main()
