"""LLM JSON 输出解析器（含修复策略）。"""

from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(text: str, default: Any = None) -> Any:
    """解析 LLM 输出中的 JSON，含常见格式问题的修复策略。"""
    if not text or not text.strip():
        return default

    # 先尝试直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 尝试从 markdown 中提取 JSON 块
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 尝试查找最外层的 { } 或 [ ]
    for pat in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        m = re.search(pat, text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    return default
