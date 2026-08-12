from __future__ import annotations

import re
from typing import Any


def is_affirmative_follow_up(query: str) -> bool:
    normalized = re.sub(r"[\s，。！？,.!?]", "", (query or "").lower())
    if not normalized or len(normalized) > 24:
        return False
    markers = (
        "确认",
        "确认创建",
        "继续",
        "执行",
        "可以",
        "好的",
        "好",
        "同意",
        "批准",
        "是的",
        "就这样",
        "按这个",
        "创建吧",
        "confirm",
        "continue",
        "proceed",
        "approve",
        "yes",
    )
    return any(normalized == marker or normalized.startswith(marker) for marker in markers)


def is_contextual_follow_up(query: str) -> bool:
    if is_affirmative_follow_up(query):
        return True
    normalized = re.sub(r"\s+", "", query or "")
    return len(normalized) <= 24 and any(
        marker in normalized
        for marker in (
            "这个",
            "那个",
            "刚才",
            "上一个",
            "上一条",
            "上一轮",
            "照此",
            "按上述",
            "继续说",
            "接着说",
            "再详细",
            "具体怎么",
            "然后呢",
            "那怎么",
        )
    )


def is_sql_draft_execution_request(query: str) -> bool:
    """识别用户对已展示 SQL 草案或候选的明确执行选择。"""

    normalized = re.sub(r"[\s，。！？,.!?]", "", (query or "").lower())
    if normalized in {
        "确认",
        "确认执行",
        "继续",
        "执行",
        "可以",
        "好的",
        "好",
        "同意",
        "批准",
        "是的",
        "就这样",
        "按这个",
        "confirm",
        "continue",
        "proceed",
        "approve",
        "yes",
    }:
        return True
    targets = (
        "sql草案",
        "sql候选",
        "候选",
        "方案",
        "第一个",
        "第二个",
        "第三个",
        "第一条",
        "第二条",
        "第三条",
        "全部",
        "所有",
        "candidate",
        "draft",
    )
    actions = (
        "执行",
        "运行",
        "采用",
        "选择",
        "使用",
        "用第",
        "按第",
        "重试",
        "确认",
        "execute",
        "run",
        "retry",
        "select",
        "use",
    )
    return any(target in normalized for target in targets) and any(
        action in normalized for action in actions
    )


def is_explicit_write_request(
    query: str,
    *,
    pending_action: dict[str, Any] | None = None,
) -> bool:
    if pending_action and is_affirmative_follow_up(query):
        return True
    if is_sql_draft_execution_request(query):
        return True
    normalized = re.sub(r"\s+", "", query or "")
    direct_markers = (
        "记录下来",
        "记录一下",
        "记一下",
        "添加到日历",
        "新增到日历",
        "加入日历",
        "创建日历事件",
        "创建日程",
        "预定日历",
        "预订日历",
        "预约日历",
        "预定日程",
        "预订日程",
        "预约日程",
        "创建任务",
        "创建预警",
        "执行sql草案",
        "执行sql候选",
        "执行候选",
        "执行全部候选",
        "运行sql草案",
        "运行sql候选",
        "运行候选",
        "选择候选",
        "采用候选",
        "重试候选",
        "确认执行候选",
        "提醒我",
        "取消日程",
        "删除日程",
        "修改日程",
        "更新日程",
        "改到",
        "reschedule",
        "addtocalendar",
        "createevent",
        "canceltheevent",
    )
    if any(marker in normalized.lower() for marker in direct_markers):
        return True
    return bool(
        re.search(
            r"(?:帮我|请|麻烦|给我).{0,24}"
            r"(?:记录|添加|创建|安排|提醒|预定|预订|预约|取消|删除|修改|更新)",
            normalized,
        )
    )
