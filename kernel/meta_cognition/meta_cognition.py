"""
Meta-Cognition — three-tier quality control:
  score >= 0.8  -> accept
  score >= 0.6  -> refine (improve without full retry)
  score <  0.6  -> retry (re-run up to max_retries)

Also performs hallucination risk detection.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.identity.system_identity import build_system_identity
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

EVAL_SYSTEM = build_system_identity("""\
You are a strict quality evaluator. Rate the answer quality.
Respond ONLY with JSON:
{"score": 0.0-1.0, "hallucination_risk": 0.0-1.0, "reason": "...", "issues": ["..."]}
""")

REFINE_SYSTEM = build_system_identity("Improve the following answer based on the feedback. Return only the improved answer.")


@dataclass
class ValidationResult:
    passed: bool
    score: float
    reason: str
    final_answer: Any
    hallucination_risk: float = 0.0
    issues: list[str] = field(default_factory=list)


class MetaCognition:
    """
    Three-tier quality gate:
      score >= high_threshold  -> pass immediately
      score >= low_threshold   -> refine once
      score <  low_threshold   -> retry up to max_retries
    """

    def __init__(
        self,
        high_threshold: float = 0.8,
        low_threshold: float = 0.6,
        max_retries: int = 2,
    ) -> None:
        self.high_threshold = high_threshold
        self.low_threshold = low_threshold
        self.max_retries = max_retries
        self._gateway = get_model_gateway()

    async def validate(
        self,
        query: str,
        result: Any,
        retry_fn: Optional[Callable] = None,
    ) -> ValidationResult:
        with tracer.start_as_current_span("meta_cognition.validate") as span:
            current = result

            for attempt in range(self.max_retries + 1):
                score, h_risk, reason, issues = await self._score(query, str(current))
                span.set_attribute("meta.score", score)
                span.set_attribute("meta.attempt", attempt)
                span.set_attribute("meta.hallucination_risk", h_risk)

                if h_risk > 0.7:
                    logger.warning("High hallucination risk", risk=h_risk, attempt=attempt)

                # Tier 1: Accept
                if score >= self.high_threshold:
                    return ValidationResult(
                        passed=True, score=score, reason=reason,
                        final_answer=current, hallucination_risk=h_risk, issues=issues,
                    )

                # Tier 2: Refine
                if score >= self.low_threshold:
                    try:
                        current = await self._refine(query, str(current), reason, issues)
                        logger.info("MetaCognition: refined answer", attempt=attempt)
                        continue
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Refine failed", error=str(exc))

                # Tier 3: Retry
                logger.warning("MetaCognition: low score, retrying", score=score, attempt=attempt)
                if retry_fn and attempt < self.max_retries:
                    try:
                        current = await retry_fn()
                        continue
                    except Exception as exc:  # noqa: BLE001
                        logger.error("Retry fn failed", error=str(exc))
                        break
                elif attempt >= self.max_retries:
                    break

            # score/h_risk are guaranteed assigned by the loop above (min 1 iteration)
        return ValidationResult(
                passed=score >= self.low_threshold,  # type: ignore[possibly-undefined]
                score=score,  # type: ignore[possibly-undefined]
                reason=reason,  # type: ignore[possibly-undefined]
                final_answer=current,
                hallucination_risk=h_risk,  # type: ignore[possibly-undefined]
                issues=issues,  # type: ignore[possibly-undefined]
            )

    async def _score(self, query: str, answer: str) -> tuple[float, float, str, list[str]]:
        try:
            resp = await self._gateway.complete(
                messages=[
                    LLMMessage(role="system", content=EVAL_SYSTEM),
                    LLMMessage(role="user", content=f"Query: {query}\n\nAnswer: {answer[:2000]}"),
                ],
                role=LLMRole.COMPRESS,
                temperature=0.0,
                max_tokens=200,
            )
            match = re.search(r"\{.*\}", resp.content, re.DOTALL)
            if match:
                d = json.loads(match.group(0))
                return (
                    float(d.get("score", 0.5)),
                    float(d.get("hallucination_risk", 0.0)),
                    d.get("reason", ""),
                    d.get("issues", []),
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug("MetaCognition score parse failed", error=str(exc))
        return 0.5, 0.0, "parse_error", []

    async def _refine(self, query: str, answer: str, reason: str, issues: list[str]) -> str:
        issue_text = "; ".join(issues) if issues else reason
        resp = await self._gateway.complete(
            messages=[
                LLMMessage(role="system", content=REFINE_SYSTEM),
                LLMMessage(
                    role="user",
                    content=(
                        f"Original question: {query}\n"
                        f"Current answer: {answer[:1500]}\n"
                        f"Issues: {issue_text}\n\n"
                        "Please provide an improved answer:"
                    ),
                ),
            ],
            role=LLMRole.QUERY,
            temperature=0.3,
            max_tokens=2048,
        )
        return resp.content

    async def should_retry(self, step, state) -> bool:
        if getattr(step, "reflection_score", None) is None:
            return False
        retry_count = int(getattr(state, "metadata", {}).get("retry_count", 0))
        max_retries = int(getattr(state, "metadata", {}).get("max_retries", self.max_retries))
        if float(step.reflection_score) < self.low_threshold and retry_count < max_retries:
            state.metadata["retry_count"] = retry_count + 1
            return True
        return False
