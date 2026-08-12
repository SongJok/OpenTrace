import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from data_agent.contracts import DataSourceDecision


def _make_schema_mock():
    schema_row = Mock(spec=["schema_json", "semantic_mappings"])
    schema_row.schema_json = '{"tables":[{"name":"orders"},{"name":"users"}]}'
    schema_row.semantic_mappings = {}
    return schema_row


def _make_data_source_mock():
    source = Mock(
        spec=[
            "id",
            "user_id",
            "source_type",
            "host",
            "port",
            "database",
            "username",
            "password_encrypted",
        ]
    )
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


class DataAgentRegressionTests(unittest.TestCase):
    def test_data_query_uses_schema_payload_for_data_agent(self):
        from gateway.api_gateway.routers.data import DataQueryRequest, data_query
        from infra.storage.models import User

        async def _run():
            current_user = Mock(spec=User)
            current_user.id = "u1"
            db = _make_db_mock()

            with (
                patch(
                    "gateway.api_gateway.routers.data.get_settings", create=True
                ) as settings_mock,
                patch(
                    "gateway.api_gateway.routers.data.decrypt_data_source_secret",
                    return_value="secret",
                    create=True,
                ),
                patch("gateway.api_gateway.routers.data.SQLPlanner", create=True) as planner_cls,
                patch(
                    "gateway.api_gateway.routers.data.SQLValidator", create=True
                ) as validator_cls,
                patch(
                    "gateway.api_gateway.routers.data.normalize_sql_for_dialect", create=True
                ) as normalize_mock,
                patch("gateway.api_gateway.routers.data.DBRouter", create=True) as router_cls,
                patch("gateway.api_gateway.routers.data.SQLExecutor", create=True) as exec_cls,
                patch("gateway.api_gateway.routers.data.OpenTraceSourceResolver") as resolver_cls,
                patch(
                    "gateway.api_gateway.routers.data.generate_sql_query_draft",
                    new_callable=AsyncMock,
                ) as generate_draft,
                patch("gateway.api_gateway.routers.data.serialize_draft") as serialize_draft,
            ):
                settings_mock.return_value = Mock(
                    data_agent_default_limit=100,
                    data_agent_max_retry=0,
                    data_agent_v2_enabled=False,
                )
                resolver = resolver_cls.return_value.resolve = AsyncMock(
                    return_value=DataSourceDecision(
                        status="selected",
                        question="test_db库下有几张表",
                        selected_data_source_id="ds1",
                        selected_data_source_name="test_db",
                        confidence=1.0,
                    )
                )
                planner = AsyncMock()
                planner.plan.return_value = (
                    "SELECT count(*) AS table_count FROM information_schema.tables"
                )
                planner_cls.return_value = planner
                validator = Mock()
                validator.validate.return_value = (
                    "SELECT count(*) AS table_count FROM information_schema.tables LIMIT 100"
                )
                validator_cls.return_value = validator
                normalize_mock.side_effect = lambda sql, dialect: sql
                router = Mock()
                router.build_dsn.return_value = "dsn"
                router_cls.return_value = router
                executor = AsyncMock()
                executor.run_on_dsn.return_value = [{"table_count": 2}]
                exec_cls.return_value = executor
                draft = Mock(id="draft-1")
                candidate = Mock(
                    id="candidate-1",
                    sql="SELECT count(*) AS table_count FROM information_schema.tables LIMIT 100",
                )
                generate_draft.return_value = (draft, [candidate])
                serialize_draft.return_value = {
                    "status": "awaiting_confirmation",
                    "candidates": [{"id": candidate.id, "sql": candidate.sql}],
                }

                resp = await data_query(
                    DataQueryRequest(
                        question="test_db库下有几张表",
                        data_source_id="ds1",
                        dry_run=False,
                        sql=None,
                    ),
                    current_user=current_user,
                    db=db,
                )
                return resp, planner, exec_cls, resolver, generate_draft

        resp, planner, executor_cls, resolver, generate_draft = asyncio.run(_run())
        self.assertEqual(resp["data_source_id"], "ds1")
        self.assertEqual(resp["rows"], [])
        self.assertFalse(resp["executed"])
        self.assertIn("等待确认执行", resp["summary"])
        self.assertIsNone(resolver.await_args.kwargs["explicit_id"])
        self.assertIsNone(resolver.await_args.kwargs["candidate_ids"])
        self.assertNotIn("project_id", resolver.await_args.kwargs)
        self.assertNotIn("project_id", generate_draft.await_args.kwargs)
        planner.plan.assert_not_called()
        executor_cls.assert_not_called()

    def test_data_query_lists_tables_without_planner(self):
        from gateway.api_gateway.routers.data import DataQueryRequest, data_query
        from infra.storage.models import User

        async def _run():
            current_user = Mock(spec=User)
            current_user.id = "u1"
            db = _make_db_mock()

            with (
                patch(
                    "gateway.api_gateway.routers.data.get_settings", create=True
                ) as settings_mock,
                patch(
                    "gateway.api_gateway.routers.data.decrypt_data_source_secret",
                    return_value="secret",
                    create=True,
                ),
                patch("gateway.api_gateway.routers.data.SQLPlanner", create=True) as planner_cls,
                patch(
                    "gateway.api_gateway.routers.data.SQLValidator", create=True
                ) as validator_cls,
                patch(
                    "gateway.api_gateway.routers.data.normalize_sql_for_dialect", create=True
                ) as normalize_mock,
                patch("gateway.api_gateway.routers.data.DBRouter", create=True) as router_cls,
                patch("gateway.api_gateway.routers.data.SQLExecutor", create=True) as exec_cls,
                patch("gateway.api_gateway.routers.data.OpenTraceSourceResolver") as resolver_cls,
                patch(
                    "gateway.api_gateway.routers.data.generate_sql_query_draft",
                    new_callable=AsyncMock,
                ) as generate_draft,
                patch("gateway.api_gateway.routers.data.serialize_draft") as serialize_draft,
            ):
                settings_mock.return_value = Mock(
                    data_agent_default_limit=100,
                    data_agent_max_retry=0,
                    data_agent_v2_enabled=False,
                )
                resolver_cls.return_value.resolve = AsyncMock(
                    return_value=DataSourceDecision(
                        status="selected",
                        question="test_db下面有哪些表",
                        selected_data_source_id="ds1",
                        selected_data_source_name="test_db",
                        confidence=1.0,
                    )
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
                executor.run_on_dsn.return_value = [
                    {"table_name": "orders"},
                    {"table_name": "users"},
                ]
                exec_cls.return_value = executor
                draft = Mock(id="draft-1")
                candidate = Mock(
                    id="candidate-1",
                    sql="SELECT table_name FROM information_schema.tables LIMIT 100",
                )
                generate_draft.return_value = (draft, [candidate])
                serialize_draft.return_value = {
                    "status": "awaiting_confirmation",
                    "candidates": [{"id": candidate.id, "sql": candidate.sql}],
                }

                resp = await data_query(
                    DataQueryRequest(
                        question="test_db下面有哪些表",
                        data_source_id="ds1",
                        dry_run=False,
                        sql=None,
                    ),
                    current_user=current_user,
                    db=db,
                )
                return resp, planner, exec_cls

        resp, planner, executor_cls = asyncio.run(_run())
        self.assertEqual(resp["rows"], [])
        self.assertFalse(resp["executed"])
        self.assertIn("等待确认执行", resp["summary"])
        planner.plan.assert_not_called()
        executor_cls.assert_not_called()

    def test_data_agent_uses_structured_query_when_sql_missing(self):
        """When a natural-language query (no SQL) is submitted, the pipeline
        should understand the intent via semantic parsing and produce valid SQL
        deterministically — no planner.plan() call required."""
        from agents.base import TaskMessage
        from agents.data_agent import DataAgentV1
        from infra.storage.models import DataSource, DataSourceSchema
        from kernel.data_cognition.logical_plan import LogicalPlan, Projection

        async def _run():
            task = TaskMessage(
                task_id="t1",
                agent_type="data",
                query="test_db库下有几张表",
                user_id="user-1",
                params={"data_source_id": "ds1", "tenant_id": "default", "workspace_id": "default"},
            )
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

            with (
                patch("agents.data_agent.AsyncSessionLocal") as session_mock,
                patch("agents.data_agent.decrypt_data_source_secret", return_value="secret"),
                patch("agents.data_agent.DBRouter") as router_cls,
                patch("agents.data_agent.SQLExecutor_from_executor") as exec_fn,
                patch("agents.data_agent.SemanticParser") as sp_cls,
                patch("agents.data_agent.QueryPlanner") as qp_cls,
                patch("agents.data_agent.SQLBuilder") as sb_cls,
                patch("agents.data_agent.QueryExecutor") as qe_cls,
            ):
                session_mock.side_effect = [
                    AsyncMock(
                        __aenter__=AsyncMock(return_value=db1),
                        __aexit__=AsyncMock(return_value=None),
                    )
                ]

                router = Mock()
                router.build_dsn.return_value = "dsn"
                router_cls.return_value = router

                executor = AsyncMock()
                executor.run_on_dsn.return_value = [{"table_count": 2}]
                exec_fn.return_value = executor

                # SemanticParser: check_structured_intent returns SQL for meta-queries
                semantic_parser = Mock()
                semantic_parser.check_structured_intent.return_value = (
                    "SELECT count(*) AS table_count FROM information_schema.tables"
                )
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
                sql_builder.build.return_value = (
                    "SELECT count(*) AS table_count FROM `information_schema`.`tables`"
                )
                sb_cls.return_value = sql_builder

                # QueryExecutor
                query_executor = AsyncMock()
                query_executor.run_with_retry.return_value = (
                    [{"table_count": 2}],
                    "SELECT count(*) AS table_count FROM `information_schema`.`tables`",
                    [],
                )
                qe_cls.return_value = query_executor

                result = await DataAgentV1().execute(task)
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
