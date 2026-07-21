import unittest

from kernel.agent_runtime.manifest import get_manifest


class AgentBusEligibilityContractTests(unittest.TestCase):
    def test_rules_not_bus_eligible(self) -> None:
        m = get_manifest()
        self.assertIn("rules", m.bootstrap_agent_types)
        self.assertNotIn("rules", m.bus_eligible_agent_types())

    def test_assert_bus_routing_rejects_rules(self) -> None:
        m = get_manifest()
        with self.assertRaises(ValueError) as ctx:
            m.assert_bus_routing("rules")
        self.assertIn("agent_not_bus_eligible", str(ctx.exception))

    def test_web_alias_resolves_to_web_intelligence(self) -> None:
        m = get_manifest()
        cap, reg = m.resolve_capability_alias("web")
        self.assertEqual(cap, "web_search")
        self.assertEqual(reg, "web_intelligence")


if __name__ == "__main__":
    unittest.main()