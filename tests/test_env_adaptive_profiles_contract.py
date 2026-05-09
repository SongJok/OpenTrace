import unittest


class EnvAdaptiveProfilesContractTests(unittest.TestCase):
    def test_settings_contains_profile_json(self):
        with open("infra/config/settings.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("kernel_adaptive_profile_json", code)

    def test_profile_loader_exists(self):
        with open("kernel/adaptive_profiles.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("DEFAULT_PROFILES", code)
        self.assertIn("PROFILE_OVERRIDES", code)
        self.assertIn("get_profile_defaults", code)

    def test_env_example_contains_profile_json(self):
        with open(".env.example", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("KERNEL_ADAPTIVE_PROFILE_JSON", code)

    def test_orchestrator_uses_profile_loader(self):
        with open("kernel/orchestrator_v4.py", "r", encoding="utf-8") as f:
            code = f.read()

        self.assertIn("from kernel.adaptive_profiles import get_profile_defaults", code)
        self.assertIn("profile = get_profile_defaults(profile_name)", code)


if __name__ == "__main__":
    unittest.main()
