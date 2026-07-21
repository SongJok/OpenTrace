"""Data Agent V2 ↔ DataClarificationGate integration contracts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _mock_ctx(**kwargs):
    from dataclasses import dataclass, field

    @dataclass
    class MockCtx:
        query: str = ""
        table_names: list = field(default_factory=list)
        table_columns: dict = field(default_factory=dict)
        intent: dict | None = None
        entities: list | None = None
        metrics: list | None = None
        compiled_sql: str = ""
        needs_clarification: bool = False
        clarification: dict | None = None

    defaults = {
        "query": "帮我查一下数据",
        "entities": [],
        "metrics": [],
        "table_names": ["orders"],
    }
    defaults.update(kwargs)
    return MockCtx(**defaults)


class TestSupervisorClarificationWiring:
    def test_supervisor_imports_data_clarification_gate(self):
        sup = (ROOT / "agents" / "data_agent_v2" / "supervisor.py").read_text(encoding="utf-8")
        assert "DataClarificationGate" in sup
        assert "data_agent_v2_clarification_enabled" in sup
        assert "_build_clarification_result" in sup

    @pytest.mark.asyncio
    async def test_check_clarification_returns_none_when_clear(self):
        from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
        from agents.base import TaskMessage

        sup = DataAgentV2Supervisor()
        task = TaskMessage(task_id="t1", agent_type="data", query="orders 销售额")
        ctx = _mock_ctx(
            query="orders 销售额",
            entities=[{"mention": "orders", "mapped_table": "orders"}],
            metrics=[{"mention": "sales", "mapped_column": "amount", "agg": "SUM"}],
        )
        out = await sup._check_clarification(task, ctx)
        assert out is None

    @pytest.mark.asyncio
    async def test_check_clarification_returns_question_when_vague(self):
        from dataclasses import asdict

        from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
        from agents.base import TaskMessage
        from kernel.clarification_gate import ClarificationQuestion

        sup = DataAgentV2Supervisor()
        task = TaskMessage(task_id="t2", agent_type="data", query="帮我查一下数据")
        ctx = _mock_ctx(query="帮我查一下数据", entities=[], metrics=[])

        fake_q = ClarificationQuestion(
            question_id="q1",
            question_text="您想查哪张表？",
            missing_entities=["table"],
            suggested_options=["orders", "users"],
        )

        with patch(
            "kernel.clarification_gate.DataClarificationGate.generate_question",
            new=AsyncMock(return_value=fake_q),
        ):
            out = await sup._check_clarification(task, ctx)

        assert out is not None
        assert out.get("question_text") == "您想查哪张表？"
        assert out == asdict(fake_q)


def test_clarification_result_metadata_shape():
    from kernel.clarification_gate import ClarificationQuestion

    q = ClarificationQuestion(
        question_id="id1",
        question_text="请选择时间范围",
        missing_entities=["time_range"],
        suggested_options=["近7天", "近30天"],
    )
    d = {
        "question_text": q.question_text,
        "missing_entities": list(q.missing_entities),
        "suggested_options": list(q.suggested_options),
        "question_id": q.question_id,
    }
    assert d["question_text"]
    assert len(d["suggested_options"]) == 2