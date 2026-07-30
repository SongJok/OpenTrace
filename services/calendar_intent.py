from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from services.calendar import ensure_timezone

_CHINESE_DIGITS = "零〇一二两三四五六七八九"
_CHINESE_NUMBER = rf"(?:十[{_CHINESE_DIGITS}]?|[{_CHINESE_DIGITS}](?:十[{_CHINESE_DIGITS}]?)?)"
_NUMBER_TOKEN = rf"(?:\d{{1,2}}|{_CHINESE_NUMBER})"


def _time_pattern(prefix: str, *, marker_required: bool) -> str:
    marker = (
        rf"(?:(?::|：)(?P<{prefix}_minute_clock>\d{{1,2}})"
        rf"|点(?:(?P<{prefix}_half>半)|(?P<{prefix}_quarter>一刻)"
        rf"|(?P<{prefix}_minute_point>{_NUMBER_TOKEN})分?)?)"
    )
    if not marker_required:
        marker += "?"
    return (
        rf"(?P<{prefix}_period>上午|下午|晚上|中午|凌晨)?\s*"
        rf"(?P<{prefix}_hour>{_NUMBER_TOKEN}){marker}"
    )


_TIME_RANGE = re.compile(
    _time_pattern("start", marker_required=True)
    + r"\s*(?:-|—|~|～|至|到)\s*"
    + _time_pattern("end", marker_required=False)
)
_SINGLE_TIME = re.compile(_time_pattern("single", marker_required=True))
_CALENDAR_WRITE_MARKERS = (
    "记录下来",
    "记录一下",
    "记下来",
    "记一下",
    "记录到日历",
    "记到日历",
    "添加到日历",
    "新增到日历",
    "加入日历",
    "放到日历",
    "写入日历",
    "创建日历事件",
    "创建日程",
    "新增日程",
    "安排日程",
    "提醒我",
    "createevent",
    "addevent",
    "addtocalendar",
)
_COMPETING_WRITE_PATTERNS = (
    re.compile(
        r"(?:创建|新增|配置|设置|开启|建立)(?:一个|一条)?(?:数据)?"
        r"(?:预警|告警|定时任务|计划任务|cron任务|待办事项?|审批流程|工单)"
    ),
    re.compile(r"(?:创建|新增|配置|设置|开启|建立)(?:一个|一条)?监控(?:规则|任务|告警|预警)"),
)
_DATE_TEXT = re.compile(r"(?:今天|明天|后天|(?:(?:\d{4})[年/-])?\d{1,2}[月/-]\d{1,2}日?)")
_TITLE_REQUEST_SUFFIX = re.compile(
    r"(?:[，,；;]\s*)?"
    r"(?:(?:请|麻烦)?(?:帮我|给我)?)?"
    r"(?:记录下来|记录一下|记下来|记一下|记录到日历|记到日历|添加到日历|"
    r"新增到日历|加入日历|放到日历|写入日历|创建日历事件|创建日程|新增日程|"
    r"安排日程|create\s*event|add\s*event|"
    r"add\s*to\s*calendar)\s*[。.!！]?$",
    re.IGNORECASE,
)


def _hour(period: str, value: int) -> int:
    if value == 12 and period in {"凌晨", "晚上"}:
        return 0
    if period in {"下午", "晚上"} and value < 12:
        return value + 12
    if period == "中午" and value < 11:
        return value + 12
    return value


def _number(value: str) -> int:
    if value.isdigit():
        return int(value)
    digits = {
        "零": 0,
        "〇": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if "十" not in value:
        return digits[value]
    left, right = value.split("十", maxsplit=1)
    tens = digits[left] if left else 1
    ones = digits[right] if right else 0
    return tens * 10 + ones


def _time_parts(
    match: re.Match[str],
    prefix: str,
    *,
    fallback_period: str = "",
) -> tuple[int, int, str]:
    period = str(match.group(f"{prefix}_period") or fallback_period)
    hour = _hour(period, _number(str(match.group(f"{prefix}_hour"))))
    if match.group(f"{prefix}_half"):
        minute = 30
    elif match.group(f"{prefix}_quarter"):
        minute = 15
    else:
        minute_value = match.group(f"{prefix}_minute_clock") or match.group(
            f"{prefix}_minute_point"
        )
        minute = _number(str(minute_value)) if minute_value else 0
    return hour, minute, period


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
    month = int(match.group("month"))
    day = int(match.group("day"))
    explicit_year = match.group("year")
    candidate_years = [int(explicit_year)] if explicit_year else list(range(now.year, now.year + 9))
    for year in candidate_years:
        try:
            candidate = now.replace(year=year, month=month, day=day)
        except ValueError:
            continue
        if explicit_year or candidate.date() >= now.date():
            return candidate
    return None


def _title(query: str, time_match: re.Match[str]) -> str:
    cleaned = query[: time_match.start()] + query[time_match.end() :]
    cleaned = _DATE_TEXT.sub("", cleaned, count=1)
    cleaned = _TITLE_REQUEST_SUFFIX.sub("", cleaned)
    cleaned = re.sub(r"[，,；;]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，,。.!！")
    cleaned = re.sub(r"^(?:请|麻烦|帮我|给我|我)+", "", cleaned)
    cleaned = re.sub(
        r"^(?:上午|下午|晚上|中午|凌晨)?(?:要|准备|计划|打算)?",
        "",
        cleaned,
    )
    cleaned = re.sub(r"^(?:请|麻烦)?提醒我", "", cleaned)
    title = cleaned.strip(" ，,。.!！") or "日程"
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

    normalized = re.sub(r"\s+", "", query or "").lower()
    if not any(marker in normalized for marker in _CALENDAR_WRITE_MARKERS):
        return None
    if any(pattern.search(normalized) for pattern in _COMPETING_WRITE_PATTERNS):
        return None
    timezone_name = ensure_timezone(timezone_name)
    zone = ZoneInfo(timezone_name)
    local_now = (now or datetime.now(zone)).astimezone(zone)
    target = _target_date(query, local_now)
    time_match = _TIME_RANGE.search(query)
    single_time = False
    if time_match is None:
        time_match = _SINGLE_TIME.search(query)
        single_time = time_match is not None
    if target is None or time_match is None:
        return None
    if single_time:
        start_hour, start_minute, start_period = _time_parts(time_match, "single")
        end_hour = end_minute = None
        end_period = ""
    else:
        start_hour, start_minute, start_period = _time_parts(time_match, "start")
        end_hour, end_minute, end_period = _time_parts(
            time_match,
            "end",
            fallback_period=start_period,
        )
    if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
        return None
    if not single_time and not (
        end_hour is not None
        and end_minute is not None
        and 0 <= end_hour <= 23
        and 0 <= end_minute <= 59
    ):
        return None
    start = target.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
    start_raw_hour = _number(str(time_match.group("single_hour" if single_time else "start_hour")))
    if start_period == "晚上" and start_raw_hour == 12:
        start += timedelta(days=1)
    if single_time:
        end = start + timedelta(hours=1)
    else:
        assert end_hour is not None and end_minute is not None
        end = target.replace(hour=end_hour, minute=end_minute, second=0, microsecond=0)
        end_raw_hour = _number(str(time_match.group("end_hour")))
        if end_period == "晚上" and end_raw_hour == 12:
            end += timedelta(days=1)
        elif (
            end <= start
            and start_period in {"下午", "晚上"}
            and end_period in {"凌晨", "上午"}
            and start.hour >= 18
            and end.hour <= 6
        ):
            end += timedelta(days=1)
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
