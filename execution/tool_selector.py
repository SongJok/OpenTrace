from __future__ import annotations

from execution.tool_feedback import tool_feedback_store
from execution.tool_ranker import ToolRanker, ToolSignal


class ToolSelector:
    """Top-K tool selector for P1 baseline."""

    def __init__(self) -> None:
        self.ranker = ToolRanker()

    def _candidates(self, query: str, web_enabled: bool = False) -> list[ToolSignal]:
        q = query.lower()
        cands: list[ToolSignal] = []

        def add(name: str, rel: float) -> None:
            succ, lat = tool_feedback_store.snapshot(name)
            cands.append(ToolSignal(name=name, relevance=rel, success_rate=succ, latency_ms=lat))

        if web_enabled or any(k in q for k in ["最新", "新闻", "today", "latest"]):
            add("web_search", 0.92)
        if any(k in q for k in ["图表", "折线图", "柱状图", "可视化"]):
            add("chart_generator", 0.94)
        if any(k in q for k in ["数据", "csv", "pandas", "统计", "dataframe"]):
            add("data_analysis", 0.9)
        if any(k in q for k in ["代码", "python", "debug", "执行代码", "implement"]):
            add("code_interpreter", 0.88)
        if any(k in q for k in ["文件", "sandbox", "读文件", "写文件"]):
            add("file_sandbox", 0.82)

        if not cands:
            add("tool_router", 0.65)
        return cands

    def select(self, query: str, web_enabled: bool = False, top_k: int = 2) -> list[str]:
        ranked = self.ranker.rank(self._candidates(query, web_enabled=web_enabled), top_k=top_k)
        return [x.name for x in ranked]
