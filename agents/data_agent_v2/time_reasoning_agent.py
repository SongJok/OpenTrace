"""
TimeReasoningAgent — 将模糊时间表达转为精确时间窗口。

借助知识层 column_semantics 识别时间列，再依次：
1. 配置驱动的时间宏解析（semantic_config）
2. 启发式正则抽取（绝对区间、相对天/月）
3. 时间列推断
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
    """将时间表达解析为带列提示的具体时间窗口。"""

    # 预编译的时间抽取正则
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

        # 优先级 1：配置驱动的时间宏
        result = self._resolve_time_macros(query, ctx)
        if result:
            return result

        # 优先级 2：启发式正则抽取
        result = self._extract_heuristic(query)
        if result:
            # 用 schema_metadata 补充列提示
            col_hint = self._infer_time_column(ctx)
            if col_hint:
                result["column_hint"] = col_hint
            return result

        # 未检测到时间意图
        return {
            "type": "none",
            "description": "no time constraint",
            "confidence": 0.9,
        }

    def _resolve_time_macros(self, query: str, ctx: CognitiveContext) -> dict | None:
        """检查 semantic_config.time_macros 中是否有匹配的模式。"""
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
        """基于正则的时间抽取。"""
        now = datetime.now()

        # 相对天数
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

        # 相对月数
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

        # 相对小时
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

        # 绝对日期区间
        if m := self._ABSOLUTE_RANGE.search(query):
            return {
                "type": "absolute_range",
                "start": self._normalize_date(m.group(1)),
                "end": self._normalize_date(m.group(2)),
                "description": f"{m.group(1)} to {m.group(2)}",
                "confidence": 0.92,
            }

        # 昨天
        if self._YESTERDAY.search(query):
            d = now - timedelta(days=1)
            return {
                "type": "absolute",
                "start": d.strftime("%Y-%m-%d"),
                "end": d.strftime("%Y-%m-%d"),
                "description": "yesterday",
                "confidence": 0.95,
            }

        # 今天
        if self._TODAY.search(query):
            return {
                "type": "absolute",
                "start": now.strftime("%Y-%m-%d"),
                "end": now.strftime("%Y-%m-%d"),
                "description": "today",
                "confidence": 0.95,
            }

        # 本周
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

        # 本月
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

        # 上周
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

        # 上月
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

        # 过去一年
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

        # 环比
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

        # 同比
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
        """查找 schema_metadata 中标记为 time_column 的列。"""
        if ctx.column_semantics:
            for col in ctx.column_semantics:
                if col.get("is_time_column"):
                    return f"{col['table_name']}.{col['column_name']}"

        # 启发式：检查查询中是否提及时间相关列
        time_patterns = [
            r"(?:created_at|create_time|下单时间|创建时间|updated_at|update_time|order_time|订单时间)",
        ]
        for pat in time_patterns:
            m = re.search(pat, ctx.query, re.IGNORECASE)
            if m:
                return m.group(0)
        return None

    def _normalize_date(self, s: str) -> str:
        """将中文日期格式标准化为 YYYY-MM-DD。"""
        s = re.sub(r"[年月]", "-", s)
        s = re.sub(r"[日号]", "", s)
        # 确保 YYYY-MM-DD 格式
        parts = s.split("-")
        if len(parts) == 3:
            return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
        return s
