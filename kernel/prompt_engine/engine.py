"""
提示词引擎 — 系统与用户提示模板管理。
"""

from __future__ import annotations

from string import Template
from typing import Any

PROMPTS: dict[str, str] = {
    "system_default": (
        "You are OpenTrace, a helpful and precise AI assistant. "
        "Today is $date. Answer concisely and accurately."
    ),
    "rag_context": (
        "Use the following retrieved context to answer the question.\n"
        "Context:\n$context\n\nQuestion: $question"
    ),
    "summarize": ("Summarize the following text concisely, preserving key facts:\n\n$text"),
    "tool_result": ("Tool '$tool_name' returned:\n$result\n\nContinue with the original task."),
}


class PromptEngine:
    """Simple template-based prompt builder."""

    def render(self, template_name: str, **kwargs: Any) -> str:
        tmpl = PROMPTS.get(template_name)
        if tmpl is None:
            raise KeyError(f"Unknown prompt template: {template_name}")
        return Template(tmpl).safe_substitute(kwargs)

    def add_template(self, name: str, template: str) -> None:
        PROMPTS[name] = template

    def list_templates(self) -> list[str]:
        return list(PROMPTS.keys())


prompt_engine = PromptEngine()
