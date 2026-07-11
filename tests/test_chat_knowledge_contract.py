"""Pure contracts for the chat-facing knowledge orchestration boundary."""

import unittest

from knowledge.chat_actions import infer_knowledge_action
from kernel.turn_bootstrap import TurnBootstrapResult


class ChatKnowledgeContractTests(unittest.TestCase):
    def test_explicit_knowledge_commands_are_the_only_side_effecting_routes(self):
        self.assertEqual(infer_knowledge_action("把刚上传的制度加入知识库"), "ingest")
        self.assertEqual(infer_knowledge_action("检查知识库有哪些过期内容"), "lint")
        self.assertEqual(infer_knowledge_action("根据反馈优化规则"), "evolve")
        self.assertEqual(infer_knowledge_action("这条回答来自哪份文档"), "trace")
        self.assertEqual(infer_knowledge_action("根据知识库说明退款流程"), "query")

    def test_turn_bootstrap_result_remains_structured_for_shared_decision(self):
        self.assertEqual(
            set(TurnBootstrapResult.__dataclass_fields__),
            {"effective_query", "intent_lock", "world_hydrate", "multi_turn_applied"},
        )
