"""Turn-level preference injection — conversation_state + UserMemory → metadata."""

from __future__ import annotations

from typing import Any

from infra.observability.logger import get_logger
from kernel.preference_layers import (
    LayeredMemory,
    PreferenceLayer,
    build_layered_context_block,
    classify_memories,
)

logger = get_logger(__name__)


def _prefs_from_conversation_state(conversation_state: Any) -> list[LayeredMemory]:
    if conversation_state is None:
        return []
    learned = getattr(conversation_state, "learned_preferences", None) or {}
    out: list[LayeredMemory] = []
    if isinstance(learned, dict):
        for key, val in learned.items():
            if val is None or val == "":
                continue
            out.append(
                LayeredMemory(
                    content=f"{key}: {val}",
                    layer=PreferenceLayer.BEHAVIORAL,
                    tags=["learned_preferences"],
                )
            )
    elif isinstance(learned, list):
        for item in learned:
            if isinstance(item, str) and item.strip():
                out.append(
                    LayeredMemory(
                        content=item.strip(),
                        layer=PreferenceLayer.BEHAVIORAL,
                        tags=["learned_preferences"],
                    )
                )
    return out


async def _load_user_memory_preferences(user_id: str, session_id: str) -> list[LayeredMemory]:
    if not user_id or user_id == "shared":
        return []
    try:
        from sqlalchemy import select

        from infra.storage.database import AsyncSessionLocal
        from infra.storage.models import UserMemory

        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(UserMemory).where(UserMemory.user_id == user_id).limit(40)
            )
            rows = list(result.scalars().all())
        return classify_memories(rows, session_id=session_id)
    except Exception as exc:
        logger.debug("preference_user_memory_skipped", error=str(exc))
        return []


def merge_learned_preference(
    conversation_state: Any,
    key: str,
    value: Any,
) -> None:
    """Merge a single preference key into conversation_state.learned_preferences."""
    if conversation_state is None or not key:
        return
    lp = getattr(conversation_state, "learned_preferences", None)
    if not isinstance(lp, dict):
        lp = {}
    lp[str(key)[:80]] = value
    conversation_state.learned_preferences = lp


async def apply_preference_injection_for_turn(
    *,
    user_id: str,
    session_id: str,
    metadata: dict[str, Any],
    conversation_state: Any = None,
) -> dict[str, Any]:
    """Populate metadata fields consumed by memory_injection and Executive prompts."""
    md = dict(metadata or {})
    layered: list[LayeredMemory] = []
    layered.extend(_prefs_from_conversation_state(conversation_state))
    layered.extend(await _load_user_memory_preferences(user_id, session_id))

    custom = str(md.get("custom_instruction_block") or "").strip()

    if not layered:
        if custom:
            md["user_preference_context_block"] = f"## 用户明确指令\n{custom[:8000]}"
        return md

    block = build_layered_context_block(layered)
    md["user_preference_context_block"] = (
        f"## 用户明确指令\n{custom[:8000]}\n\n## 用户偏好\n{block}"
        if custom
        else block
    )
    md["user_preferences"] = [lm.content for lm in layered[:24]]
    md["preference_layers"] = [
        {"layer": lm.layer.value, "content": lm.content, "tags": list(lm.tags)}
        for lm in layered[:24]
    ]
    return md
