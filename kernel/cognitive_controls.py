"""确定性认知控制 — 保障运行时边界安全。

将意图锁定、认知预算与相关性校验与模型提示分离；规则偏保守：
简单轮次保持简单，除非用户明确要求更强能力。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any


_CAPABILITY_HELP_RE = re.compile(
    r"(你能做什么|你可以做什么|你会什么|你能干什么|你能帮我.*什么|"
    r"怎么帮我|如何帮我|可以帮我什么|有哪些?功能|你的能力|你有什么用)",
    re.IGNORECASE,
)
_USAGE_HELP_RE = re.compile(r"(怎么用|怎么使用|使用帮助|帮助|help)", re.IGNORECASE)
_GREETING_RE = re.compile(
    r"^(你好|您好|hi|hello|hey|嗨|早上好|晚上好|下午好|好久不见|在吗|在不在)"
    r"[\s!！。.,，]*$",
    re.IGNORECASE,
)
_IDENTITY_RE = re.compile(
    r"(你是谁|你是什么|哪位|什么模型|什么助手|什么ai|哪家公司的|"
    r"who\s+are\s+you|what\s+are\s+you|what\s+model|"
    r"你叫什么|你的名字|你是什么模型|介绍.*自己|介绍一下你)",
    re.IGNORECASE,
)

# 需要在多轮对话中继承的 domain 类型（这些 domain 的追问通常不含显式关键词）
_STICKY_DOMAINS: frozenset[str] = frozenset(
    {"data_query", "document_qa", "web_search", "rag", "web", "data_analysis"}
)

# 追问检测标记词
_FOLLOW_UP_MARKERS = ["那", "具体", "详细", "按", "根据", "那么", "还有", "另外的", "再"]
_FOLLOW_UP_Q_WORDS = ["怎么查", "如何", "怎么样", "呢", "什么意思", "为什么"]

# intent_lock 能力名称 → 实际注册名称的映射
_CAPABILITY_NORMALIZE_MAP: dict[str, str] = {
    "tool.datetime": "get_current_time",
    "tool.weather": "get_weather",
    "chart.generate": "chart_generator",
    "tool.execute": "tool.datetime",
}


def normalize_capability_name(intent_cap: str) -> str:
    """将 intent_lock 能力名称规范化为实际注册名称。"""
    return _CAPABILITY_NORMALIZE_MAP.get(intent_cap, intent_cap)


_STANDALONE_QUESTION_RE = re.compile(
    r"(是什么|什么是|有哪些|有没有|是谁|在哪|多少钱|几个|多少|什么意思)",
)


def _detect_follow_up(normalized_query: str, conversation_phase: str | None) -> bool:
    """判断当前 query 是否为上一轮话题的追问（非显式话题切换）。

    勿将「任意短句」视为追问，否则同会话内新问题会错误继承上一轮 RAG/data 域。
    """
    q = (normalized_query or "").strip()
    if conversation_phase in ("follow_up", "drill_down"):
        return True
    if any(q.startswith(m) for m in _FOLLOW_UP_MARKERS):
        return True
    if len(q) <= 15 and _STANDALONE_QUESTION_RE.search(q):
        return False
    if any(w in q for w in _FOLLOW_UP_Q_WORDS):
        return True
    return False


@dataclass(frozen=True)
class CognitiveBudget:
    max_planning_depth: int = 1
    max_capabilities: int = 1
    max_replans: int = 0
    max_memory_tokens: int = 0
    max_context_expansion: int = 0
    max_reasoning_steps: int = 1
    memory_injection: bool = False
    workspace_context: bool = False
    critic: bool = False


@dataclass(frozen=True)
class IntentLock:
    raw_user_query: str
    normalized_query: str
    protected_intent: str
    task_type: str
    complexity_level: str
    allowed_capabilities: list[str] = field(default_factory=list)
    disallowed_capabilities: list[str] = field(default_factory=list)
    confidence: float = 0.9
    cognitive_budget: CognitiveBudget = field(default_factory=CognitiveBudget)
    relevance_threshold: float = 0.35

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["cognitive_budget"] = asdict(self.cognitive_budget)
        return data


def build_capability_help_answer() -> str:
    return (
        "我可以帮你进行数据查询与分析、文档检索与总结、网页搜索、"
        "时间/天气/计算等工具调用、图片分析和规则/技能任务。"
        "你可以直接告诉我具体需求，也可以用 /rag、/data、/web 指定模式。"
    )


def build_usage_help_answer() -> str:
    return (
        "直接输入你的问题即可。我会先判断它是普通问答、文档检索、数据查询、"
        "联网搜索还是工具调用；需要指定模式时，可以使用 /rag、/data、/web。"
    )


def classify_intent(
    query: str,
    force_mode: str | None = None,
    prior_intent: str | None = None,
    prior_domain: str | None = None,
    conversation_phase: str | None = None,
) -> IntentLock:
    raw = query or ""
    normalized = " ".join(raw.strip().split())
    q = normalized.lower()

    if force_mode:
        caps = _capabilities_for_force_mode(force_mode, normalized)
        # Multi-turn: short follow-ups under same slash mode keep force + allow memory/context
        follow = _detect_follow_up(normalized, conversation_phase)
        prior_matches = prior_intent in (
            force_mode,
            _force_mode_to_task_type_alias(force_mode),
        )
        light_tool = force_mode == "tool" and not (follow and prior_matches)
        budget = CognitiveBudget(
            max_planning_depth=1,
            max_capabilities=1,
            max_replans=0,
            max_memory_tokens=512 if (follow and prior_matches) else 0,
            max_context_expansion=256 if light_tool else (1024 if (follow and prior_matches) else 512),
            max_reasoning_steps=1 if light_tool else 2,
            memory_injection=bool(follow and prior_matches),
            workspace_context=False,
            critic=False,
        )
        task_type = force_mode
        if force_mode == "tool":
            if any(k in q for k in ["天气", "weather", "温度", "下雨", "预报"]):
                task_type = "weather"
            elif any(k in q for k in ["几点", "时间", "time", "日期", "date"]):
                task_type = "time"
        return IntentLock(
            raw_user_query=raw,
            normalized_query=normalized,
            protected_intent=normalized,
            task_type=task_type,
            complexity_level="L1" if light_tool else "L2",
            allowed_capabilities=caps,
            confidence=0.95 if prior_matches and follow else 1.0,
            cognitive_budget=budget,
            relevance_threshold=0.45,
        )

    if not normalized:
        return _simple_lock(raw, normalized, "empty", "", [])
    if _GREETING_RE.match(normalized):
        return _simple_lock(raw, normalized, "greeting", "打招呼", [])
    if _IDENTITY_RE.search(normalized):
        return _simple_lock(raw, normalized, "identity", "询问助手身份", [])
    if _CAPABILITY_HELP_RE.search(normalized):
        return _simple_lock(raw, normalized, "capability_help", "询问助手能力", [])
    if _USAGE_HELP_RE.search(normalized):
        return _simple_lock(raw, normalized, "usage_help", "询问使用方式", [])
    if any(k in q for k in ["翻译", "translate"]):
        return _light_lock(raw, normalized, "translation", ["model.answer"])
    if any(k in q for k in ["总结", "概括", "归纳"]):
        return _light_lock(raw, normalized, "summarization", ["model.answer"])
    if any(k in q for k in ["文档", "知识库", "pdf", "docx", "从文档", "根据文档"]):
        return _rich_lock(raw, normalized, "document_qa", ["rag.retrieve"])
    if any(k in q for k in ["数据库", "数据表", "sql", "查询", "统计", "报表", "订单", "销售"]):
        return _rich_lock(raw, normalized, "data_query", ["data.query"])
    if any(k in q for k in ["最新", "新闻", "实时", "联网", "搜索"]):
        return _rich_lock(raw, normalized, "web_search", ["web.search"])
    if any(k in q for k in ["天气", "weather"]):
        return _light_lock(raw, normalized, "weather", ["tool.weather"])
    if any(k in q for k in ["几点", "时间", "日期", "time", "date"]):
        return _light_lock(raw, normalized, "time", ["tool.datetime"])

    # ── 多轮上下文继承：当前 query 不含显式关键词时，从上一轮继承 sticky domain ──
    if prior_intent and prior_intent in _STICKY_DOMAINS:
        if _detect_follow_up(normalized, conversation_phase):
            if prior_intent == "data_query":
                return _rich_lock(raw, normalized, "data_query", ["data.query"], confidence=0.65)
            if prior_intent == "document_qa":
                return _rich_lock(raw, normalized, "document_qa", ["rag.retrieve"], confidence=0.65)
            if prior_intent == "web_search":
                return _rich_lock(raw, normalized, "web_search", ["web.search"], confidence=0.65)

    return IntentLock(
        raw_user_query=raw,
        normalized_query=normalized,
        protected_intent=normalized,
        task_type="general_qa",
        complexity_level="L1",
        allowed_capabilities=["model.answer"],
        disallowed_capabilities=["rag.retrieve", "memory.retrieve", "web.search", "data.query"],
        confidence=0.72,
        cognitive_budget=CognitiveBudget(
            max_planning_depth=1,
            max_capabilities=1,
            max_replans=0,
            max_memory_tokens=0,
            max_context_expansion=256,
            max_reasoning_steps=2,
            memory_injection=False,
            workspace_context=False,
            critic=False,
        ),
        relevance_threshold=0.35,
    )


def apply_intent_lock_to_context(ctx: Any, lock: IntentLock) -> None:
    ctx.raw_user_query = lock.raw_user_query
    ctx.protected_intent = lock.protected_intent
    ctx.task_type = lock.task_type
    ctx.allowed_capabilities = list(lock.allowed_capabilities)
    ctx.disallowed_capabilities = list(lock.disallowed_capabilities)
    ctx.cognitive_budget = lock.to_dict()["cognitive_budget"]
    ctx.intent_confidence = lock.confidence
    ctx.relevance_threshold = lock.relevance_threshold
    ctx.metadata = ctx.metadata or {}
    ctx.metadata["intent_lock"] = lock.to_dict()


def direct_answer_for_intent(lock: IntentLock) -> str | None:
    if lock.task_type == "capability_help":
        return build_capability_help_answer()
    if lock.task_type == "usage_help":
        return build_usage_help_answer()
    return None


def capability_allowed(capability: str, lock: IntentLock | None) -> bool:
    if not lock:
        return True
    if capability in lock.disallowed_capabilities:
        return False
    if not lock.allowed_capabilities:
        return True
    return capability in lock.allowed_capabilities


def relevance_score(query: str, text: str) -> float:
    q_tokens = set(_tokens(query))
    t_tokens = set(_tokens(text))
    if not q_tokens or not t_tokens:
        return 0.0
    overlap = len(q_tokens & t_tokens) / max(1, len(q_tokens))
    if _CAPABILITY_HELP_RE.search(query or ""):
        help_hits = sum(1 for k in ["数据", "文档", "搜索", "工具", "能力", "功能", "帮你"] if k in text)
        overlap = max(overlap, min(1.0, help_hits / 3.0))
    return round(max(0.0, min(1.0, overlap)), 3)


def passes_relevance_anchor(query: str, text: str, threshold: float = 0.35) -> bool:
    if not (text or "").strip():
        return False
    return relevance_score(query, text) >= threshold


def _simple_lock(
    raw: str,
    normalized: str,
    task_type: str,
    intent: str,
    allowed: list[str],
) -> IntentLock:
    return IntentLock(
        raw_user_query=raw,
        normalized_query=normalized,
        protected_intent=intent or normalized,
        task_type=task_type,
        complexity_level="L0",
        allowed_capabilities=allowed,
        disallowed_capabilities=[
            "rag.retrieve",
            "web.search",
            "data.query",
            "python.execute",
            "chart.generate",
        ],
        confidence=0.96,
        cognitive_budget=CognitiveBudget(),
        relevance_threshold=0.30,
    )


def _light_lock(raw: str, normalized: str, task_type: str, allowed: list[str]) -> IntentLock:
    return IntentLock(
        raw_user_query=raw,
        normalized_query=normalized,
        protected_intent=normalized,
        task_type=task_type,
        complexity_level="L1",
        allowed_capabilities=allowed,
        disallowed_capabilities=["web.search", "data.query", "rag.retrieve"],
        confidence=0.82,
        cognitive_budget=CognitiveBudget(
            max_planning_depth=1,
            max_capabilities=1,
            max_replans=0,
            max_memory_tokens=0,
            max_context_expansion=256,
            max_reasoning_steps=2,
            memory_injection=False,
            workspace_context=False,
            critic=False,
        ),
        relevance_threshold=0.35,
    )


def _rich_lock(raw: str, normalized: str, task_type: str, allowed: list[str], confidence: float = 0.78) -> IntentLock:
    return IntentLock(
        raw_user_query=raw,
        normalized_query=normalized,
        protected_intent=normalized,
        task_type=task_type,
        complexity_level="L2",
        allowed_capabilities=allowed,
        confidence=confidence,
        cognitive_budget=CognitiveBudget(
            max_planning_depth=2,
            max_capabilities=2,
            max_replans=1,
            max_memory_tokens=512,
            max_context_expansion=2048,
            max_reasoning_steps=5,
            memory_injection=False,
            workspace_context=False,
            critic=True,
        ),
        relevance_threshold=0.45,
    )


def _force_mode_to_task_type_alias(force_mode: str) -> str:
    """Map slash modes to sticky prior_intent values used in conversation_state."""
    return {
        "rag": "document_qa",
        "data_query": "data_query",
        "data_analysis": "data_query",
        "web": "web_search",
    }.get(force_mode or "", force_mode or "")


def _capability_for_force_mode(force_mode: str) -> str:
    caps = _capabilities_for_force_mode(force_mode, "")
    return caps[0] if caps else ""


def _capabilities_for_force_mode(force_mode: str, normalized_query: str) -> list[str]:
    fm = force_mode or ""
    if fm == "tool":
        q = (normalized_query or "").lower()
        if any(k in q for k in ["天气", "weather", "温度", "下雨", "预报"]):
            return ["tool.weather"]
        if any(k in q for k in ["几点", "时间", "time", "日期", "date"]):
            return ["tool.datetime"]
        return ["tool.weather", "tool.datetime"]
    single = {
        "rag": "rag.retrieve",
        "data_query": "data.query",
        "data_analysis": "data.analysis",
        "web": "web.search",
        "vision": "vision.analyze",
        "skills": "skills.execute",
        "anomaly_tracking": "skills.execute",
        "rule_engine": "skills.execute",
        "product": "skills.execute",
    }.get(fm, "")
    return [single] if single else []


def _tokens(text: str) -> list[str]:
    raw = (text or "").lower()
    words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", raw)
    chars = re.findall(r"[\u4e00-\u9fff]", raw)
    bigrams = ["".join(chars[i : i + 2]) for i in range(max(0, len(chars) - 1))]
    return words + bigrams
