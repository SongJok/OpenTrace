"""多问分解（认知域 — 不执行）。"""

from __future__ import annotations

import re
from typing import Any

from kernel.json_parser import parse_llm_json

_MULTI_Q_HINTS = [
    "第一个",
    "第二个",
    "第三个",
    "第一",
    "第二",
    "第三",
    "并告诉我",
    "同时告诉我",
    "另外",
    "此外",
    "还有",
    "再分析",
    "再查询",
    "再告诉我",
]

_DOMAIN_DATA_KW = [
    "查询",
    "统计",
    "报表",
    "销量",
    "订单",
    "数据库",
    "sql",
    "表",
    "字段",
]
_DOMAIN_RAG_KW = ["文档", "手册", "知识库", "总结", "pdf", "doc"]
_DOMAIN_WEB_KW = ["最新", "新闻", "今天", "实时", "联网", "搜索", "weather"]
_DOMAIN_TOOL_KW = ["时间", "几点", "天气", "计算"]
_FACTUAL_Q_PATTERNS = ["首都", "哪里", "是谁", "多少", "什么"]


def is_multi_question(query: str) -> bool:
    q = (query or "").strip()
    if q.count("？") + q.count("?") >= 2:
        return True
    if len(q) < 15:
        return False
    if any(h in q for h in _MULTI_Q_HINTS):
        return True
    # IntentEngine.parse is async — use lightweight heuristics only (no await here).
    q_lower = q.lower()
    if any(
        w in q_lower
        for w in [
            "然后",
            "接着",
            "之后",
            "首先",
            "其次",
            "最后",
            "then",
            "after that",
            "first",
            "next",
            "finally",
        ]
    ):
        return True
    return False


def classify_sub_question_domain(text: str) -> str:
    t = (text or "").lower()
    scores = {
        "data_query": sum(1 for k in _DOMAIN_DATA_KW if k in t),
        "document_retrieval": sum(1 for k in _DOMAIN_RAG_KW if k in t),
        "web_search": sum(1 for k in _DOMAIN_WEB_KW if k in t),
        "tool_execution": sum(1 for k in _DOMAIN_TOOL_KW if k in t),
    }
    if any(p in t for p in _FACTUAL_Q_PATTERNS) and scores["document_retrieval"] == 0:
        scores["web_search"] = max(scores["web_search"], 2)
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "general_qa"


def split_by_syntax(query: str) -> list[str] | None:
    q = (query or "").strip()
    qm_parts = re.split(r"[？?]\s*", q)
    qm_parts = [s.strip() for s in qm_parts if s.strip() and len(s.strip()) > 2]
    if len(qm_parts) >= 2:
        return qm_parts
    if "；" in q:
        parts = [s.strip() for s in q.split("；") if s.strip() and len(s.strip()) > 5]
        if len(parts) >= 2:
            return parts
    logical_split = re.split(r"[，,]\s*(?:并|同时|另外|此外|还有)\s*", q)
    logical_split = [s.strip() for s in logical_split if s.strip() and len(s.strip()) > 8]
    if len(logical_split) >= 2:
        return logical_split
    return None


async def split_by_llm(query: str) -> list[dict[str, str]] | None:
    from model.llm_adapter.base import LLMMessage
    from model.model_gateway.gateway import LLMRole, get_model_gateway

    prompt = (
        "将复合问题拆分为独立子问题 JSON："
        '{"questions": [{"id": "q1", "text": "...", "domain": "data_query|document_retrieval|web_search|tool_execution|general_qa"}]}'
        f"\n用户：{query}"
    )
    try:
        resp = await get_model_gateway().complete(
            [LLMMessage(role="user", content=prompt)],
            role=LLMRole.PLANNING,
            temperature=0.0,
            max_tokens=400,
        )
        parsed = parse_llm_json((resp.content or "").strip())
        if not parsed or not isinstance(parsed, dict):
            return None
        questions = parsed.get("questions", [])
        if not isinstance(questions, list) or len(questions) < 2:
            return None
        out: list[dict[str, str]] = []
        for i, q_data in enumerate(questions):
            if not isinstance(q_data, dict):
                continue
            text_val = str(q_data.get("text", ""))
            if not text_val.strip():
                continue
            dom = str(q_data.get("domain", "general_qa"))
            heur = classify_sub_question_domain(text_val)
            out.append(
                {
                    "id": str(q_data.get("id", f"q{i+1}")),
                    "text": text_val,
                    "domain": heur if heur != "general_qa" else dom,
                }
            )
        return out if len(out) >= 2 else None
    except Exception:
        return None


async def decompose_query(query: str) -> list[dict[str, str]] | None:
    parts = split_by_syntax(query)
    if parts and len(parts) >= 2:
        return [
            {"id": f"q{i+1}", "text": t, "domain": classify_sub_question_domain(t)}
            for i, t in enumerate(parts)
        ]
    return await split_by_llm(query)