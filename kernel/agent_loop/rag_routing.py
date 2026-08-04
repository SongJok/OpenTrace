"""Responses 主链路的确定性 RAG 路由判定。"""

from __future__ import annotations

import re
from dataclasses import dataclass

_RAG_COMMAND_RE = re.compile(
    r"^\s*/(?P<command>rag|kb|knowledge)(?=$|[\s:：])(?:[\s:：]+)?",
    flags=re.IGNORECASE,
)
_EXPLICIT_GROUNDING_MARKERS = (
    "根据知识库",
    "基于知识库",
    "使用知识库",
    "参考知识库",
    "查询知识库",
    "检索知识库",
    "搜索知识库",
    "从知识库",
    "知识库中",
    "知识库证据",
    "已发布知识",
    "根据企业知识库",
    "基于企业知识库",
    "查询企业知识库",
    "检索企业知识库",
    "搜索企业知识库",
    "从企业知识库",
    "企业知识库中",
    "根据公司知识库",
    "基于公司知识库",
    "查询公司知识库",
    "检索公司知识库",
    "根据文档",
    "基于文档",
    "参考文档",
    "查询文档",
    "检索文档",
    "搜索文档",
    "从文档",
    "文档中",
    "上传的文档",
    "我的资料中",
    "我的文档中",
    "basedontheknowledgebase",
    "fromtheknowledgebase",
    "searchtheknowledgebase",
    "basedonthedocument",
    "fromthedocument",
    "searchthedocument",
    "uploadeddocument",
)


@dataclass(frozen=True, slots=True)
class RagRoutingDecision:
    """只表达路由与检索范围，不扩大服务器侧授权边界。"""

    required: bool
    query: str
    reason: str = "auto"
    explicit_command: bool = False
    explicit_grounding: bool = False
    enterprise_grounding: bool = False
    sources: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "required": self.required,
            "reason": self.reason,
            "explicit_command": self.explicit_command,
            "explicit_grounding": self.explicit_grounding,
            "enterprise_grounding": self.enterprise_grounding,
            "sources": list(self.sources),
        }


def strip_rag_command(query: str) -> tuple[str, bool]:
    """移除仅位于消息开头的 RAG slash command，避免污染检索 query。"""

    raw = str(query or "").strip()
    match = _RAG_COMMAND_RE.match(raw)
    if match is None:
        return raw, False
    return raw[match.end() :].strip(), True


def has_explicit_grounding_request(query: str) -> bool:
    """识别“用知识库/文档作答”，但不把“什么是知识库”误判为检索请求。"""

    normalized = re.sub(r"\s+", "", str(query or "").lower())
    return any(marker in normalized for marker in _EXPLICIT_GROUNDING_MARKERS)


def resolve_rag_routing(
    query: str,
    *,
    knowledge_mode: str = "auto",
    enterprise_grounding: bool = False,
) -> RagRoutingDecision:
    """合并 API 显式模式、slash command、语义标志和企业治理标志。"""

    cleaned_query, explicit_command = strip_rag_command(query)
    explicit_grounding = has_explicit_grounding_request(cleaned_query)
    normalized_mode = str(knowledge_mode or "auto").strip().lower()
    mode_required = normalized_mode == "required"
    required = bool(mode_required or explicit_command or explicit_grounding or enterprise_grounding)

    if enterprise_grounding:
        reason = "enterprise_grounding"
        sources = ("knowledge",)
    elif explicit_command:
        reason = "slash_command"
        sources = ("knowledge", "documents")
    elif mode_required:
        reason = "api_required"
        sources = ("knowledge", "documents")
    elif explicit_grounding:
        reason = "explicit_grounding"
        sources = ("knowledge", "documents")
    else:
        reason = "auto"
        sources = ()

    return RagRoutingDecision(
        required=required,
        query=cleaned_query or str(query or "").strip(),
        reason=reason,
        explicit_command=explicit_command,
        explicit_grounding=explicit_grounding,
        enterprise_grounding=enterprise_grounding,
        sources=sources,
    )
