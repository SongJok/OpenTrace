import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch


class StreamFallbackSyncBehaviorTests(unittest.TestCase):
    def test_database_intent_detects_common_phrasings(self):
        from gateway.api_gateway.routers.chat import _database_intent

        self.assertTrue(_database_intent("帮我查最近7天订单金额"))
        self.assertTrue(_database_intent("请分析这个数据库里的销售数据"))
        self.assertTrue(_database_intent("show tables and count rows"))
        self.assertTrue(_database_intent("test_db库下有几张表"))
        self.assertFalse(_database_intent("帮我写一段 Python 代码"))

    def test_plan_agent_attaches_data_source_id_for_data_intent(self):
        from kernel.plan_agent import PlanAgent, SubTask

        agent = PlanAgent()
        # Use the real rule function through generate_plan by stubbing the LLM response.
        with patch("kernel.plan_agent.get_model_gateway") as gw_mock:
            resp = Mock(content='{"subtasks":[{"agent_type":"data","query":"查订单","params":{}}],"merge_strategy":"prioritized","max_parallel":3}')
            gw_mock.return_value.complete = AsyncMock(return_value=resp)
            out = asyncio.run(
                agent.generate_plan(
                    "test_db库下有几张表",
                    context={"metadata": {"data_source_id": "ds_123"}, "adaptive_profile": {"name": "balanced"}},
                )
            )
        self.assertEqual(out.subtasks[0].agent_type, "data")
        self.assertEqual(out.subtasks[0].params.get("data_source_id"), "ds_123")

    def test_data_query_builds_sql_via_planner_when_sql_missing(self):
        from gateway.api_gateway.routers.data import DataQueryRequest, data_query
        from infra.storage.models import DataSource, User

        async def _run():
            current_user = Mock(spec=User)
            current_user.id = "u1"
            source = Mock(spec=DataSource)
            source.id = "ds1"
            source.user_id = "u1"
            source.source_type = "mysql"
            source.host = "localhost"
            source.port = 3306
            source.database = "db"
            source.username = "root"
            source.password_encrypted = "enc"

            schema_row = Mock()
            schema_row.schema_json = "{}"
            schema_row.semantic_mappings = {}

            db = AsyncMock()
            db.execute.side_effect = [
                Mock(scalar_one_or_none=Mock(return_value=source)),
                Mock(scalar_one_or_none=Mock(return_value=schema_row)),
                Mock(scalar_one_or_none=Mock(return_value=schema_row)),
            ]

            with patch("gateway.api_gateway.routers.data.get_settings") as settings_mock, \
                 patch("gateway.api_gateway.routers.data._dec", return_value="secret"), \
                 patch("gateway.api_gateway.routers.data.SQLPlanner") as planner_cls, \
                 patch("gateway.api_gateway.routers.data.SQLValidator") as validator_cls, \
                 patch("gateway.api_gateway.routers.data.SQLRewriter") as rewriter_cls, \
                 patch("gateway.api_gateway.routers.data.DBRouter") as router_cls, \
                 patch("gateway.api_gateway.routers.data.SQLExecutor") as exec_cls, \
                 patch("gateway.api_gateway.routers.data.normalize_sql_for_dialect") as normalize_mock, \
                 patch("gateway.api_gateway.routers.data.SQLRanker") as ranker_cls, \
                 patch("gateway.api_gateway.routers.data.SQLReflector") as reflector_cls:
                settings_mock.return_value = Mock(text2sql_default_limit=100, text2sql_max_retry=0)
                planner = AsyncMock()
                planned = Mock()
                planned.sql = "SELECT count(*) FROM orders"
                planner.plan.return_value = planned
                planner.generate_candidates.return_value = []
                planner_cls.return_value = planner
                validator = Mock()
                validator.validate.return_value = "SELECT count(*) FROM orders LIMIT 100"
                validator_cls.return_value = validator
                rewriter = AsyncMock()
                rewriter.rewrite.return_value = "SELECT count(*) FROM orders LIMIT 100"
                rewriter_cls.return_value = rewriter
                ranker = Mock()
                ranker.rank.return_value = []
                ranker_cls.return_value = ranker
                reflector = Mock()
                reflector.MAX_REFLECTION_ROUNDS = 0
                reflector_cls.return_value = reflector
                router = Mock()
                router.build_dsn.return_value = "dsn"
                router_cls.return_value = router
                executor = AsyncMock()
                executor.run_on_dsn.return_value = [{"count": 1}]
                exec_cls.return_value = executor
                normalize_mock.side_effect = lambda sql, dialect: sql

                resp = await data_query(
                    DataQueryRequest(question="查订单", data_source_id="ds1", dry_run=False, sql=None),
                    current_user=current_user,
                    db=db,
                )
                return resp, planner

        resp, planner = asyncio.run(_run())
        self.assertEqual(resp["data_source_id"], "ds1")
        self.assertEqual(resp["summary"], "查询成功，结果为 1")
        planner.plan.assert_awaited()


if __name__ == "__main__":
    unittest.main()
