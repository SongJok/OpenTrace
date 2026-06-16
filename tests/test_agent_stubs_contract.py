"""P1-A 实现后 Agent 桩的契约测试。"""

import asyncio
import unittest


class TestRuleEngineAgent:
    """Contract: RuleEngineAgent matches rules and returns results."""

    def test_returns_result_on_rule_match(self):
        from agents.rule_engine_agent import RuleEngineAgent
        from agents.base import TaskMessage

        async def _run():
            agent = RuleEngineAgent()
            task = TaskMessage(
                task_id="t1", agent_type="rules",
                query="数据隐私保护规则是什么",
                params={"rule_category": "data_privacy"},
            )
            result = await agent.execute(task)
            assert result.status == "success"
            assert result.agent_type == "rules"
            assert len(result.content) > 0
            assert result.confidence > 0.3

        asyncio.run(_run())

    def test_returns_empty_on_no_match(self):
        from agents.rule_engine_agent import RuleEngineAgent
        from agents.base import TaskMessage

        async def _run():
            agent = RuleEngineAgent()
            task = TaskMessage(
                task_id="t1", agent_type="rules",
                query="今天天气怎么样",
                params={},
            )
            result = await agent.execute(task)
            assert result.status == "success"
            assert result.confidence == 0.1
            assert result.metadata["matched_rules"] == []

        asyncio.run(_run())

    def test_has_correct_agent_type(self):
        from agents.rule_engine_agent import RuleEngineAgent
        agent = RuleEngineAgent()
        assert agent.agent_type == "rules"


class TestVisionAgent:
    """Contract: VisionAgent handles image inputs."""

    def test_returns_error_on_no_images_by_default(self):
        from agents.vision_agent import VisionAgent
        from agents.base import TaskMessage

        async def _run():
            agent = VisionAgent()
            task = TaskMessage(
                task_id="t1", agent_type="vision",
                query="描述这张图片",
                params={},
            )
            result = await agent.execute(task)
            assert result.status == "error"
            assert result.error == "vision_input_required:image_urls_or_image_data"
            assert result.metadata.get("governance") == "vision_input_required"

        asyncio.run(_run())

    def test_has_correct_agent_type(self):
        from agents.vision_agent import VisionAgent
        agent = VisionAgent()
        assert agent.agent_type == "vision"

    def test_has_vision_flag_in_settings(self):
        from infra.config.settings import settings
        assert hasattr(settings, "kernel_agent_vision_enabled")


if __name__ == "__main__":
    unittest.main()
