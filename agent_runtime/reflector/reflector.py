"""
Reflector — post-execution self-reflection to improve future responses.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.json_parser import parse_llm_json
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

REFLECT_SYSTEM = """\
You are a self-reflective AI. Given a task, the steps taken, and the final result,
identify what went well and what could be improved next time.
Respond with JSON: {"strengths": [...], "improvements": [...], "lesson": "..."}
"""


@dataclass
class ReflectionResult:
    strengths: list[str]
    improvements: list[str]
    lesson: str


class Reflector:
    def __init__(self) -> None:
        self._gateway = get_model_gateway()

    async def reflect(
        self,
        task: str,
        steps: list[str],
        result: str,
    ) -> ReflectionResult:
        with tracer.start_as_current_span("reflector.reflect"):
            steps_text = "\n".join(f"- {s}" for s in steps)
            content = f"Task: {task}\n\nSteps:\n{steps_text}\n\nResult: {result}"
            resp = await self._gateway.complete(
                messages=[
                    LLMMessage(role="system", content=REFLECT_SYSTEM),
                    LLMMessage(role="user", content=content),
                ],
                role=LLMRole.COMPRESS,
                temperature=0.2,
                max_tokens=512,
            )
            return self._parse(resp.content)

    def _parse(self, text: str) -> ReflectionResult:
        parsed = parse_llm_json(text)
        if parsed and isinstance(parsed, dict):
            return ReflectionResult(
                strengths=parsed.get("strengths", []),
                improvements=parsed.get("improvements", []),
                lesson=parsed.get("lesson", ""),
            )
        return ReflectionResult(strengths=[], improvements=[], lesson=text.strip()[:200])
