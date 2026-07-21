"""Goal-driven DAG mode contract (phase 2)."""

from __future__ import annotations

import pytest


class TestGoalDrivenDag:
    @pytest.mark.asyncio
    async def test_goal_only_graph_when_enabled(self):
        from kernel.goal.goal_driven_planner import try_build_goal_only_execution_graph

        class _Ctx:
            request_id = "r1"
            metadata = {}

        gg = {
            "root_goal_id": "r1",
            "intent_category": "general",
            "goals": [
                {"goal_id": "r1", "parent_id": None, "description": "root"},
                {
                    "goal_id": "r1:sub:1",
                    "parent_id": "r1",
                    "description": "子问题一",
                    "metadata": {"domain": "web_search"},
                },
            ],
        }
        subs = [g for g in gg["goals"] if g.get("parent_id") == "r1"]
        out = await try_build_goal_only_execution_graph(
            "A？B？", _Ctx(), gg, subs, "r1"
        )
        assert out is not None
        _cog, plan, _graph = out
        assert len(plan.subtasks) == 1
        assert plan.subtasks[0].goal_id == "r1:sub:1"
        assert plan.subtasks[0].capability_type == "web.search"