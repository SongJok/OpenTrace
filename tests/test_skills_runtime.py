import tempfile
import unittest
from pathlib import Path

from skills.runtime.loader import SkillLoader
from skills.runtime.manifest import SkillManifest
from skills.runtime.verifier import SkillSignatureVerifier


class SkillRuntimeTests(unittest.TestCase):
    def test_manifest_parse_json(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "skill.json").write_text(
                '{"name":"demo","version":"0.1.0","entrypoint":"main.py","required_connectors":["github"],"permissions":["repo:read"]}',
                encoding="utf-8",
            )
            m = SkillLoader().load_manifest(d)
            self.assertIsInstance(m, SkillManifest)
            self.assertEqual(m.name, "demo")
            self.assertEqual(m.required_connectors, ["github"])

    def test_signature_verifier_prefix(self):
        v = SkillSignatureVerifier()
        m = SkillManifest(name="a", version="1", entrypoint="e", signature="")
        self.assertTrue(v.verify(m))


if __name__ == "__main__":
    unittest.main()
