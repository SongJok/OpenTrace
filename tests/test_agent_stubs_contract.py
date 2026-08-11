"""P1-A 实现后 Agent 桩的契约测试。"""

import asyncio
import unittest


class TestVisionAgent:
    """Contract: VisionAgent handles image inputs."""

    def test_returns_error_on_no_images_by_default(self):
        from agents.base import TaskMessage
        from agents.vision_agent import VisionAgent

        async def _run():
            agent = VisionAgent()
            task = TaskMessage(
                task_id="t1",
                agent_type="vision",
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
