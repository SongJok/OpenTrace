import unittest

from tests.orchestrator_v4_source import read_orchestrator_v4_implementation


class AdaptivePlanningContractTests(unittest.TestCase):
    def test_taskplan_contains_adaptive_profile_field(self):
        with open("kernel/plan_agent.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn('adaptive_profile: dict[str, Any]', code)
        self.assertIn('plan = TaskPlan(', code)
        self.assertIn('adaptive_profile=get_profile_defaults(', code)

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
        self.assertIn('agent_type="data"', code)

    def test_orchestrator_metadata_includes_adaptive_profile_in_plan(self):
        code = read_orchestrator_v4_implementation()

        self.assertIn('"adaptive_profile": adaptive_profile', code)
        self.assertIn('plan.adaptive_profile = adaptive_profile', code)


if __name__ == "__main__":
    unittest.main()
