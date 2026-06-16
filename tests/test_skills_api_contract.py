"""技能 create/get/test API 端点契约测试。"""
import unittest
from unittest.mock import patch, Mock

from skills.store.marketplace import InstalledSkill


class TestSkillsCreateApiContract(unittest.TestCase):
    def _cleanup(self, skill_id):
        from skills.store.marketplace import marketplace
        marketplace.uninstall(skill_id)

    def setUp(self):
        # Clean up any stale test skills
        from skills.store.marketplace import marketplace
        for sid in ["test_skill@1.0.0", "echo_skill@1.0.0", "fetch_skill@0.2.0", "dup_skill@1.0.0", "list_skill@1.0.0", "router_skill@0.1.0"]:
            marketplace.uninstall(sid)

    def test_create_local_writes_manifest_and_config(self):
        from skills.store.marketplace import marketplace, INSTALLED_DIR

        skill = marketplace.create_local(
            name="test_skill",
            version="1.0.0",
            entrypoint="main.py",
            code="def execute(input): return {'ok': True}",
            description="A test skill",
            skill_type="generic",
            test_cases=[{"input": {"x": 1}, "expected": {"ok": True}}],
            data_source_id="ds_123",
        )

        self.assertEqual(skill.skill_id, "test_skill@1.0.0")
        self.assertEqual(skill.name, "test_skill")
        self.assertEqual(skill.description, "A test skill")
        self.assertEqual(skill.skill_type, "generic")
        self.assertIn("execute", skill.code)

        # Verify files exist
        import json
        manifest = json.loads((INSTALLED_DIR / skill.skill_id / "skill.json").read_text())
        self.assertEqual(manifest["name"], "test_skill")
        self.assertEqual(manifest["version"], "1.0.0")

        config = json.loads((INSTALLED_DIR / skill.skill_id / "skill_config.json").read_text())
        self.assertEqual(config["description"], "A test skill")
        self.assertEqual(config["data_source_id"], "ds_123")

        # Cleanup
        marketplace.uninstall(skill.skill_id)

    def test_get_skill_returns_full_metadata(self):
        from skills.store.marketplace import marketplace

        skill = marketplace.create_local(
            name="fetch_skill",
            version="0.2.0",
            entrypoint="fetch.py",
            description="Fetch data",
            skill_type="data_query",
        )

        fetched = marketplace.get_skill(skill.skill_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "fetch_skill")
        self.assertEqual(fetched.skill_type, "data_query")

        marketplace.uninstall(skill.skill_id)

    def test_get_skill_returns_none_for_missing(self):
        from skills.store.marketplace import marketplace
        self.assertIsNone(marketplace.get_skill("nonexistent@0.0.0"))

    def test_test_skill_executes_python_code(self):
        from skills.store.marketplace import marketplace

        code = '''
def execute(input: dict) -> dict:
    return {"echo": input.get("msg", ""), "length": len(input.get("msg", ""))}
'''
        skill = marketplace.create_local(
            name="echo_skill",
            version="1.0.0",
            entrypoint="main.py",
            code=code,
        )

        result = marketplace.test_skill(skill.skill_id, {"msg": "hello"})
        self.assertTrue(result.get("success"))
        self.assertEqual(result["output"]["echo"], "hello")
        self.assertEqual(result["output"]["length"], 5)

        marketplace.uninstall(skill.skill_id)

    def test_test_skill_returns_error_for_missing(self):
        from skills.store.marketplace import marketplace
        result = marketplace.test_skill("missing@0.0.0", {})
        self.assertFalse(result["success"])
        self.assertIn("not found", result["error"])

    def test_create_local_rejects_duplicate(self):
        from skills.store.marketplace import marketplace

        skill = marketplace.create_local(name="dup_skill", version="1.0.0", entrypoint="main.py")
        with self.assertRaises(ValueError):
            marketplace.create_local(name="dup_skill", version="1.0.0", entrypoint="main.py")
        marketplace.uninstall(skill.skill_id)

    def test_list_includes_created_skills(self):
        from skills.store.marketplace import marketplace

        before = marketplace.list_installed()
        skill = marketplace.create_local(name="list_skill", version="1.0.0", entrypoint="main.py", description="for listing")
        after = marketplace.list_installed()
        self.assertEqual(len(after), len(before) + 1)

        ids = [s.skill_id for s in after]
        self.assertIn("list_skill@1.0.0", ids)

        marketplace.uninstall(skill.skill_id)


class TestSkillsRouterEndpoints(unittest.TestCase):
    def setUp(self):
        from skills.store.marketplace import marketplace
        marketplace.uninstall("router_skill@0.1.0")
    def test_router_create_endpoint(self):
        from gateway.api_gateway.routers.skills import SkillCreateRequest
        req = SkillCreateRequest(
            name="router_skill",
            version="0.1.0",
            entrypoint="main.py",
            code="pass",
            description="created via router",
        )
        self.assertEqual(req.name, "router_skill")
        self.assertEqual(req.skill_type, "generic")

    def test_router_test_request_model(self):
        from gateway.api_gateway.routers.skills import SkillTestRequest
        req = SkillTestRequest(test_input={"key": "value"})
        self.assertEqual(req.test_input, {"key": "value"})


if __name__ == "__main__":
    unittest.main()
