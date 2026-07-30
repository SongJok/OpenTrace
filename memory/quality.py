from __future__ import annotations

import re

_LEGACY_TRANSCRIPT = re.compile(r"^\s*Q\s*[:：].+\n\s*A\s*[:：]", re.I | re.S)
_ASSISTANT_IDENTITY_QUESTION = re.compile(
    r"(?:介绍你自己|你是谁|你是什么|who are you|introduce yourself)", re.I
)
_PLATFORM_IDENTITY_ANSWER = re.compile(
    r"(?:我是\s*OpenTrace|由\s*Cognitive\s*Kernel\s*驱动|"
    r"OpenTrace.{0,40}(?:助手|assistant|kernel))",
    re.I | re.S,
)


def memory_quality_issue(
    content: str,
    *,
    kind: str = "fact",
    memory_key: str | None = None,
    source_response_id: str | None = None,
) -> str | None:
    """识别不应作为用户事实召回的旧版助手输出。"""

    text = str(content or "").strip()
    if not text or kind != "fact":
        return None
    if memory_key or source_response_id or not _LEGACY_TRANSCRIPT.search(text):
        return None
    if _ASSISTANT_IDENTITY_QUESTION.search(text) and _PLATFORM_IDENTITY_ANSWER.search(text):
        return "legacy_assistant_identity_transcript"
    return None
