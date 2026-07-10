import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch


def _make_schema_mock():
    schema_row = Mock(spec=["schema_json", "semantic_mappings"])
    schema_row.schema_json = '{"tables":[{"name":"orders"},{"name":"users"}]}'
    schema_row.semantic_mappings = {}
    return schema_row


def _make_data_source_mock():
    source = Mock(spec=["id", "user_id", "source_type", "host", "port", "database", "username", "password_encrypted"])
    source.id = "ds1"
    source.user_id = "u1"
    source.source_type = "mysql"
    source.host = "localhost"
    source.port = 3306
    source.database = "test_db"
    source.username = "root"
    source.password_encrypted = "enc"
    return source


def _make_db_mock():
    db = AsyncMock()
    db.execute.side_effect = [
        Mock(scalar_one_or_none=Mock(return_value=_make_data_source_mock())),
        Mock(scalar_one_or_none=Mock(return_value=_make_schema_mock())),
        Mock(scalar_one_or_none=Mock(return_value=_make_schema_mock())),
    ]
    return db


class Text2SqlRegressionTests(unittest.TestCase):
    def test_data_query_uses_schema_payload_for_text2sql(self):
        from gateway.api_gateway.routers.data import DataQueryRequest, data_query
        from infra.storage.models import User

        async def _run():
            current_user = Mock(spec=User)
            current_user.id = "u1"
            db = _make_db_mock()

            with patch("gateway.api_gateway.routers.data.get_settings") as settings_mock, \
                 patch("gateway.api_gateway.routers.data.decrypt_data_source_secret", return_value="secret"), \
                 patch("gateway.api_gateway.routers.data.SQLPlanner") as planner_cls, \
                 patch("gateway.api_gateway.routers.data.SQLValidator") as validator_cls, \
                 patch("gateway.api_gateway.routers.data.normalize_sql_for_dialect") as normalize_mock, \
                 patch("gateway.api_gateway.routers.data.DBRouter") as router_cls, \
                 patch("gateway.api_gateway.routers.data.SQLExecutor") as exec_cls:
                settings_mock.return_value = Mock(
                    text2sql_default_limit=100,
                    text2sql_max_retry=0,
                    data_agent_v2_enabled=False,
                )
                planner = AsyncMock()
                planner.plan.return_value = "SELECT count(*) AS table_count FROM information_schema.tables"
                planner_cls.return_value = planner
                validator = Mock()
                validator.validate.return_value = "SELECT count(*) AS table_count FROM information_schema.tables LIMIT 100"
                validator_cls.return_value = validator
                normalize_mock.side_effect = lambda sql, dialect: sql
                router = Mock()
                router.build_dsn.return_value = "dsn"
                router_cls.return_value = router
                executor = AsyncMock()
                executor.run_on_dsn.return_value = [{"table_count": 2}]
                exec_cls.return_value = executor

                resp = await data_query(
                    DataQueryRequest(question="test_db库下有几张表", data_source_id="ds1", dry_run=False, sql=None),
                    current_user=current_user,
                    db=db,
                )
                return resp, planner

        resp, planner = asyncio.run(_run())
        self.assertEqual(resp["data_source_id"], "ds1")
        self.assertIn("table_count", resp["rows"][0])
        self.assertIn("结果为 2", resp["summary"])
        planner.plan.assert_not_called()

    def test_data_query_lists_tables_without_planner(self):
        from gateway.api_gateway.routers.data import DataQueryRequest, data_query
        from infra.storage.models import User

        async def _run():
            current_user = Mock(spec=User)
            current_user.id = "u1"
            db = _make_db_mock()

            with patch("gateway.api_gateway.routers.data.get_settings") as settings_mock, \
                 patch("gateway.api_gateway.routers.data.decrypt_data_source_secret", return_value="secret"), \
                 patch("gateway.api_gateway.routers.data.SQLPlanner") as planner_cls, \
                 patch("gateway.api_gateway.routers.data.SQLValidator") as validator_cls, \
                 patch("gateway.api_gateway.routers.data.normalize_sql_for_dialect") as normalize_mock, \
                 patch("gateway.api_gateway.routers.data.DBRouter") as router_cls, \
                 patch("gateway.api_gateway.routers.data.SQLExecutor") as exec_cls:
                settings_mock.return_value = Mock(
                    text2sql_default_limit=100,
                    text2sql_max_retry=0,
                    data_agent_v2_enabled=False,
                )
                planner = AsyncMock()
                planner.plan.return_value = "SELECT table_name FROM information_schema.tables"
                planner_cls.return_value = planner
                validator = Mock()
                validator.validate.return_value = "SELECT table_name FROM information_schema.tables WHERE table_schema = 'test_db' ORDER BY table_name"
                validator_cls.return_value = validator
                normalize_mock.side_effect = lambda sql, dialect: sql
                router = Mock()
                router.build_dsn.return_value = "dsn"
                router_cls.return_value = router
                executor = AsyncMock()
                executor.run_on_dsn.return_value = [{"table_name": "orders"}, {"table_name": "users"}]
                exec_cls.return_value = executor

                resp = await data_query(
                    DataQueryRequest(question="test_db下面有哪些表", data_source_id="ds1", dry_run=False, sql=None),
                    current_user=current_user,
                    db=db,
                )
                return resp, planner

        resp, planner = asyncio.run(_run())
        self.assertEqual(resp["summary"], "查询成功，共 2 张表：orders、users")
        self.assertEqual(resp["rows"][0]["table_name"], "orders")
        planner.plan.assert_not_called()

    def test_data_agent_uses_structured_query_when_sql_missing(self):
        """When a natural-language query (no SQL) is submitted, the pipeline
        should understand the intent via semantic parsing and produce valid SQL
        deterministically — no planner.plan() call required."""
        from agents.data_agent import DataAgent
        from agents.base import TaskMessage
        from infra.storage.models import DataSource, DataSourceSchema
        from kernel.data_cognition.logical_plan import LogicalPlan, Projection

        async def _run():
            task = TaskMessage(task_id="t1", agent_type="data",
                               query="test_db库下有几张表",
                               params={"data_source_id": "ds1"})
            ds = Mock(spec=DataSource)
            ds.source_type = "mysql"
            ds.host = "localhost"
            ds.port = 3306
            ds.database = "test_db"
            ds.username = "root"
            ds.password_encrypted = "enc"

            schema_row = Mock(spec=DataSourceSchema)
            schema_row.schema_json = '{"tables":[{"name":"orders"},{"name":"users"}]}'
            schema_row.semantic_mappings = {}

            db1 = AsyncMock()
            db1.execute.side_effect = [
                Mock(scalar_one_or_none=Mock(return_value=ds)),
                Mock(scalar_one_or_none=Mock(return_value=schema_row)),
                Mock(scalar_one_or_none=Mock(return_value=schema_row)),
            ]

            with patch("agents.data_agent.settings.data_agent_v2_enabled", False), \
                 patch("agents.data_agent.AsyncSessionLocal") as session_mock, \
                 patch("agents.data_agent.decrypt_data_source_secret", return_value="secret"), \
                 patch("agents.data_agent.DBRouter") as router_cls, \
                 patch("agents.data_agent.SQLExecutor_from_executor") as exec_fn, \
                 patch("agents.data_agent.SemanticParser") as sp_cls, \
                 patch("agents.data_agent.QueryPlanner") as qp_cls, \
                 patch("agents.data_agent.SQLBuilder") as sb_cls, \
                 patch("agents.data_agent.QueryExecutor") as qe_cls:
                session_mock.side_effect = [
                    AsyncMock(__aenter__=AsyncMock(return_value=db1),
                              __aexit__=AsyncMock(return_value=None))]

                router = Mock()
                router.build_dsn.return_value = "dsn"
                router_cls.return_value = router

                executor = AsyncMock()
                executor.run_on_dsn.return_value = [{"table_count": 2}]
                exec_fn.return_value = executor

                # SemanticParser: check_structured_intent returns SQL for meta-queries
                semantic_parser = Mock()
                semantic_parser.check_structured_intent.return_value = \
                    "SELECT count(*) AS table_count FROM information_schema.tables"
                sp_cls.return_value = semantic_parser

                # QueryPlanner fallback
                query_planner = AsyncMock()
                plan = LogicalPlan(
                    tables=["information_schema.tables"],
                    projections=[Projection(expr="count(*)", alias="table_count")],
                )
                query_planner.plan.return_value = plan
                qp_cls.return_value = query_planner

                # SQLBuilder
                sql_builder = Mock()
                sql_builder.build.return_value = \
                    "SELECT count(*) AS table_count FROM `information_schema`.`tables`"
                sb_cls.return_value = sql_builder

                # QueryExecutor
                query_executor = AsyncMock()
                query_executor.run_with_retry.return_value = (
                    [{"table_count": 2}],
                    "SELECT count(*) AS table_count FROM `information_schema`.`tables`",
                    [],
                )
                qe_cls.return_value = query_executor

                result = await DataAgent().execute(task)
                return result, semantic_parser, query_planner

        result, semantic_parser, query_planner = asyncio.run(_run())
        self.assertEqual(result.status, "success")
        self.assertEqual(result.metadata["data_source_id"], "ds1")
        self.assertEqual(result.metadata["rows"][0]["table_count"], 2)
        self.assertIn("information_schema.tables", result.metadata["sql"])
        # The structured intent check should have produced SQL directly,
        # so query_planner.plan() should NOT have been called
        query_planner.plan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
