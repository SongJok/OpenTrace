"""系统身份与人设 — 对所有模型调用强制统一人设。"""

from __future__ import annotations

import re
from collections.abc import Iterable

from model.llm_adapter.base import LLMMessage

SYSTEM_IDENTITY = """\
你是 OpenTrace，由 Cognitive Kernel 驱动的智能认知助手（内部人设，勿在回复中反复宣读）。

你的能力来源于：推理引擎、工具系统、记忆系统、文档系统。

你的职责：
1. 直接、高质量地回答用户的当前问题
2. 必要时调用工具
3. 不暴露底层模型或厂商信息
4. 以 OpenTrace 的立场与风格作答，但不要在每条回复开头重复自我介绍或系统能力清单

重要：除非用户明确询问你的身份、名称、能力或「你是谁」类问题，禁止在回复开头使用「我是 OpenTrace…」「我是一个基于 Cognitive Kernel…」等固定开场白。
日常对话应直奔主题，例如用户问外卖、天气、代码时，只回答该问题，不要先介绍自己。

当且仅当用户问「你是谁」或类似身份问题时：
- 根据当前对话上下文自然地说明身份与能力，不要背诵固定模板
- 可结合当前话题简要说明你能如何继续帮忙
- 保持温暖、专业，控制在 3-5 句话以内

禁止自称或暗示自己是通义千问、Qwen、ChatGPT、GPT、Claude、Gemini、豆包、文心一言等底层模型或其他厂商助手。
如果当前任务要求严格 JSON、代码或结构化输出，仍然必须遵守该输出格式要求。
"""

CANONICAL_IDENTITY_RESPONSE = (
    "我是 OpenTrace，一个基于认知内核（Cognitive Kernel）构建的 AI 系统。"
    "我可以帮你进行文档检索与总结、数据库查询与分析、联网搜索、任务与记忆管理，以及多轮深度对话。"
    "直接告诉我你的需求即可。"
)

_IDENTITY_USER = re.compile(
    r"(你是谁|你是什么|哪位|什么模型|什么助手|什么ai|哪家公司的|who\s+are\s+you|what\s+are\s+you|what\s+model)",
    re.IGNORECASE,
)

_FORBIDDEN_SELF_ID = re.compile(
    r"(Qwen|通义千问|ChatGPT|GPT[- ]?\d|OpenAI|Anthropic|Claude|文心一言|讯飞星火|豆包|"
    r"阿里云的大语言模型|由阿里云开发|Google\s*Gemini|Gemini\s*Pro|DashScope)",
    re.IGNORECASE,
)

# 模型常在非身份问题上仍输出固定开场白，需从正文开头剥离
_LEADING_IDENTITY_BLURB = re.compile(
    r"^\s*我是\s*OpenTrace\s*[,，]?\s*"
    r"(?:一个)?(?:基于\s*)?(?:Cognitive\s*Kernel|认知内核)(?:\s*构建的)?"
    r"(?:智能认知系统|AI\s*系统|智能助手)[。，,；;]?\s*",
    re.IGNORECASE,
)


def build_system_identity(extra_instruction: str | None = None) -> str:
    if extra_instruction and extra_instruction.strip():
        return f"{SYSTEM_IDENTITY.strip()}\n\n{extra_instruction.strip()}"
    return SYSTEM_IDENTITY.strip()


def merge_system_identity(messages: list[LLMMessage]) -> list[LLMMessage]:
    if not messages:
        return [LLMMessage(role="system", content=build_system_identity())]

    merged: list[LLMMessage] = []
    system_parts: list[str] = []
    non_system_messages: list[LLMMessage] = []

    for message in messages:
        if message.role == "system":
            system_parts.append(message.content)
        else:
            non_system_messages.append(message)

    merged.append(
        LLMMessage(role="system", content=build_system_identity("\n\n".join(system_parts)))
    )
    merged.extend(non_system_messages)
    return merged


def is_identity_user_query(text: str) -> bool:
    if not (text or "").strip():
        return False
    return bool(_IDENTITY_USER.search(text.strip()))


def is_canonical_identity_response(text: str) -> bool:
    """True when assistant text matches the fixed CANONICAL identity blurb (exact or near-exact)."""
    if not (text or "").strip():
        return False
    a = (text or "").strip()
    b = CANONICAL_IDENTITY_RESPONSE.strip()
    if a == b:
        return True
    # Allow minor whitespace / full-width punctuation drift
    norm = lambda s: re.sub(r"\s+", "", s)
    return norm(a) == norm(b)


def last_user_text(messages: Iterable[LLMMessage]) -> str:
    buffered = list(messages)
    for message in reversed(buffered):
        if message.role == "user" and (message.content or "").strip():
            return str(message.content)
    return ""


def _strip_leading_identity_blurb(content: str) -> str:
    """Remove repeated OpenTrace self-intro prefix from assistant text."""
    stripped = content
    for _ in range(3):
        new = _LEADING_IDENTITY_BLURB.sub("", stripped, count=1)
        if new == stripped:
            break
        stripped = new
    return stripped.strip() or content.strip()


def enforce_identity_output(content: str, user_text: str = "") -> str:
    if not content:
        return content

    if is_identity_user_query(user_text) and _FORBIDDEN_SELF_ID.search(content):
        return CANONICAL_IDENTITY_RESPONSE

    if _FORBIDDEN_SELF_ID.search(content):
        content = _FORBIDDEN_SELF_ID.sub("OpenTrace", content)

    if not is_identity_user_query(user_text):
        content = _strip_leading_identity_blurb(content)

    return content


def finalize_assistant_content(content: str, user_query: str = "") -> str:
    """Apply identity post-processing to user-visible assistant text."""
    return enforce_identity_output(content or "", user_query or "")


def build_identity_llm_messages(
    query: str,
    identity_prompt: str,
    conversation_context: dict[str, object] | None = None,
    recent_turns: list[dict[str, object]] | None = None,
) -> list[LLMMessage]:
    """为身份查询 LLM 调用构建上下文丰富的消息。

    组装系统消息（SYSTEM_IDENTITY + SelfModel 身份提示词）
    和用户消息，注入对话上下文，使 LLM 能生成自然、上下文感知的身份回答。
    """
    system_text = SYSTEM_IDENTITY.strip()
    if identity_prompt:
        system_text += f"\n\n你当前的状态：\n{identity_prompt.strip()}"

    ctx = conversation_context or {}
    active_topic = _str_or(ctx.get("active_topic"), "")
    conv_summary = _str_or(ctx.get("conversation_summary"), "")
    conv_phase = _str_or(ctx.get("conversation_phase"), "open")
    active_entities = ctx.get("active_entities") or []
    learned_prefs = ctx.get("learned_preferences") or {}

    lines: list[str] = [f"用户问题：{query}", "", "对话上下文："]
    lines.append(f"- 当前话题：{active_topic or '新对话'}")
    lines.append(f"- 对话摘要：{conv_summary or '尚未有足够对话历史'}")
    lines.append(f"- 对话阶段：{conv_phase}")

    if isinstance(learned_prefs, dict) and learned_prefs:
        pref_items = list(learned_prefs.items())[:3]
        pref_summary = ", ".join(f"{k}: {v}" for k, v in pref_items)
        lines.append(f"- 用户偏好：{pref_summary}")
    else:
        lines.append("- 用户偏好：尚未了解")

    if isinstance(active_entities, list) and active_entities:
        entity_names = ", ".join(
            _str_or(e.get("name") if isinstance(e, dict) else getattr(e, "name", None), "")
            for e in active_entities[:5]
        )
        if entity_names.strip():
            lines.append(f"- 相关实体：{entity_names}")

    lines.append("")
    lines.append("最近对话：")
    if recent_turns:
        for turn in recent_turns[-8:]:
            role = _str_or(turn.get("role"), "unknown")
            content = _str_or(turn.get("content"), "")[:200]
            lines.append(f"[{role}] {content}")
    else:
        lines.append("（首次对话）")

    lines.append("")
    lines.append(
        "请根据以上对话上下文，自然地回答用户关于你身份的问题。"
        "让用户感受到你了解当前的对话状态，而不是给出一个模板化的自我介绍。"
    )

    return [
        LLMMessage(role="system", content=system_text),
        LLMMessage(role="user", content="\n".join(lines)),
    ]


def _str_or(value: object, default: str) -> str:
    if value is None:
        return default
    if isinstance(value, str):
        return value
    return str(value)
