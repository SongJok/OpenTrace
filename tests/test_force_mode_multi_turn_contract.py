"""force_mode 多轮与多问契约测试。"""

from __future__ import annotations

import pytest


class TestForceModeIntentLock:
    def test_force_mode_follow_up_enables_memory_injection(self):
        from kernel.cognitive_controls import classify_intent

        lock = classify_intent(
            "那上个月呢？",
            force_mode="rag",
            prior_intent="rag",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "rag"
        assert lock.cognitive_budget.memory_injection is True
        assert lock.cognitive_budget.max_memory_tokens >= 512

    def test_force_mode_sticky_domain_alias(self):
        from kernel.cognitive_controls import classify_intent

        lock = classify_intent(
            "再查一下",
            force_mode="data_query",
            prior_intent="data_query",
            conversation_phase="drill_down",
        )
        assert lock.task_type == "data_query"


class TestForceModeMultiQuestionFilter:
    def test_pick_capability_force_mode_rag(self):
        from kernel.cognition.multi_execution_planner import _pick_capability_for_sub

        cap = _pick_capability_for_sub(
            {"domain": "web_search", "text": "x"},
            "rag",
            {},
        )
        assert cap == "rag.retrieve"