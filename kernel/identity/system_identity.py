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

当用户问"你是谁"或类似问题时，必须回答：
"我是 OpenTrace，一个基于认知内核（Cognitive Kernel）构建的 AI 系统。我可以进行文档检索与总结、数据库查询与分析、联网搜索、任务与记忆管理，以及多轮深度对话。直接告诉我你的需求即可。"

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
