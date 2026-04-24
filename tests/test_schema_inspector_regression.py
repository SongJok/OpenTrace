import unittest
from unittest.mock import AsyncMock, Mock, patch


class SchemaInspectorRegressionTests(unittest.TestCase):
    def test_schema_inspector_extracts_table_names(self):
        from infra.metadata.schema_inspector import SchemaInspectionResult, build_schema_hint

        payload = {"tables": [{"name": "orders"}, {"name": "users"}, {"name": ""}]}
        hint = build_schema_hint(payload)
        self.assertIn("orders", hint)
        self.assertIn("users", hint)
        result = SchemaInspectionResult(schema_payload=payload, table_names=["orders", "users"], table_count=2)
        self.assertEqual(result.table_count, 2)

    def test_data_query_uses_loaded_schema_inspection(self):
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
            source.database = "test_db"
            source.username = "root"
            source.password_encrypted = "enc"

            db = AsyncMock()
            db.execute.side_effect = [Mock(scalar_one_or_none=Mock(return_value=source))]

            with patch("gateway.api_gateway.routers.data.load_schema_inspection") as load_mock, \
                 patch("gateway.api_gateway.routers.data.SQLPlanner") as planner_cls, \
                 patch("gateway.api_gateway.routers.data.SQLValidator") as validator_cls, \
                 patch("gateway.api_gateway.routers.data.normalize_sql_for_dialect") as normalize_mock, \
                 patch("gateway.api_gateway.routers.data.DBRouter") as router_cls, \
                 patch("gateway.api_gateway.routers.data.SQLExecutor") as exec_cls:
                load_mock.return_value = Mock(schema_payload={"tables": [{"name": "orders"}, {"name": "users"}]}, table_names=["orders", "users"], table_count=2)
                planner = AsyncMock()
                planner.plan.return_value = "SELECT * FROM orders"
                planner_cls.return_value = planner
                validator = Mock()
                validator.validate.return_value = "SELECT * FROM orders LIMIT 100"
                validator_cls.return_value = validator
                normalize_mock.side_effect = lambda sql, dialect: sql
                router = Mock()
                router.build_dsn.return_value = "dsn"
                router_cls.return_value = router
                executor = AsyncMock()
                executor.run_on_dsn.return_value = [{"id": 1}]
                exec_cls.return_value = executor

                resp = await data_query(
                    DataQueryRequest(question="查订单", data_source_id="ds1", dry_run=False, sql=None),
                    current_user=current_user,
                    db=db,
                )
                return resp, planner

        resp, planner = asyncio_run(_run())
        self.assertEqual(resp["data_source_id"], "ds1")
        planner.plan.assert_awaited()


def asyncio_run(coro):
    import asyncio
    return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()
