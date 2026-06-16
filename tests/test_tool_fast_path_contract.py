"""Tool fast path — bypass full runtime for weather/time."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from kernel.cognitive_controls import classify_intent


class ToolFastPathContractTests(unittest.TestCase):
    def test_should_use_for_weather_intent(self):
        from kernel.fast_tool_path import should_use_tool_fast_path

        lock = classify_intent("今天天气怎么样？")
        self.assertEqual(lock.task_type, "weather")
        self.assertTrue(should_use_tool_fast_path(lock))

    def test_should_use_for_force_tool_weather(self):
        from kernel.fast_tool_path import should_use_tool_fast_path

        lock = classify_intent("北京天气", force_mode="tool")
        self.assertTrue(should_use_tool_fast_path(lock, force_mode="tool"))

    def test_l0_weather_still_force_tool(self):
        from kernel.query_router_v2 import L0RuleRouter

        async def _run():
            r = await L0RuleRouter().route("今天天气怎么样？")
            assert r.force_mode == "tool"

        asyncio.run(_run())

    @patch("agents.tool_agent.ToolAgent.execute", new_callable=AsyncMock)
    def test_run_tool_fast_path_returns_kernel_response(self, mock_exec):
        from agents.base import AgentResult
        from kernel.cognitive_kernel import KernelRequest
        from kernel.fast_tool_path import run_tool_fast_path

        mock_exec.return_value = AgentResult(
            task_id="t1",
            agent_type="tool",
            status="success",
            content="晴，25℃",
            confidence=0.9,
        )

        req = KernelRequest(
            query="今天天气怎么样？",
            session_id="s1",
            metadata={"intent_lock": classify_intent("今天天气怎么样？").to_dict()},
        )

        async def _run():
            return await run_tool_fast_path(req)

        resp = asyncio.run(_run())
        self.assertEqual(resp.route, "tool_fast_path")
        self.assertIn("25", resp.content)
        self.assertTrue((resp.metadata or {}).get("tool_fast_path"))
        self.assertEqual((resp.metadata or {}).get("registry_agent"), "tool")
        self.assertEqual((resp.metadata or {}).get("capability_type"), "tool")
        audit = (resp.metadata or {}).get("audit") or {}
        self.assertEqual(audit.get("permission_scope"), "tier0_builtin_tool")


if __name__ == "__main__":
    unittest.main()