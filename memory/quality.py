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
_INTERROGATIVE_MEMORY = re.compile(
    r"(?i)(?:是什么|怎么(?:做|办)?|哪个|哪一个|多少|哪里|为何|为什么|是否|"
    r"(?:吗|呢)[？?]?$|[？?]$)"
)
_TEMPORAL_REFERENCE = re.compile(
    r"(?i)(?:今天|今晚|明天|后天|(?:本|这|下|上)周(?:[一二三四五六日天])?|"
    r"(?:\d{4}\s*年\s*)?\d{1,2}\s*月\s*\d{1,2}\s*[日号]|"
    r"\d{4}-\d{1,2}-\d{1,2}|tomorrow|today|tonight|next\s+(?:week|month)|"
    r"on\s+\d{4}-\d{1,2}-\d{1,2})"
)
_BUSINESS_EVENT = re.compile(
    r"(?i)(?:日历|日程|会议|开会|安排|提醒|预约|截止|到期|提交|拜访|出差|面试|"
    r"任务|待办|发布|评审|复盘|calendar|event|meeting|appointment|deadline|task|todo)"
)
_STABLE_TEMPORAL_PROFILE = re.compile(
    r"(?i)(?:每天|每周|每月|每年|通常|习惯|默认|工作时间|办公时间|可用时间|空闲时间|"
    r"时区|daily|weekly|monthly|yearly|usually|by default|working hours|office hours|timezone)"
)


def temporal_memory_issue(content: str, *, source_text: str | None = None) -> str | None:
    """阻止可变业务实例被复制成脱离事实来源的长期语义记忆。"""

    text = str(content or "").strip()
    if not text or _STABLE_TEMPORAL_PROFILE.search(text):
        return None
    if _TEMPORAL_REFERENCE.search(text) and _BUSINESS_EVENT.search(text):
        return "time_bound_business_event"
    source = str(source_text or "")
    if (
        source
        and _TEMPORAL_REFERENCE.search(source)
        and _BUSINESS_EVENT.search(source)
        and _BUSINESS_EVENT.search(text)
    ):
        return "time_bound_business_event"
    return None


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
    # 疑问句是待回答的输入，不是可跨会话召回的个人事实；隔离旧数据以免阻塞新事实。
    if len(text) <= 160 and _INTERROGATIVE_MEMORY.search(text):
        return "interrogative_fact"
    if memory_key or source_response_id or not _LEGACY_TRANSCRIPT.search(text):
        return None
    if _ASSISTANT_IDENTITY_QUESTION.search(text) and _PLATFORM_IDENTITY_ANSWER.search(text):
        return "legacy_assistant_identity_transcript"
    return None
