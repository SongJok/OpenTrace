"""
Reasoning Engine — three-mode reasoning: Direct, CoT, Tree-of-Thought.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.identity.system_identity import build_system_identity, enforce_identity_output
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

_COT_SYSTEM = build_system_identity("""\
Think step-by-step. Structure your response as:
<thinking>...reasoning steps...</thinking>
<answer>...final answer...</answer>
""")

_DIRECT_SYSTEM = build_system_identity(
    "You are a precise, helpful assistant. Answer directly and accurately."
)

_TOT_EXPLORE = "Generate ONE possible solution approach for this task: {query}"
_TOT_JUDGE = """\
You are given multiple solution approaches for a task.
Task: {query}
Approaches:
{approaches}
Select the best approach and produce a final comprehensive answer.
"""


def enforce_identity(output: str) -> str:
    return enforce_identity_output(output)


@dataclass
class ReasoningResult:
    thinking: str
    answer: str
    strategy: str = "DIRECT"
    confidence: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ReasoningEngine:
    """
    Supports three reasoning modes:
      DIRECT — single LLM call, fast
      COT    — chain-of-thought with structured thinking tags
      TOT    — tree-of-thought: explore N branches, judge best
    """

    def __init__(self, tot_branches: int = 3) -> None:
        self._gateway = get_model_gateway()
        self.tot_branches = tot_branches

    async def run(
        self,
        query: str,
        context: str = "",
        strategy: str = "COT",
        temperature: float = 0.2,
        system_override: Optional[str] = None,
    ) -> ReasoningResult:
        with tracer.start_as_current_span("reasoning_engine.run") as span:
            span.set_attribute("strategy", strategy)
            span.set_attribute("query.length", len(query))

            if strategy == "TOT":
                result = await self._tot(query, context, system_override)
            elif strategy == "COT":
                result = await self._cot(query, context, temperature, system_override)
            else:
                result = await self._direct(query, context, temperature, system_override)

            span.set_attribute("answer.length", len(result.answer))
            return result

    async def _direct(
        self,
        query: str,
        context: str,
        temperature: float,
        system_override: Optional[str] = None,
    ) -> ReasoningResult:
        system_prompt = system_override or _DIRECT_SYSTEM
        messages = [LLMMessage(role="system", content=system_prompt)]
        if context:
            messages.append(LLMMessage(role="user", content=f"Context:\n{context}"))
        messages.append(LLMMessage(role="user", content=query))
        resp = await self._gateway.complete(messages=messages, role=LLMRole.QUERY, temperature=temperature)
        return ReasoningResult(thinking="", answer=enforce_identity(resp.content), strategy="DIRECT",
                               metadata={"tokens": resp.total_tokens})

    async def _cot(
        self,
        query: str,
        context: str,
        temperature: float,
        system_override: Optional[str] = None,
    ) -> ReasoningResult:
        system_prompt = system_override or _COT_SYSTEM
        messages = [LLMMessage(role="system", content=system_prompt)]
        if context:
            messages.append(LLMMessage(role="user", content=f"Context:\n{context}"))
        messages.append(LLMMessage(role="user", content=query))
        resp = await self._gateway.complete(messages=messages, role=LLMRole.QUERY, temperature=temperature)
        thinking, answer = self._parse_tags(resp.content)
        return ReasoningResult(thinking=thinking, answer=enforce_identity(answer), strategy="COT",
                               metadata={"tokens": resp.total_tokens})

    async def _tot(
        self,
        query: str,
        context: str,
        system_override: Optional[str] = None,
    ) -> ReasoningResult:
        ctx_prefix = f"Context: {context[:500]}\n" if context else ""

        # Explore branches in parallel（分支调用也需身份约束，避免无 system 时裸问模型）
        branch_msgs = [
            [
                LLMMessage(role="system", content=build_system_identity()),
                LLMMessage(role="user", content=ctx_prefix + _TOT_EXPLORE.format(query=query)),
            ]
            for _ in range(self.tot_branches)
        ]
        branch_resps = await asyncio.gather(
            *[
                self._gateway.complete(msgs, role=LLMRole.QUERY, temperature=0.7)
                for msgs in branch_msgs
            ],
            return_exceptions=True,
        )

        approaches = []
        for i, r in enumerate(branch_resps):
            if isinstance(r, Exception):
                logger.debug("ToT branch failed", branch=i, error=str(r))
            else:
                approaches.append(f"Approach {i+1}:\n{r.content[:400]}")

        if not approaches:
            return await self._cot(query, context, temperature=0.3)

        judge_prompt = _TOT_JUDGE.format(
            query=query, approaches="\n\n".join(approaches)
        )
        judge_system = system_override or _COT_SYSTEM
        judge_resp = await self._gateway.complete(
            messages=[
                LLMMessage(role="system", content=judge_system),
                LLMMessage(role="user", content=judge_prompt),
            ],
            role=LLMRole.QUERY,
            temperature=0.1,
        )
        thinking, answer = self._parse_tags(judge_resp.content)
        return ReasoningResult(
            thinking=thinking,
            answer=enforce_identity(answer),
            strategy="TOT",
            metadata={"branches": len(approaches)},
        )

    def _parse_tags(self, text: str) -> tuple[str, str]:
        import re
        thinking = ""
        answer = text
        t = re.search(r"<thinking>(.*?)</thinking>", text, re.DOTALL)
        a = re.search(r"<answer>(.*?)</answer>", text, re.DOTALL)
        if t:
            thinking = t.group(1).strip()
        if a:
            answer = a.group(1).strip()
        return thinking, answer
