"""Redis world state facade — delegates to kernel runtime_grounding."""

from __future__ import annotations

from typing import Any

from kernel.cognition.runtime_grounding import (
    RuntimeGroundingState,
    get_grounding,
    hydrate_world_state_for_session,
    load_persisted_world_state,
    merge_persisted_into_grounding,
    persist_world_state,
)


async def save_session_world_state(session_id: str, state: RuntimeGroundingState | None = None) -> None:
    st = state or get_grounding(session_id)
    await persist_world_state(session_id, st)


async def load_session_world_state(session_id: str) -> dict[str, Any] | None:
    return await load_persisted_world_state(session_id)


async def hydrate_session(session_id: str) -> dict[str, Any] | None:
    return await hydrate_world_state_for_session(session_id)


def merge_snapshot(session_id: str, snapshot: dict[str, Any]) -> None:
    merge_persisted_into_grounding(session_id, snapshot)