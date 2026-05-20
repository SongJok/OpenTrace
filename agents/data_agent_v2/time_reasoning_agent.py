"""
TimeReasoningAgent — converts fuzzy time expressions to precise time windows.

Uses Knowledge Layer column_semantics to identify time columns, then applies:
1. Config-driven time_macro resolution (from semantic_config)
2. Heuristic regex extraction (absolute ranges, relative days, month offsets)
3. Time column inference
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta

from agents.base import AgentResult, BaseAgent, TaskMessage
from agents.data_agent_v2.types import (
    pack_cognitive_result,
    unpack_cognitive_context,
)


class TimeReasoningAgent(BaseAgent):
    """Resolve time expressions into concrete time windows with column hints."""

    # Pre-compiled patterns for time extraction
    _RELATIVE_DAYS = re.compile(r"最近\s*(\d+)\s*天")
    _RELATIVE_MONTHS = re.compile(r"最近\s*(\d+)\s*(个)?月")
    _RELATIVE_HOURS = re.compile(r"最近\s*(\d+)\s*(个)?(小时|钟头)")
    _ABSOLUTE_RANGE = re.compile(
        r"(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)\s*[到至~\-]\s*(\d{4}[-/年]\d{1,2}[-/月]\d{1,2}[日号]?)"
    )
    _YESTERDAY = re.compile(r"昨天|昨日")
    _TODAY = re.compile(r"今天|今日|当天")
    _THIS_WEEK = re.compile(r"本周|这周|这个星期")
    _THIS_MONTH = re.compile(r"本月|这个月")
    _LAST_MONTH = re.compile(r"上个月|上月")
    _LAST_WEEK = re.compile(r"上周|上个星期")
    _PAST_YEAR = re.compile(r"过去一年|最近一年|近一年")
    _MOM = re.compile(r"环比|上月同期")
    _YOY = re.compile(r"同比|去年同期|上年同期")

    def __init__(self) -> None:
        super().__init__("data_time")

    async def execute(self, task: TaskMessage) -> AgentResult:
        ctx = unpack_cognitive_context(task.params)

        try:
            time_window = await self._resolve_time(ctx)
            ctx.time_window = time_window

            return pack_cognitive_result(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content=f"time window: {time_window.get('description', 'none')}",
                confidence=time_window.get("confidence", 0.5),
                ctx=ctx,
                evidence=[self._make_evidence(
                    source="time_resolver",
                    source_type="data_cognition",
                    payload=time_window,
                    credibility=0.88,
                    relevance=0.9,
                )],
            )
        except Exception as exc:
            ctx.time_window = {"type": "none", "confidence": 0.0}
            return AgentResult(
                task_id=task.task_id,
                agent_type=self.agent_type,
                status="success",
                content="time resolution failed",
                confidence=0.0,
                metadata={"cognitive_context": ctx.to_dict()},
                error=str(exc),
            )

    async def _resolve_time(self, ctx: CognitiveContext) -> dict:
        query = ctx.query

        # Priority 1: Config-driven time macros
        result = self._resolve_time_macros(query, ctx)
        if result:
            return result

        # Priority 2: Heuristic regex extraction
        result = self._extract_heuristic(query)
        if result:
            # Augment with column hint from schema_metadata
            col_hint = self._infer_time_column(ctx)
            if col_hint:
                result["column_hint"] = col_hint
            return result

        # No time intent detected
        return {
            "type": "none",
            "description": "no time constraint",
            "confidence": 0.9,
        }

    def _resolve_time_macros(self, query: str, ctx: CognitiveContext) -> dict | None:
        """Check semantic_config.time_macros for matching patterns."""
        macros = ctx.semantic_config.get("time_macros", [])
        best: dict | None = None
        best_len = 0

        for macro in macros:
            pattern = macro.get("pattern", "")
            if pattern and pattern in query:
                if len(pattern) > best_len:
                    best_len = len(pattern)
                    days = macro.get("days", 0)
                    end = datetime.now()
                    start = end - timedelta(days=days)
                    best = {
                        "type": "relative",
                        "days": days,
                        "start": start.strftime("%Y-%m-%d"),
                        "end": end.strftime("%Y-%m-%d"),
                        "column_hint": macro.get("column", ""),
                        "operator": macro.get("operator", ">="),
                        "description": f"config macro: {pattern}",
                        "confidence": 0.95,
                    }
        return best

    def _extract_heuristic(self, query: str) -> dict | None:
        """Regex-based time extraction."""
        now = datetime.now()

        # Relative days
        if m := self._RELATIVE_DAYS.search(query):
            days = int(m.group(1))
            start = now - timedelta(days=days)
            return {
                "type": "relative_days",
                "days": days,
                "start": start.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
                "description": f"last {days} days",
                "confidence": 0.90,
            }

        # Relative months
        if m := self._RELATIVE_MONTHS.search(query):
            months = int(m.group(1))
            start = now - timedelta(days=months * 30)
            return {
                "type": "relative_months",
                "months": months,
                "days": months * 30,
                "start": start.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
                "description": f"last {months} months",
                "confidence": 0.88,
            }

        # Relative hours
        if m := self._RELATIVE_HOURS.search(query):
            hours = int(m.group(1))
            start = now - timedelta(hours=hours)
            return {
                "type": "relative_hours",
                "hours": hours,
                "start": start.strftime("%Y-%m-%d %H:%M:%S"),
                "end": now.strftime("%Y-%m-%d %H:%M:%S"),
                "description": f"last {hours} hours",
                "confidence": 0.90,
            }

        # Absolute date range
        if m := self._ABSOLUTE_RANGE.search(query):
            return {
                "type": "absolute_range",
                "start": self._normalize_date(m.group(1)),
                "end": self._normalize_date(m.group(2)),
                "description": f"{m.group(1)} to {m.group(2)}",
                "confidence": 0.92,
            }

        # Yesterday
        if self._YESTERDAY.search(query):
            d = now - timedelta(days=1)
            return {
                "type": "absolute",
                "start": d.strftime("%Y-%m-%d"),
                "end": d.strftime("%Y-%m-%d"),
                "description": "yesterday",
                "confidence": 0.95,
            }

        # Today
        if self._TODAY.search(query):
            return {
                "type": "absolute",
                "start": now.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
                "description": "today",
                "confidence": 0.95,
            }

        # This week
        if self._THIS_WEEK.search(query):
            start = now - timedelta(days=now.weekday())
            return {
                "type": "relative_days",
                "days": 7,
                "start": start.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
                "description": "this week",
                "confidence": 0.88,
            }

        # This month
        if self._THIS_MONTH.search(query):
            start = now.replace(day=1)
            return {
                "type": "relative_days",
                "days": now.day,
                "start": start.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
                "description": "this month",
                "confidence": 0.88,
            }

        # Last week
        if self._LAST_WEEK.search(query):
            end = now - timedelta(days=now.weekday() + 1)
            start = end - timedelta(days=6)
            return {
                "type": "absolute_range",
                "start": start.strftime("%Y-%m-%d"),
                "end": end.strftime("%Y-%m-%d"),
                "description": "last week",
                "confidence": 0.88,
            }

        # Last month
        if self._LAST_MONTH.search(query):
            end = now.replace(day=1) - timedelta(days=1)
            start = end.replace(day=1)
            return {
                "type": "absolute_range",
                "start": start.strftime("%Y-%m-%d"),
                "end": end.strftime("%Y-%m-%d"),
                "description": "last month",
                "confidence": 0.88,
            }

        # Past year
        if self._PAST_YEAR.search(query):
            start = now - timedelta(days=365)
            return {
                "type": "relative_days",
                "days": 365,
                "start": start.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
                "description": "past year",
                "confidence": 0.90,
            }

        # MoM comparison
        if self._MOM.search(query):
            return {
                "type": "comparison",
                "comparison": "mom",
                "current_start": now.replace(day=1).strftime("%Y-%m-%d"),
                "current_end": now.strftime("%Y-%m-%d"),
                "previous_start": (now.replace(day=1) - timedelta(days=30)).replace(day=1).strftime("%Y-%m-%d"),
                "description": "month over month",
                "confidence": 0.85,
            }

        # YoY comparison
        if self._YOY.search(query):
            return {
                "type": "comparison",
                "comparison": "yoy",
                "current_start": now.replace(day=1).strftime("%Y-%m-%d"),
                "current_end": now.strftime("%Y-%m-%d"),
                "previous_start": now.replace(year=now.year - 1, day=1).strftime("%Y-%m-%d"),
                "previous_end": now.replace(year=now.year - 1).strftime("%Y-%m-%d"),
                "description": "year over year",
                "confidence": 0.85,
            }

        return None

    def _infer_time_column(self, ctx: CognitiveContext) -> str | None:
        """Find columns marked as time_column in schema_metadata."""
        if ctx.column_semantics:
            for col in ctx.column_semantics:
                if col.get("is_time_column"):
                    return f"{col['table_name']}.{col['column_name']}"

        # Heuristic: check query for time-related column mentions
        time_patterns = [
            r"(?:created_at|create_time|下单时间|创建时间|updated_at|update_time|order_time|订单时间)",
        ]
        for pat in time_patterns:
            m = re.search(pat, ctx.query, re.IGNORECASE)
            if m:
                return m.group(0)
        return None

    def _normalize_date(self, s: str) -> str:
        """Normalize Chinese date formats to YYYY-MM-DD."""
        s = re.sub(r"[年月]", "-", s)
        s = re.sub(r"[日号]", "", s)
        # Ensure YYYY-MM-DD format
        parts = s.split("-")
        if len(parts) == 3:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        return s
