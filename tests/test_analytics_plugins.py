from __future__ import annotations

import json
import unittest

from plugins.chart.generator import run_chart_generator
from plugins.code.interpreter import run_code_interpreter
from plugins.code.safe_ast import assert_code_ast_safe
from plugins.data.analysis import run_data_analysis
from plugins.file.sandbox import resolve_readable_sandbox_file, run_file_sandbox


class AnalyticsPluginsTests(unittest.IsolatedAsyncioTestCase):
    async def test_chart_generator_returns_png_base64(self) -> None:
        raw = await run_chart_generator("正弦")
        data = json.loads(raw)
        self.assertIn("image_base64", data)
        self.assertGreater(len(data["image_base64"]), 100)

    async def test_chart_generator_bar_heuristic(self) -> None:
        raw = await run_chart_generator("画一个柱状图 demo")
        data = json.loads(raw)
        self.assertGreater(len(data.get("image_base64", "")), 100)

    async def test_code_interpreter_print(self) -> None:
        payload = json.dumps({"code": "print('ok')"})
        raw = await run_code_interpreter(payload, "test-session-ci")
        data = json.loads(raw)
        self.assertIn("ok", data.get("stdout", ""))

    async def test_code_interpreter_extracts_fenced_block(self) -> None:
        msg = '说明\n```python\nprint("fenced")\n```\n'
        raw = await run_code_interpreter(msg, "test-session-fence")
        data = json.loads(raw)
        self.assertIn("fenced", data.get("stdout", ""))

    def test_ast_rejects_os_import(self) -> None:
        with self.assertRaises(ValueError):
            assert_code_ast_safe("import os\nos.system('ls')")

    async def test_data_analysis_describe(self) -> None:
        raw = await run_data_analysis(
            json.dumps({"operation": "describe", "data": "x,y\n1,2\n"}),
        )
        data = json.loads(raw)
        self.assertIn("result", data)

    def test_file_sandbox_roundtrip(self) -> None:
        sid = "test-fs-ci"
        w = json.loads(
            run_file_sandbox(
                json.dumps({"operation": "write", "path": "a/b.txt", "content": "x"}),
                sid,
            )
        )
        self.assertTrue(w.get("ok"))
        r = json.loads(
            run_file_sandbox(
                json.dumps({"operation": "read", "path": "a/b.txt"}),
                sid,
            )
        )
        self.assertEqual(r.get("content"), "x")
        p = resolve_readable_sandbox_file(sid, "a/b.txt")
        self.assertTrue(p.is_file())
        self.assertEqual(p.read_text(encoding="utf-8"), "x")


if __name__ == "__main__":
    unittest.main()
