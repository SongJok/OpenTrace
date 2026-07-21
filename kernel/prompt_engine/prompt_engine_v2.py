from __future__ import annotations

from dataclasses import dataclass


@dataclass
class PromptBundle:
    system: str
    context: str
    instruction: str

    def compose(self) -> str:
        return f"{self.system}\n\n[CONTEXT]\n{self.context}\n\n[INSTRUCTION]\n{self.instruction}".strip()


class PromptEngineV2:
    def _strategy(self, query: str) -> str:
        q = query.lower()
        if any(k in q for k in ["code", "python", "debug", "实现", "代码"]):
            return "coding"
        if any(k in q for k in ["分析", "统计", "数据", "analysis"]):
            return "analysis"
        return "qa"

    def build(self, query: str, context_text: str, phase: str = "DRAFT") -> PromptBundle:
        strategy = self._strategy(query)
        system = (
            "你是 OpenTrace 认知内核中的高级智能体。"
            "请基于上下文给出可验证、可执行、边界清晰的答案。"
        )
        if strategy == "analysis":
            system += "遇到数据库、表结构、SQL 或数据源问题时，优先使用给定的 schema / 数据源上下文作答，不要臆测。"
            system += "如果上下文里存在 database_context.summary_text，请优先据此回答表名、字段和结构问题。"
        instruction = (
            f"当前策略: {strategy}; 当前阶段: {phase}; "
            "先给结论，再给关键依据；如果信息不足，明确指出缺口。"
        )
        return PromptBundle(system=system, context=context_text, instruction=instruction)
