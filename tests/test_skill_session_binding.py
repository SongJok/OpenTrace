import unittest

from gateway.api_gateway.routers.skills import _SESSION_SKILL_BINDINGS


class SkillSessionBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        _SESSION_SKILL_BINDINGS.clear()

    def test_binding_store_shape(self):
        uid = "u1"
        sid = "s1"
        _SESSION_SKILL_BINDINGS.setdefault(uid, {})[sid] = {
            "enabled_skills": ["demo_skill"],
            "disabled_skills": ["old_skill"],
        }
        self.assertIn(uid, _SESSION_SKILL_BINDINGS)
        self.assertIn(sid, _SESSION_SKILL_BINDINGS[uid])
        self.assertEqual(_SESSION_SKILL_BINDINGS[uid][sid]["enabled_skills"], ["demo_skill"])


if __name__ == "__main__":
    unittest.main()
