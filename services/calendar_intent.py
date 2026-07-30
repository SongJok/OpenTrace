from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from services.calendar import ensure_timezone

_TIME_RANGE = re.compile(
    r"(?P<start_period>上午|下午|晚上|中午|凌晨)?\s*"
    r"(?P<start_hour>\d{1,2})(?:(?::|：)(?P<start_minute>\d{1,2})|点(?P<start_minute_cn>\d{1,2})?分?)"
    r"\s*(?:-|—|~|～|至|到)\s*"
    r"(?P<end_period>上午|下午|晚上|中午|凌晨)?\s*"
    r"(?P<end_hour>\d{1,2})(?:(?::|：)(?P<end_minute>\d{1,2})|点(?P<end_minute_cn>\d{1,2})?分?)?"
)


def _hour(period: str, value: int) -> int:
    if period in {"下午", "晚上"} and value < 12:
        return value + 12
    if period == "中午" and value < 11:
        return value + 12
    return value


def _target_date(query: str, now: datetime) -> datetime | None:
    if "后天" in query:
        return now + timedelta(days=2)
    if "明天" in query:
        return now + timedelta(days=1)
    if "今天" in query:
        return now
    match = re.search(
        r"(?:(?P<year>\d{4})[年/-])?(?P<month>\d{1,2})[月/-](?P<day>\d{1,2})日?", query
    )
    if not match:
        return None
    year = int(match.group("year") or now.year)
    try:
        return now.replace(
            year=year,
            month=int(match.group("month")),
            day=int(match.group("day")),
        )
    except ValueError:
        return None


def _title(query: str, time_match: re.Match[str]) -> str:
    first_clause = re.split(r"[，,；;]", query, maxsplit=1)[0]
    first_clause = _TIME_RANGE.sub("", first_clause)
    first_clause = re.sub(
        r"^(?:我)?(?:今天|明天|后天|(?:(?:\d{4})[年/-])?\d{1,2}[月/-]\d{1,2}日?)?"
        r"(?:上午|下午|晚上|中午|凌晨)?(?:要|准备|计划|打算)?",
        "",
        first_clause,
    )
    first_clause = re.sub(r"(?:帮我|请|麻烦)?(?:记录|添加|安排|提醒).*$", "", first_clause)
    title = first_clause.strip(" ，,。.!！") or "日程"
    title = re.sub(r"(?i)opentrace", "OpenTrace", title)
    title = re.sub(r"([\u4e00-\u9fff])OpenTrace", r"\1 OpenTrace", title)
    return title[:255]


def parse_calendar_create_intent(
    query: str,
    *,
    timezone_name: str,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """把明确的单次日历写入转换为 typed-tool 参数；模糊输入返回 None。"""

    timezone_name = ensure_timezone(timezone_name)
    zone = ZoneInfo(timezone_name)
    local_now = (now or datetime.now(zone)).astimezone(zone)
    target = _target_date(query, local_now)
    time_match = _TIME_RANGE.search(query)
    if target is None or time_match is None:
        return None
    start_period = str(time_match.group("start_period") or "")
    end_period = str(time_match.group("end_period") or start_period)
    start_hour = _hour(start_period, int(time_match.group("start_hour")))
    end_hour = _hour(end_period, int(time_match.group("end_hour")))
    start_minute = int(time_match.group("start_minute") or time_match.group("start_minute_cn") or 0)
    end_minute = int(time_match.group("end_minute") or time_match.group("end_minute_cn") or 0)
    if not (0 <= start_hour <= 23 and 0 <= end_hour <= 23):
        return None
    if not (0 <= start_minute <= 59 and 0 <= end_minute <= 59):
        return None
    start = target.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    end = target.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
    if end <= start:
        return None
    title = _title(query, time_match)
    event_type = (
        "focus" if re.search(r"(?:开发|学习|写作|专注|编码|code)", title, re.I) else "event"
    )
    return {
        "title": title,
        "start_at": start.isoformat(),
        "end_at": end.isoformat(),
        "timezone": timezone_name,
        "description": title,
        "location": "",
        "event_type": event_type,
        "all_day": False,
        "recurrence_rule": "",
        "reminder_minutes": [15],
    }
