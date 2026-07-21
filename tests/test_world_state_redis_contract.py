"""World state Redis facade."""

from __future__ import annotations

import pytest

from kernel.cognition.runtime_grounding import RuntimeGroundingState, get_grounding
from world.world_state_redis import merge_snapshot, save_session_world_state


@pytest.mark.asyncio
async def test_save_noop_when_disabled():
    await save_session_world_state("s-redis", get_grounding("s-redis"))


def test_merge_snapshot_restores_goal():
    merge_snapshot(
        "s-merge",
        {"goal": {"root_goal_id": "g99", "version": 3, "active_states": {"g99": "active"}}},
    )
    st = get_grounding("s-merge")
    assert st.goal.root_goal_id == "g99"
    assert st.goal.version == 3