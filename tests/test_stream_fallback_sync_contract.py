import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch


class StreamFallbackSyncBehaviorTests(unittest.TestCase):
    def test_responses_path_has_no_keyword_database_router(self):
        from pathlib import Path

        text = (
            Path(__file__).resolve().parents[1] / "gateway/api_gateway/routers/responses.py"
        ).read_text()
        self.assertNotIn("_database_intent", text)

    def test_plan_agent_attaches_data_source_id_for_data_intent(self):
        from kernel.plan_agent import PlanAgent

        agent = PlanAgent()
        with patch("kernel.plan_agent.get_model_gateway") as gw_mock:
            resp = Mock(
                content=(
                    '{"subtasks":[{"agent_type":"data","query":"查订单","params":{}}],'
                    '"merge_strategy":"prioritized","max_parallel":3}'
                )
            )
            gw_mock.return_value.complete = AsyncMock(return_value=resp)
            out = asyncio.run(
                agent.generate_plan(
                    "test_db库下有几张表",
                    context={
                        "metadata": {"data_source_id": "ds_123"},
                        "adaptive_profile": {"name": "balanced"},
                    },
                )
            )
        self.assertEqual(out.subtasks[0].agent_type, "data")
        self.assertEqual(out.subtasks[0].params.get("data_source_id"), "ds_123")

    def test_data_query_generates_draft_without_calling_executor(self):
        from gateway.api_gateway.routers.data import DataQueryRequest, data_query
        from infra.storage.models import DataSource, User

        async def _run():
            current_user = Mock(spec=User)
            current_user.id = "u1"
            source = Mock(spec=DataSource)
            source.id = "ds1"
            source.source_type = "mysql"
            db = AsyncMock()
            draft = Mock(id="draft-1")
            candidate = Mock(id="candidate-1", sql="SELECT count(*) FROM orders LIMIT 100")

            with (
                patch(
                    "gateway.api_gateway.routers.data.get_accessible_data_source",
                    new_callable=AsyncMock,
                    return_value=source,
                ),
                patch(
                    "gateway.api_gateway.routers.data.generate_sql_query_draft",
                    new_callable=AsyncMock,
                    return_value=(draft, [candidate]),
                ) as generate_draft,
                patch(
                    "gateway.api_gateway.routers.data.serialize_draft",
                    return_value={
                        "status": "awaiting_confirmation",
                        "candidates": [{"id": candidate.id, "sql": candidate.sql}],
                    },
                ),
                patch("execution.data.sql_executor.SQLExecutor") as executor_cls,
            ):
                response = await data_query(
                    DataQueryRequest(
                        question="查订单",
                        data_source_id="ds1",
                        dry_run=False,
                    ),
                    current_user=current_user,
                    db=db,
                )
                return response, generate_draft, executor_cls

        response, generate_draft, executor_cls = asyncio.run(_run())
        self.assertEqual(response["data_source_id"], "ds1")
        self.assertEqual(response["rows"], [])
        self.assertFalse(response["executed"])
        self.assertIn("等待确认执行", response["summary"])
        generate_draft.assert_awaited_once()
        executor_cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
