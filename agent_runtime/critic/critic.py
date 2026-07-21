"""
Critic — evaluates intermediate agent outputs and provides feedback.
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

CRITIC_SYSTEM = """\
You are a critical evaluator reviewing an agent's intermediate output.
Score it 0.0-1.0 and provide specific actionable feedback.
Respond with JSON: {"score": float, "feedback": "...", "ok": bool}
"""


@dataclass
class CriticResult:
    score: float
    feedback: str
    ok: bool


class Critic:
    def __init__(self, threshold: float = 0.6) -> None:
        self.threshold = threshold
        self._gateway = get_model_gateway()

    async def critique(
        self,
        task: str,
        output: str,
    ) -> CriticResult:
        with tracer.start_as_current_span("critic.critique"):
            resp = await self._gateway.complete(
                messages=[
                    LLMMessage(role="system", content=CRITIC_SYSTEM),
                    LLMMessage(
                        role="user",
                        content=f"Task: {task}\n\nOutput: {output[:2000]}",
                    ),
                ],
                role=LLMRole.COMPRESS,
                temperature=0.0,
                max_tokens=256,
            )
            return self._parse(resp.content)

    def _parse(self, text: str) -> CriticResult:
        parsed = parse_llm_json(text)
        if parsed and isinstance(parsed, dict):
            score = float(parsed.get("score", 0.5))
            return CriticResult(
                score=score,
                feedback=parsed.get("feedback", ""),
                ok=parsed.get("ok", score >= self.threshold),
            )
        return CriticResult(score=0.5, feedback=text.strip()[:200], ok=False)
