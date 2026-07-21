"""结果引用构建桩 — 从 Agent 结果构建 ResultRefs。"""

from __future__ import annotations

from typing import Any


class ResultRefBuilder:

    @staticmethod
    def build_from_agent_result(
        result: Any, query: str = ""
    ) -> list[dict[str, Any]]:
        return []

    @staticmethod
    def build_from_task_results(
        results: dict[str, Any], subtasks: list
    ) -> list[dict[str, Any]]:
        return []
