"""Multi-goal runtime contract — bindings and planner graph without LLM."""

from __future__ import annotations

import pytest

from kernel.goal.multi_goal_outcomes import build_sub_goal_bindings
from kernel.goal.multi_goal_scheduler import schedule_sub_goals_from_graph
from kernel.protocol.runtime_contract import Goal, GoalGraph
from kernel.runtime.objects import ExecutionBudget, ExecutionNode


class TestSubGoalBindings:
    def test_build_bindings_from_graph(self):
        sub_q = [
            {"id": "q1", "text": "销量?", "goal_id": "g:1"},
            {"id": "q2", "text": "利润?", "goal_id": "g:2"},
        ]
        nodes = [
            ExecutionNode(
                node_id="q1:n1",
                capability_name="data.query",
                params={"sub_question_id": "q1", "goal_id": "g:1"},
                goal_id="g:1",
            ),
            ExecutionNode(
                node_id="q2:n1",
                capability_name="data.query",
                params={"sub_question_id": "q2", "goal_id": "g:2"},
                goal_id="g:2",
            ),
        ]
        bindings = build_sub_goal_bindings(nodes, sub_q)
        assert len(bindings) >= 2
        by_gid = {b["goal_id"]: b for b in bindings}
        assert "q1:n1" in by_gid["g:1"]["node_ids"]

    def test_scheduler_attaches_goal_id(self):
        graph = GoalGraph(
            root_goal_id="root",
            goals=[
                Goal(goal_id="root", description="root"),
                Goal(goal_id="g1", description="A", parent_id="root", priority=0),
                Goal(goal_id="g2", description="B", parent_id="root", priority=1),
            ],
        )
        sq = [{"text": "A"}, {"text": "B"}]
        out = schedule_sub_goals_from_graph(graph, sq)
        assert any(item.get("goal_id") for item in out)


@pytest.mark.asyncio
async def test_build_multi_execution_graph_mocked(monkeypatch):
    from kernel.cognition import multi_execution_planner as mep
    from kernel.runtime.objects import ExecutionNode

    async def fake_plan_and_project(query, ctx, understanding=None):
        sq = (ctx.metadata or {}).get("sub_question_id", "sq")
        gid = (ctx.metadata or {}).get("sub_goal_id", "")
        node = ExecutionNode(
            node_id="n1",
            capability_name="model.answer",
            query=query,
            goal_id=gid,
            params={"goal_id": gid},
        )
        return None, None, [node]

    class FakePlanner:
        plan_and_project = staticmethod(fake_plan_and_project)

    import kernel.cognition.planner_facade as pf

    monkeypatch.setattr(pf, "ExecutionPlanner", FakePlanner)

    req = type(
        "R",
        (),
        {
            "query": "A？B？",
            "session_id": "s",
            "user_id": "u",
            "metadata": {
                "request_id": "r1",
                "intent_lock": {"allowed_capabilities": ["model.answer"]},
                "goal_graph": {"root_goal_id": "root", "goals": []},
            },
            "history": [],
            "conversation_state": None,
            "web_enabled": False,
            "trace_ctx": None,
        },
    )()

    sub_q = [
        {"id": "q1", "text": "part A", "goal_id": "g1"},
        {"id": "q2", "text": "part B", "goal_id": "g2"},
    ]
    nodes, meta = await mep.build_multi_execution_graph(req, sub_q)
    assert len(nodes) == 2
    assert all(getattr(n, "goal_id", "") for n in nodes)
    assert meta[0].get("node_id")
    assert meta[0].get("node_id")