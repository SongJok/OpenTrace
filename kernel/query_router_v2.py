"""L0 规则路由 — 零 LLM 快速路径（<1ms）。

V5 路由层级之一：
  L0RuleRouter → ComplexityEngine → TinyRouter(L1) → SemanticCache → ContextAssembler

纯正则/规则匹配，无 LLM；处理身份、问候、FAQ、斜杠命令。
其余 hit=False，落入 L1/L4。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from infra.config.settings import settings
from kernel.identity.system_identity import CANONICAL_IDENTITY_RESPONSE, is_identity_user_query


# ── 模式定义 ──────────────────────────────────────────────────────

_IDENTITY_PATTERNS = re.compile(
    r"(你是谁|你是什么|哪位|什么模型|什么助手|什么ai|哪家公司的|"
    r"who\s+are\s+you|what\s+are\s+you|what\s+model|"
    r"你叫什么|你的名字|你是什么模型|介绍.*自己|介绍一下你)",
    re.IGNORECASE,
)

_GREETING_PATTERNS = re.compile(
    r"^(你好|您好|hi|hello|hey|嗨|早上好|晚上好|下午好|"
    r"good\s*morning|good\s*evening|good\s*afternoon|"
    r"好久不见|在吗|在不在)[\s!！。.,，]*$",
    re.IGNORECASE,
)

_SLASH_COMMAND = re.compile(
    r"^/(rag|data|web|tool|tools|skills|vision|anomaly|rule)\s+(.+)",
    re.IGNORECASE,
)

# Weather / time → tool agent (L0 fast path, no RAG)
_WEATHER_QUERY = re.compile(
    r"(天气|气温|温度|下雨|下雪|风力|湿度|预报|weather|forecast|temperature)",
    re.IGNORECASE,
)
_TIME_QUERY = re.compile(
    r"(几点|现在几点|当前时间|what\s+time|current\s+time)",
    re.IGNORECASE,
)

# 斜杠命令别名到 force_mode 值的映射
_SLASH_FORCE_MODE: dict[str, str] = {
    "rag": "rag",
    "data": "data_query",
    "web": "web",
    "tool": "tool",
    "tools": "tool",
    "skills": "skills",
    "vision": "vision",
    "anomaly": "anomaly_tracking",
    "rule": "rule_engine",
}

# FAQ 预设回答 — 常见问题的确定性回答
_FAQ_RESPONSES: dict[str, str] = {
    "你能做什么": (
        "我可以帮你进行数据查询与分析、文档检索（RAG）、网页搜索、"
        "工具调用（时间/天气/代码）、技能执行等任务。请直接告诉我你的需求。"
    ),
    "你有哪些功能": (
        "我支持以下功能：\n"
        "1. 数据查询与分析（Text2SQL）\n"
        "2. 文档检索与问答（RAG）\n"
        "3. 网页搜索\n"
        "4. 工具调用（时间/天气/代码执行）\n"
        "5. 图片分析\n"
        "6. 规则引擎匹配\n"
        "请告诉我你想使用哪项功能。"
    ),
    "怎么用": "直接告诉我你的问题或需求即可，我会自动判断需要调用哪些能力来回答你。",
    "怎么使用": "直接告诉我你的问题或需求即可，我会自动判断需要调用哪些能力来回答你。",
    "使用帮助": "你可以直接向我提问，也支持使用斜杠命令：\n/rag <问题> — 文档检索\n/data <问题> — 数据查询\n/web <问题> — 网页搜索",
    "帮助": "你可以直接向我提问，也支持使用斜杠命令：\n/rag <问题> — 文档检索\n/data <问题> — 数据查询\n/web <问题> — 网页搜索",
    "help": "You can ask me questions directly or use slash commands:\n/rag <query> — Document search\n/data <query> — Data query\n/web <query> — Web search",
    "hello": "你好！我是 OpenTrace，有什么可以帮你的？",
    "hi": "你好！有什么可以帮你的？",
    "hey": "你好！有什么可以帮你的？",
}

# FAQ 正则模式（比精确匹配更灵活）
_FAQ_PATTERNS: list[tuple[re.Pattern, str]] = [
    (
        re.compile(
            r"你能做什么|你可以做什么|你有哪些?功能|你会什么|你能干什么|"
            r"你能帮我.*什么|怎么帮我|如何帮我|可以帮我什么|你的能力|你有什么用"
        ),
        "你能做什么",
    ),
    (re.compile(r"怎么用|怎么使用|使用帮助|帮助|help"), "帮助"),
    (re.compile(r"^(hello|hi|hey)[\s!！。.,，]*$", re.IGNORECASE), "hello"),
]


# ── L0RouteResult ──────────────────────────────────────────────────────


@dataclass
class L0RouteResult:
    hit: bool = False
    answer: str | None = None
    route: str = "v4"  # "identity" | "faq" | "force_mode" | "v4"
    force_mode: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ── L0RuleRouter ─────────────────────────────────────────────────────


class L0RuleRouter:
    """零 LLM 规则路由器，用于 V5 路由层。

    使用纯正则匹配，以亚毫秒延迟处理身份查询、问候、FAQ 和斜杠命令。
    """

    async def route(
        self,
        query: str,
        session_id: str = "",
        is_multi: bool = False,
        conversation_history: list | None = None,
    ) -> L0RouteResult:
        if not query or not query.strip():
            return L0RouteResult(hit=True, answer="", route="faq")

        q = query.strip()
        q_lower = q.lower()

        # ── 1. 斜杠命令（/rag、/data、/web 等） ─────────────────
        slash_match = _SLASH_COMMAND.match(q)
        if slash_match:
            force_alias = slash_match.group(1).lower()
            raw_query = slash_match.group(2).strip()
            force_mode = _SLASH_FORCE_MODE.get(force_alias, force_alias)
            return L0RouteResult(
                hit=True,
                answer=raw_query,
                route="force_mode",
                force_mode=force_mode,
                metadata={"method": "slash_command", "force_mode": force_mode},
            )

        # ── 2. 身份查询 ─────────────────────────────────────────
        if is_identity_user_query(q) or _IDENTITY_PATTERNS.search(q):
            # 仅在增强身份功能禁用或不适用时处理
            if not settings.kernel_enriched_identity_enabled:
                return L0RouteResult(
                    hit=True,
                    answer=CANONICAL_IDENTITY_RESPONSE,
                    route="identity",
                    metadata={"method": "rule", "identity_handler": "canonical"},
                )
            # 启用增强身份时，仍返回 hit 以便内核通过 MinShort LLM 增强回答
            return L0RouteResult(
                hit=True,
                answer=CANONICAL_IDENTITY_RESPONSE,
                route="identity",
                metadata={"method": "rule", "identity_handler": "enrichable"},
            )

        # ── 3. 问候 ────────────────────────────────────────────
        if _GREETING_PATTERNS.match(q) or _GREETING_PATTERNS.match(q_lower):
            greeting_answer = (
                "你好！我是 OpenTrace，一个基于认知内核构建的智能助手。有什么可以帮你的？"
            )
            return L0RouteResult(
                hit=True,
                answer=greeting_answer,
                route="faq",
                metadata={"method": "rule", "category": "greeting"},
            )

        # ── 4. FAQ 模式 ─────────────────────────────────────
        for pattern, key in _FAQ_PATTERNS:
            if pattern.search(q):
                answer = _FAQ_RESPONSES.get(key, "")
                if answer:
                    return L0RouteResult(
                        hit=True,
                        answer=answer,
                        route="faq",
                        metadata={"method": "rule", "category": "faq", "faq_key": key},
                    )

        # ── 5. 天气 / 时间 → tool（避免误走 RAG/web） ─────
        if not is_multi and (_WEATHER_QUERY.search(q) or _TIME_QUERY.search(q)):
            return L0RouteResult(
                hit=True,
                answer=q,
                route="force_mode",
                force_mode="tool",
                metadata={
                    "method": "rule",
                    "category": "weather" if _WEATHER_QUERY.search(q) else "time",
                    "task_type": "weather" if _WEATHER_QUERY.search(q) else "time",
                },
            )

        # ── 6. 无匹配 — 落入 L1/L4 ─────────────────────────
        return L0RouteResult()
