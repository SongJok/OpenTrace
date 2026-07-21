"""Goal Portfolio hierarchy."""

from __future__ import annotations

from kernel.goal.goal_portfolio import GoalPortfolio, PortfolioLevel
from kernel.protocol.runtime_contract import Goal, GoalGraph


class TestGoalPortfolio:
    def test_bind_goal_graph_creates_program_initiative_tasks(self):
        g1 = Goal(goal_id="g-root", description="Root goal")
        g2 = Goal(goal_id="g-sub", description="Sub task", parent_id="g-root")
        graph = GoalGraph(root_goal_id="g-root", goals=[g1, g2])
        p = GoalPortfolio()
        doc = p.bind_goal_graph(graph)
        levels = {n["level"] for n in doc["nodes"]}
        assert PortfolioLevel.PROGRAM.value in levels
        assert PortfolioLevel.INITIATIVE.value in levels
        assert PortfolioLevel.TASK.value in levels
        assert doc["program_id"]