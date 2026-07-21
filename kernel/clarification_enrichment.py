"""Merge turn enrichment blocks into clarification prompts (Data + generic)."""

from __future__ import annotations

from typing import Any


def enrichment_blocks_from_params(params: dict[str, Any] | None) -> str:
    """Build a short context block for clarification LLM / fallback text."""
    params = params or {}
    parts: list[str] = []

    summary = str(params.get("conversation_summary", "") or "").strip()
    if summary:
        parts.append(f"【对话摘要】\n{summary[:800]}")

    assembled = params.get("assembled_context")
    if isinstance(assembled, dict):
        state_block = str(assembled.get("state_block", "") or "").strip()
        if state_block:
            parts.append(f"【会话状态】\n{state_block[:600]}")
        memory_block = str(assembled.get("memory_block", "") or "").strip()
        if memory_block and not summary:
            parts.append(f"【相关记忆】\n{memory_block[:500]}")

    mtr = params.get("multi_turn_resolution")
    if isinstance(mtr, dict) and mtr.get("applied"):
        orig = str(mtr.get("original_query", "") or "")
        resolved = str(mtr.get("resolved_query", "") or "")
        if orig and resolved and orig != resolved:
            parts.append(f"【多轮解析】用户原话：{orig[:200]}\n展开后：{resolved[:300]}")

    mtc = params.get("multi_turn_constraints")
    if isinstance(mtc, dict) and mtc:
        import json

        parts.append(
            "【多轮约束】\n"
            + json.dumps(mtc, ensure_ascii=False)[:600]
        )

    return "\n\n".join(parts).strip()


def append_enrichment_to_query(query: str, params: dict[str, Any] | None) -> str:
    block = enrichment_blocks_from_params(params)
    if not block:
        return query
    return f"{query}\n\n{block}"