"""监督层流水线内澄清门的集成测试。

验证：
1. 澄清在 SQL 执行前短路
2. clarify_context 与原始查询正确合并
3. 已澄清查询（含 clarify_context）不重复触发
4. 明确查询正常继续
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch


class SupervisorClarificationIntegrationTests(unittest.TestCase):
    """Test the supervisor's integration with DataClarificationGate."""

    def setUp(self):
        from kernel.agent_runtime.tier2_registry import list_tier2_agent_types

        list_tier2_agent_types()

    def _make_task(self, **kwargs):
        from agents.base import TaskMessage

        defaults = {
            "task_id": "test_clarify_001",
            "agent_type": "data",
            "query": "帮我查一下数据",
            "params": {
                "data_source_id": "ds-test-001",
                "_dsn": "postgresql://localhost/test",
                "dialect": "postgresql",
                "schema_hint": '{"tables":[{"name":"dim_user","columns":[{"name":"grade_name","comment":"等级名称"},{"name":"user_name","comment":"用户名称"}]}]}',
                "table_names": ["dim_user"],
                "table_columns": {"dim_user": ["grade_name", "user_name"]},
                "dry_run": True,
                "clarify_context": "",
            },
            "session_id": None,
            "user_id": "test-user",
        }
        defaults.update(kwargs)
        return TaskMessage(**defaults)

    def _run(self, coro):
        return asyncio.run(coro)

    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._load_datasource_metadata", new_callable=AsyncMock)
    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._run_knowledge_layer", new_callable=AsyncMock)
    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._execute_dag", new_callable=AsyncMock)
    def test_vague_query_triggers_clarification(self, mock_dag, mock_kb, mock_load):
        """A vague query with no entities should trigger a clarification response."""
        from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
        from agents.data_agent_v2.types import CognitiveContext

        vague_ctx = CognitiveContext(
            query="帮我查一下数据",
            data_source_id="ds-test-001",
            dialect="postgresql",
            schema_hint='{"tables":[{"name":"dim_user","columns":[{"name":"grade_name"}]}]}',
            table_names=["dim_user"],
            table_columns={"dim_user": ["grade_name"]},
            intent={"intent_type": "raw_lookup", "confidence": 0.3},
            entities=[],
            metrics=[],
        )
        mock_dag.return_value = vague_ctx
        mock_kb.return_value = vague_ctx
        mock_load.return_value = None

        supervisor = DataAgentV2Supervisor()
        task = self._make_task()

        result = supervisor._coerce_agent_result(
            self._run(supervisor.execute(task))
        )

        self.assertEqual(result.status, "success")
        self.assertTrue(result.metadata.get("needs_clarification"))
        self.assertIsNotNone(result.metadata.get("clarification"))
        self.assertLess(result.confidence, 0.3)

    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._load_datasource_metadata", new_callable=AsyncMock)
    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._run_knowledge_layer", new_callable=AsyncMock)
    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._execute_dag", new_callable=AsyncMock)
    def test_clarify_context_skips_clarification_check(self, mock_dag, mock_kb, mock_load):
        """When clarify_context is provided, skip re-clarification and proceed."""
        from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
        from agents.data_agent_v2.types import CognitiveContext

        clarified_ctx = CognitiveContext(
            query="原始问题：帮我查一下数据\n用户补充信息：统计 dim_user 表中各 grade_name 的数量",
            data_source_id="ds-test-001",
            dialect="postgresql",
            schema_hint='{"tables":[{"name":"dim_user","columns":[{"name":"grade_name"}]}]}',
            table_names=["dim_user"],
            table_columns={"dim_user": ["grade_name"]},
            intent={"intent_type": "aggregation", "confidence": 0.85, "dimensions": ["grade_name"]},
            entities=[{"mention": "dim_user", "mapped_table": "dim_user"}],
            metrics=[{"mention": "数量", "mapped_column": "grade_name", "agg": "COUNT"}],
            clarify_context="统计 dim_user 表中各 grade_name 的数量",
            compiled_sql="SELECT COUNT(*) AS count, grade_name FROM dim_user GROUP BY grade_name",
            verification_report={"status": "pass", "issues": []},
        )
        mock_dag.return_value = clarified_ctx
        mock_kb.return_value = clarified_ctx
        mock_load.return_value = None

        supervisor = DataAgentV2Supervisor()
        task = self._make_task(
            query="帮我查一下数据",
            params={
                "data_source_id": "ds-test-001",
                "_dsn": "postgresql://localhost/test",
                "dialect": "postgresql",
                "schema_hint": '{"tables":[{"name":"dim_user"}]}',
                "table_names": ["dim_user"],
                "table_columns": {"dim_user": ["grade_name"]},
                "dry_run": True,
                "clarify_context": "统计 dim_user 表中各 grade_name 的数量",
            },
        )

        result = supervisor._coerce_agent_result(
            self._run(supervisor.execute(task))
        )

        self.assertFalse(result.metadata.get("needs_clarification", False))
        self.assertEqual(result.status, "success")
        self.assertIn("grade_name", result.metadata.get("sql", ""))

    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._load_datasource_metadata", new_callable=AsyncMock)
    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._run_knowledge_layer", new_callable=AsyncMock)
    @patch("agents.data_agent_v2.supervisor.DataAgentV2Supervisor._execute_dag", new_callable=AsyncMock)
    def test_clear_query_proceeds_normally(self, mock_dag, mock_kb, mock_load):
        """A clear, specific query should not trigger clarification."""
        from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
        from agents.data_agent_v2.types import CognitiveContext

        clear_ctx = CognitiveContext(
            query="统计 dim_user 表中各 grade_name 的用户数量",
            data_source_id="ds-test-001",
            dialect="postgresql",
            schema_hint='{"tables":[{"name":"dim_user","columns":[{"name":"grade_name"}]}]}',
            table_names=["dim_user"],
            table_columns={"dim_user": ["grade_name"]},
            intent={"intent_type": "aggregation", "confidence": 0.85, "dimensions": ["grade_name"]},
            entities=[{"mention": "dim_user", "mapped_table": "dim_user"}],
            metrics=[{"mention": "数量", "mapped_column": "grade_name", "agg": "COUNT"}],
            compiled_sql="SELECT COUNT(*) AS count, grade_name FROM dim_user GROUP BY grade_name",
            verification_report={"status": "pass", "issues": []},
        )
        mock_dag.return_value = clear_ctx
        mock_kb.return_value = clear_ctx
        mock_load.return_value = None

        supervisor = DataAgentV2Supervisor()
        task = self._make_task(
            query="统计 dim_user 表中各 grade_name 的用户数量",
            params={
                "data_source_id": "ds-test-001",
                "_dsn": "postgresql://localhost/test",
                "dialect": "postgresql",
                "schema_hint": '{"tables":[{"name":"dim_user"}]}',
                "table_names": ["dim_user"],
                "table_columns": {"dim_user": ["grade_name"]},
                "dry_run": True,
            },
        )

        result = supervisor._coerce_agent_result(
            self._run(supervisor.execute(task))
        )

        self.assertFalse(result.metadata.get("needs_clarification", False))
        self.assertIn("grade_name", result.metadata.get("sql", ""))


if __name__ == "__main__":
    unittest.main()
