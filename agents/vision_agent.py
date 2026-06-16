"""视觉分析 Agent — 解读图像与图表。

使用 LLMRole.VISION（qwen3.6-vl-plus）进行多模态图像理解。
"""

from __future__ import annotations

from agents.base import AgentResult, BaseAgent, TaskMessage


class VisionAgent(BaseAgent):
    agent_type = "vision"

    def __init__(self) -> None:
        super().__init__(agent_type=self.agent_type)

    async def execute(self, task: TaskMessage) -> AgentResult:
        params = getattr(task, "params", None) or {}
        query = getattr(task, "query", "") or ""

        image_urls: list[str] = params.get("image_urls", [])
        image_data: list[str] = params.get("image_data", [])  # base64-encoded

        if not image_urls and not image_data:
            from infra.config.settings import settings

            strict = bool(getattr(settings, "kernel_vision_require_images", True))
            if strict:
                return AgentResult(
                    task_id=task.task_id,
                    agent_type=self.agent_type,
                    status="error",
                    content="",
                    confidence=0.0,
                    error="vision_input_required:image_urls_or_image_data",
                    metadata={
                        "note": "no images provided",
                        "degraded": False,
                        "governance": "vision_input_required",
                    },
                )
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="",
                confidence=0.0,
                metadata={
                    "note": "no images provided",
                    "degraded": True,
                    "degradation_reason": "vision_no_input_lenient_mode",
                },
            )

        try:
            from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

            gw = get_model_gateway()

            # Build multimodal messages
            user_content: list[dict] = []
            if query:
                user_content.append({"type": "text", "text": query})

            for url in image_urls:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": url},
                })
            for b64 in image_data:
                user_content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64}"},
                })

            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are a vision analysis assistant. Describe images "
                        "clearly and accurately in Chinese. For charts and graphs, "
                        "extract key data points and trends."
                    ),
                ),
                LLMMessage(role="user", content=user_content),
            ]

            response = await gw.complete(messages, role=LLMRole.VISION)
            content = (response.content or "").strip()

            conf = 0.8 if content else 0.0
            ev_objs = []
            if content:
                ev_objs.append(
                    self._make_evidence_object(
                        content=content,
                        source_type="vision",
                        credibility=conf,
                        relevance=0.75,
                        content_type="image_description",
                        image_count=len(image_urls) + len(image_data),
                    )
                )
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=content,
                confidence=conf,
                metadata={
                    "image_count": len(image_urls) + len(image_data),
                    "has_response": bool(content),
                },
                evidence_objects=ev_objs,
            )
        except Exception as exc:
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="error",
                content="",
                error=str(exc),
                confidence=0.0,
            )
