"""轻量路由 — 用小型 LLM 做查询分类与简单回答分流。

将查询路由到合适层级：
  - simple：问候/FAQ → FAST LLM 直接回答
  - knowledge：需 RAG → 知识流水线
  - complex：需完整推理 → 落入 V4 编排器

分类用 LLMRole.ROUTER，简单回答用 LLMRole.FAST。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


_ROUTER_SYSTEM_PROMPT = """You are a query complexity classifier. Analyze the user query and respond with EXACTLY one word:

- "simple" — greetings, basic facts, definitions, yes/no questions that can be answered directly without retrieval or reasoning
- "knowledge" — questions about documentation, knowledge base, specific topics that may need retrieval
- "complex" — multi-step reasoning, comparison, analysis, calculation, data queries, or anything needing tool use

Reply with ONLY the classification word, nothing else."""


@dataclass
class L1RouteResult:
    route: str = "v4"                  # "simple" | "knowledge" | "complex" | "v4"
    answer: str | None = None
    difficulty: str = "medium"         # "simple" | "medium" | "complex"
    metadata: dict[str, Any] = field(default_factory=dict)


class TinyRouter:
    """L1 分类 + 简单回答生成路由器。

    使用小型 LLM（ROUTER 角色，1.7B）分类查询，
    然后可选地使用中型 LLM（FAST 角色，8B）生成直接回答。
    """

    def __init__(self) -> None:
        self._gw = None

    @property
    def _gateway(self):
        if self._gw is None:
            from model.model_gateway.gateway import get_model_gateway
            self._gw = get_model_gateway()
        return self._gw

    async def route(
        self,
        query: str,
        history: list | None = None,
        intent_lock: dict | None = None,
    ) -> L1RouteResult:
        if not query or not query.strip():
            return L1RouteResult(route="simple", answer="", difficulty="simple")

        # ── 快速路径：身份查询 → 落入编排器 ──
        identity_patterns = [
            "你是谁", "你叫什么", "你的名字", "你是什么", "who are you",
            "你的能力", "你能做什么", "你可以做什么", "怎么帮我", "你有哪些功能",
        ]
        if any(p in query.strip().lower() for p in identity_patterns):
            return L1RouteResult(
                route="complex",
                answer=None,
                difficulty="simple",
                metadata={"method": "rule", "reason": "identity_query"},
            )

        # ── 快速路径：intent_lock 确定性路由 ──
        if intent_lock:
            task_type = intent_lock.get("task_type", "")
            # 工具依赖型 → 必须走完整管线
            if task_type in ("weather", "time", "data_query", "web_search", "document_qa"):
                return L1RouteResult(
                    route="complex",
                    answer=None,
                    difficulty="medium",
                    metadata={"method": "intent_lock", "reason": f"tool:{task_type}"},
                )
            # 模型直接回答型 → LLM 直接处理
            if task_type in ("translation", "summarization", "general_qa"):
                allowed = intent_lock.get("allowed_capabilities", [])
                if "model.answer" in allowed:
                    return L1RouteResult(
                        route="simple",
                        answer=None,
                        difficulty="simple",
                        metadata={"method": "intent_lock", "reason": f"direct:{task_type}"},
                    )

        # ── 快速路径：明显问候 ──
        greeting_lower = query.strip().lower()
        greeting_patterns = [
            "你好", "您好", "hi", "hello", "hey", "早上好", "晚上好",
            "谢谢", "thank", "再见", "bye",
        ]
        if any(greeting_lower.startswith(p) for p in greeting_patterns) and len(greeting_lower) < 20:
            return L1RouteResult(
                route="simple",
                answer="你好！有什么可以帮助你的吗？",
                difficulty="simple",
                metadata={"method": "rule"},
            )

        # ── 使用 ROUTER LLM 分类 ──
        classification = await self._classify(query, history)

        if classification == "simple":
            answer = await self._generate_simple_answer(query)
            return L1RouteResult(
                route="simple",
                answer=answer,
                difficulty="simple",
                metadata={"method": "router_llm", "generated": bool(answer)},
            )

        if classification == "knowledge":
            return L1RouteResult(
                route="knowledge",
                answer=None,
                difficulty="medium",
                metadata={"method": "router_llm"},
            )

        return L1RouteResult(
            route="complex",
            answer=None,
            difficulty="complex",
            metadata={"method": "router_llm"},
        )

    async def _classify(self, query: str, history: list | None) -> str:
        """使用 ROUTER LLM 分类查询复杂度。"""
        from model.model_gateway.gateway import LLMMessage, LLMRole

        try:
            messages = [LLMMessage(role="system", content=_ROUTER_SYSTEM_PROMPT)]
            if history:
                recent = history[-4:]
                for h in recent:
                    role = "user" if getattr(h, "role", "user") == "user" else "assistant"
                    content = getattr(h, "content", "") or ""
                    if content:
                        messages.append(LLMMessage(role=role, content=str(content)[:500]))
            messages.append(LLMMessage(role="user", content=query[:1000]))

            response = await self._gateway.complete(messages, role=LLMRole.ROUTER)
            classification = (response.content or "").strip().lower()

            for label in ("simple", "knowledge", "complex"):
                if label in classification:
                    return label
            return "complex"
        except Exception:
            return "complex"

    async def _generate_simple_answer(self, query: str) -> str | None:
        """使用 FAST LLM 为简单查询生成直接回答。"""
        from model.model_gateway.gateway import LLMMessage, LLMRole

        try:
            messages = [
                LLMMessage(
                    role="system",
                    content=(
                        "You are a helpful assistant. Answer the user's question "
                        "directly and concisely in Chinese. Keep your answer under "
                        "100 characters."
                    ),
                ),
                LLMMessage(role="user", content=query[:500]),
            ]
            response = await self._gateway.complete(messages, role=LLMRole.FAST)
            answer = (response.content or "").strip()
            if answer:
                return answer
            return None
        except Exception:
            return None
