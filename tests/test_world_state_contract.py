"""Runtime world state versioning and artifact lineage."""

from __future__ import annotations

from kernel.cognition.runtime_grounding import (
    attach_world_state_to_context,
    bump_world_state_version,
    get_grounding,
    project_from_context,
)


class _Ctx:
    session_id = "s1"
    request_id = "r1"
    metadata: dict = {}
    allowed_capabilities: list = []
    user_preferences: list = []
    task_type = "general"
    protected_intent = "hello"


class TestWorldState:
    def test_bump_increments_version_and_ids(self):
        state = get_grounding("s-ws")
        bump_world_state_version(state, request_id="r0")
        w1 = state.world_state_id
        bump_world_state_version(state, request_id="r1")
        assert state.parent_world_state_id == w1
        assert state.world_state_id != w1
        assert state.goal.version >= 1

    def test_attach_writes_metadata(self):
        ctx = _Ctx()
        ctx.metadata = {"goal_graph": {"root_goal_id": "g1", "goals": []}}
        state = project_from_context(ctx)
        attach_world_state_to_context(ctx, state)
        assert ctx.metadata.get("world_state_id")
        assert "runtime_grounding" in ctx.metadata

    def test_hydrate_merge_restores_goal_version(self):
        from kernel.cognition.runtime_grounding import merge_persisted_into_grounding

        merge_persisted_into_grounding(
            "s-h",
            {
                "world_state_id": "w-old",
                "turn_index": 3,
                "goal": {"root_goal_id": "g9", "version": 7, "active_states": {"g9": "active"}},
            },
        )
        state = get_grounding("s-h")
        assert state.world_state_id == "w-old"
        assert state.goal.version == 7