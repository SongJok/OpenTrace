"""System identity and persona enforcement for all model calls."""

from __future__ import annotations

import re
from collections.abc import Iterable

from model.llm_adapter.base import LLMMessage

SYSTEM_IDENTITY = """\
你是 OpenTrace，一个基于 Cognitive Kernel 构建的智能认知系统。

你的能力来源于：
- 推理引擎（Reasoning Engine）
- 工具系统（Tool System）
- 记忆系统（Memory System）
- 文档系统（Document System）

你的职责：
1. 提供高质量、可解释的回答
2. 必要时调用工具
3. 不暴露底层模型信息
4. 始终以 OpenTrace 身份回答

当用户问"你是谁"或类似问题时，应根据当前对话上下文自然地表达你的身份和能力，不要背诵固定的介绍文本。在回答时：
- 先说清楚你是 OpenTrace（基于 Cognitive Kernel 构建的 AI 系统）
- 根据当前对话主题，自然地提及你正在为用户提供的帮助
- 如果用户之前讨论过某个话题，可以在回答中自然地引用（例如"我们之前在讨论..."）
- 简要说明你能做什么，但不要机械列举——自然地引出你如何帮助用户的具体需求
- 保持温暖、专业的语调，回答控制在 3-5 句话以内

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


def last_user_text(messages: Iterable[LLMMessage]) -> str:
    buffered = list(messages)
    for message in reversed(buffered):
        if message.role == "user" and (message.content or "").strip():
            return str(message.content)
    return ""


def enforce_identity_output(content: str, user_text: str = "") -> str:
    if not content:
        return content

    if is_identity_user_query(user_text) and _FORBIDDEN_SELF_ID.search(content):
        return CANONICAL_IDENTITY_RESPONSE

    if _FORBIDDEN_SELF_ID.search(content):
        content = _FORBIDDEN_SELF_ID.sub("OpenTrace", content)
    return content


def build_identity_llm_messages(
    query: str,
    identity_prompt: str,
    conversation_context: dict[str, object] | None = None,
    recent_turns: list[dict[str, object]] | None = None,
) -> list[LLMMessage]:
    """Build context-rich messages for an identity query LLM call.

    Assembles a system message (SYSTEM_IDENTITY + SelfModel identity prompt)
    and a user message that injects conversation context so the LLM can
    produce a natural, context-aware identity response.
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
