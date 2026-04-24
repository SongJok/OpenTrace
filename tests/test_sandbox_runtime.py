import asyncio
import os
import unittest

from sandbox_runtime.executor import sandbox_executor


class SandboxRuntimeTests(unittest.TestCase):
    def test_local_ast_provider_runs_code(self):
        os.environ["SANDBOX_PROVIDER"] = "local_ast"
        r = asyncio.run(sandbox_executor.run("print(1+1)", "test-local"))
        self.assertEqual(r.returncode, 0)
        self.assertIn("2", r.stdout)
        self.assertEqual(r.provider, "local_ast")

    def test_gvisor_fallback_to_local(self):
        os.environ["SANDBOX_PROVIDER"] = "gvisor"
        r = asyncio.run(sandbox_executor.run("print('ok')", "test-gv"))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.provider, "local_ast")
        self.assertEqual(r.metadata.get("fallback_from"), "gvisor")


if __name__ == "__main__":
    unittest.main()
