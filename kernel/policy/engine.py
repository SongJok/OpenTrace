"""
Policy Engine — hybrid rule + LLM cognitive router.
Reads runtime strategy overrides pushed by LearningEngine.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.identity.system_identity import build_system_identity
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)


class Route(str, Enum):
    FAST = "FAST"
    REASON = "REASON"
    TOOL = "TOOL"
    MULTI_AGENT = "MULTI_AGENT"


class Strategy(str, Enum):
    DIRECT = "DIRECT"
    COT = "COT"
    TOT = "TOT"
    RAG = "RAG"
    SEARCH = "SEARCH"


@dataclass
class Decision:
    route: Route
    strategy: Strategy = Strategy.DIRECT
    confidence: float = 1.0
    rationale: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# Backwards-compat
class DecisionType(str, Enum):
    FAST_RESPONSE = "FAST"
    DEEP_REASONING = "REASON"
    RAG = "TOOL"
    TOOL = "TOOL"
    MULTI_AGENT = "MULTI_AGENT"


POLICY_SYSTEM = build_system_identity("""\
你是一个决策引擎。根据以下信息，决定是否需要调用工具（文档检索、Web搜索、代码执行）或者直接回答。

规则：
- 如果用户问的是最新信息（包含“今天”、“最新”、“新闻”、“latest”、“today”），必须调用 Web 搜索工具。
- 如果上下文中的文档相似度最高分低于 0.7，应该调用文档检索工具重新检索。
- 如果用户的问题是代码编写类，应该调用代码执行工具。
- 直接回答时，回答长度不超过 500 字。
- 工具调用之间必须间隔至少一次观察。

输出 JSON ONLY：
{"route": "FAST|REASON|TOOL|MULTI_AGENT", "strategy": "DIRECT|COT|TOT|RAG|SEARCH", "confidence": 0.0-1.0, "rationale": "...", "tool_calls": [{"tool": "...", "query": "..."}], "final_answer": "..."}
""")

_TOOL_KW = ["search", "look up", "find", "latest", "current", "today",
            "calculate", "compute", "fetch", "weather", "price", "news"]
_SEARCH_KW = ["search", "find", "latest", "look up", "news", "weather"]


class PolicyEngine:
    """
    Hybrid routing policy.
    Stage 1 — zero-latency rules.
    Stage 2 — LLM for 0.45-0.65 ambiguous band only.
    Supports runtime strategy injection from LearningEngine.
    """

    def __init__(self, use_llm_fallback: bool = True) -> None:
        self._use_llm = use_llm_fallback
        self._gateway = get_model_gateway()
        self._runtime_strategy: dict[str, Any] = {}

    def update_strategy(self, strategy: dict[str, Any]) -> None:
        """Called by LearningEngine to push runtime strategy updates."""
        self._runtime_strategy.update(strategy)
        logger.info("PolicyEngine strategy updated", strategy=strategy)

    async def decide(self, intent: Any, context: Any = None) -> Decision:
        with tracer.start_as_current_span("policy_engine.decide") as span:
            decision = self._fast_rules(intent, context)

            if decision is None and self._use_llm:
                try:
                    decision = await self._llm_decide(intent, context)
                    span.set_attribute("policy.source", "llm")
                except Exception as exc:  # noqa: BLE001
                    logger.warning("LLM policy failed", error=str(exc))

            if decision is None:
                decision = Decision(route=Route.REASON, strategy=Strategy.COT, rationale="fallback")

            decision = self._apply_depth_override(decision)
            span.set_attribute("policy.route", decision.route.value)
            span.set_attribute("policy.strategy", decision.strategy.value)
            logger.debug("Policy decision", route=decision.route.value, strategy=decision.strategy.value)
            return decision

    def _apply_depth_override(self, decision: Decision) -> Decision:
        """Upgrade strategy when LearningEngine signals reasoning_depth=deep."""
        depth = self._runtime_strategy.get("reasoning_depth")
        if depth == "deep" and decision.route == Route.REASON and decision.strategy == Strategy.COT:
            decision.strategy = Strategy.TOT
            decision.rationale += " [learning:deep→TOT]"
        return decision

    def _fast_rules(self, intent: Any, context: Any = None) -> Optional[Decision]:
        if hasattr(intent, "raw_query"):
            query = intent.raw_query.lower()
            complexity: float = getattr(intent, "complexity", 0.5)
            multi_step: bool = getattr(intent, "multi_step", False)
            category: str = getattr(intent, "category", "qa")
        else:
            query = str(intent).lower()
            complexity = min(1.0, len(query) / 400)
            multi_step = any(w in query for w in ["then", "after", "step", "first", "next"])
            category = "qa"

        if complexity < 0.2 and not multi_step:
            return Decision(route=Route.FAST, strategy=Strategy.DIRECT, rationale="Low complexity")

        if any(kw in query for kw in _TOOL_KW) or category in ("search", "math"):
            strat = Strategy.SEARCH if any(k in query for k in _SEARCH_KW) else Strategy.RAG
            return Decision(route=Route.TOOL, strategy=strat, rationale="Tool keyword")

        if context and isinstance(context, list):
            doc_scores = [
                float(getattr(c, "score", 1.0))
                for c in context
                if getattr(c, "source_type", "") == "document"
            ]
            if doc_scores and max(doc_scores) < 0.7:
                return Decision(route=Route.TOOL, strategy=Strategy.RAG, rationale="Low document confidence")

        if multi_step and complexity > 0.6:
            return Decision(route=Route.MULTI_AGENT, strategy=Strategy.COT, rationale="Multi-step")

        if category == "code":
            return Decision(route=Route.REASON, strategy=Strategy.COT, rationale="Code")

        # Narrow ambiguous band — only truly uncertain range goes to LLM
        if 0.45 <= complexity <= 0.65:
            return None

        if complexity > 0.5:
            strat = Strategy.TOT if complexity > 0.8 else Strategy.COT
            return Decision(route=Route.REASON, strategy=strat, rationale="Moderate-high")

        return Decision(route=Route.FAST, strategy=Strategy.DIRECT, rationale="Default fast")

    async def _llm_decide(self, intent: Any, context: Any) -> Decision:
        query = intent.raw_query if hasattr(intent, "raw_query") else str(intent)
        ctx_str = ""
        if context:
            if isinstance(context, list):
                ctx_str = " ".join(getattr(c, "content", str(c))[:80] for c in context[:3])
            else:
                ctx_str = str(context)[:200]
        resp = await self._gateway.complete(
            messages=[
                LLMMessage(role="system", content=POLICY_SYSTEM),
                LLMMessage(role="user", content=f"query: {query[:300]}\ncontext: {ctx_str}"),
            ],
            role=LLMRole.PLANNING,
            temperature=0.0,
            max_tokens=128,
        )
        return self._parse_llm(resp.content)

    def _parse_llm(self, text: str) -> Decision:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                d = json.loads(m.group(0))
                return Decision(
                    route=Route(d.get("route", "REASON").upper()),
                    strategy=Strategy(d.get("strategy", "COT").upper()),
                    confidence=float(d.get("confidence", 0.8)),
                    rationale=d.get("rationale", ""),
                    metadata={
                        "tool_calls": d.get("tool_calls", []),
                        "final_answer": d.get("final_answer"),
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        return Decision(route=Route.REASON, strategy=Strategy.COT, rationale="parse fallback")

    def decide_sync(self, intent: Any) -> Decision:
        d = self._fast_rules(intent, None)
        return self._apply_depth_override(d) if d else Decision(route=Route.REASON, strategy=Strategy.COT)
