"""LLM JSON output parser with repair strategies."""

from __future__ import annotations

import json
import re
from typing import Any


def parse_llm_json(text: str, default: Any = None) -> Any:
    """Parse JSON from LLM output, with repair for common formatting issues."""
    if not text or not text.strip():
        return default

    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try extracting JSON block from markdown
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # Try finding the outermost { } or [ ]
    for pat in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        m = re.search(pat, text)
        if m:
            try:
                return json.loads(m.group(0))
            except json.JSONDecodeError:
                pass

    return default
