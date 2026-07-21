"""
意图引擎 — 专用结构化意图解析器。

使用小型 LLM 调用将原始用户查询解析为丰富的 Intent 对象。
当 LLM 不可用时回退到启发式解析。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer
from kernel.identity.system_identity import build_system_identity
from kernel.json_parser import parse_llm_json
from model.llm_adapter.base import LLMMessage
from model.model_gateway.gateway import LLMRole, get_model_gateway

logger = get_logger(__name__)
tracer = get_tracer(__name__)

INTENT_SYSTEM = build_system_identity(
    """\
You are an intent classifier. Analyse the user query and return JSON ONLY:
{
  "category": "qa|search|task|analysis|creative|code|math|other",
  "complexity": 0.0-1.0,
  "multi_step": true|false,
  "requires_tools": true|false,
  "requires_knowledge": true|false,
  "language": "en|zh|...",
  "entities": ["..."],
  "keywords": ["..."]
}
No explanation, no markdown, JSON only.
"""
)


@dataclass
class Intent:
    raw_query: str
    category: str = "qa"
    complexity: float = 0.5
    multi_step: bool = False
    requires_tools: bool = False
    requires_knowledge: bool = False
    language: str = "en"
    entities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    session_context: dict[str, Any] = field(default_factory=dict)

    # 为向后兼容 PolicyEngine 保留的便捷别名
    @property
    def raw(self) -> str:
        return self.raw_query


class IntentEngine:
    """
    将原始用户查询解析为结构化 Intent。
    使用规划 LLM（小型/快速）进行分类。
    出错时回退到启发式解析。
    """

    def __init__(self) -> None:
        self._gateway = get_model_gateway()

    async def parse(
        self,
        query: str,
        session_context: dict[str, Any] | None = None,
    ) -> Intent:
        with tracer.start_as_current_span("intent_engine.parse") as span:
            span.set_attribute("query.length", len(query))

            try:
                resp = await self._gateway.complete(
                    messages=[
                        LLMMessage(role="system", content=INTENT_SYSTEM),
                        LLMMessage(role="user", content=query[:1000]),
                    ],
                    role=LLMRole.PLANNING,
                    temperature=0.0,
                    max_tokens=256,
                )
                intent = self._parse_llm(query, resp.content, session_context)
            except Exception as exc:  # noqa: BLE001
                logger.debug("IntentEngine LLM failed, using heuristics", error=str(exc))
                intent = self._heuristic(query, session_context)

            span.set_attribute("intent.category", intent.category)
            span.set_attribute("intent.complexity", intent.complexity)
            span.set_attribute("intent.multi_step", intent.multi_step)
            return intent

    def _parse_llm(
        self,
        query: str,
        text: str,
        session_context: dict[str, Any] | None,
    ) -> Intent:
        parsed = parse_llm_json(text)
        if not parsed or not isinstance(parsed, dict):
            return self._heuristic(query, session_context)
        try:
            d = parsed
            return Intent(
                raw_query=query,
                category=d.get("category", "qa"),
                complexity=float(d.get("complexity", 0.5)),
                multi_step=bool(d.get("multi_step", False)),
                requires_tools=bool(d.get("requires_tools", False)),
                requires_knowledge=bool(d.get("requires_knowledge", False)),
                language=d.get("language", "en"),
                entities=d.get("entities", []),
                keywords=d.get("keywords", []),
                session_context=session_context or {},
            )
        except Exception:  # noqa: BLE001
            return self._heuristic(query, session_context)

    def _heuristic(self, query: str, session_context: dict[str, Any] | None) -> Intent:
        q = query.lower()
        multi_step = any(
            w in q for w in ["then", "after", "step", "first", "next", "finally", "lastly"]
        )
        requires_tools = any(
            w in q for w in ["search", "calculate", "run", "execute", "fetch", "find", "look up"]
        )
        requires_knowledge = any(
            w in q for w in ["what", "who", "where", "when", "explain", "why", "how", "tell me"]
        )
        is_code = any(w in q for w in ["code", "function", "class", "implement", "debug", "error"])
        is_math = any(w in q for w in ["calculate", "solve", "equation", "compute", "integral"])

        category = (
            "code" if is_code else ("math" if is_math else ("search" if requires_tools else "qa"))
        )
        complexity = min(
            1.0, len(query) / 400 + (0.3 if multi_step else 0.0) + (0.2 if requires_tools else 0.0)
        )

        return Intent(
            raw_query=query,
            category=category,
            complexity=complexity,
            multi_step=multi_step,
            requires_tools=requires_tools,
            requires_knowledge=requires_knowledge,
            language="zh" if any("\u4e00" <= c <= "\u9fff" for c in query) else "en",
            keywords=list(set(query.lower().split()))[:10],
            session_context=session_context or {},
        )
