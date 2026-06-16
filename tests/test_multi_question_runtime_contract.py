"""多问运行时 V2 契约测试。"""

from __future__ import annotations

import pytest


class TestMultiQuestionDecompose:
    def test_is_multi_two_question_marks(self):
        from kernel.cognition.multi_question import is_multi_question

        assert is_multi_question("北京的首都是什么？上海呢？") is True

    def test_split_syntax(self):
        from kernel.cognition.multi_question import split_by_syntax

        parts = split_by_syntax("问题一？问题二？")
        assert parts is not None
        assert len(parts) >= 2

    @pytest.mark.asyncio
    async def test_decompose_syntax(self):
        from kernel.cognition.multi_question import decompose_query

        subs = await decompose_query("销量多少？文档里怎么说？")
        assert subs is not None
        assert len(subs) >= 2
        assert all("text" in s and "domain" in s for s in subs)


class TestMultiQuestionReplayContract:
    def test_replay_contract_shape(self):
        from kernel.protocol.behavior_contracts import ReplayContract, validate_replay_contract

        rc = ReplayContract(
            request_id="r",
            session_id="s",
            root_goal_id="root",
            artifact_id="multi:r",
            evidence_ids=["e1"],
        )
        assert validate_replay_contract(rc) == []


class TestGoalGraphMulti:
    def test_goal_planner_extends_subgoals(self):
        from kernel.cognition.planner_facade import GoalPlanner
        from kernel.cognitive_kernel import KernelRequest

        req = KernelRequest(
            query="a？b？",
            metadata={
                "request_id": "r-mq",
                "intent_lock": {"protected_intent": "a？b？", "task_type": "general_qa"},
                "decomposed_goals": [
                    {"id": "q1", "text": "a", "domain": "general_qa"},
                    {"id": "q2", "text": "b", "domain": "web_search"},
                ],
            },
        )
        g = GoalPlanner().build_from_request(req)
        assert len(g.goals) >= 3  # root + 2 subs