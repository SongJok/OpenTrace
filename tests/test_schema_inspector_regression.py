import json
import unittest
from types import SimpleNamespace

import pytest


class SchemaInspectorRegressionTests(unittest.TestCase):
    def test_schema_inspector_extracts_table_names(self):
        from infra.metadata.schema_inspector import SchemaInspectionResult, build_schema_hint

        payload = {"tables": [{"name": "orders"}, {"name": "users"}, {"name": ""}]}
        hint = build_schema_hint(payload)
        self.assertIn("orders", hint)
        self.assertIn("users", hint)
        result = SchemaInspectionResult(
            schema_payload=payload, table_names=["orders", "users"], table_count=2, column_map={}
        )
        self.assertEqual(result.table_count, 2)

    def test_schema_inspector_handles_empty_payload(self):
        from infra.metadata.schema_inspector import build_schema_hint

        hint = build_schema_hint({})
        self.assertIsInstance(hint, str)

    def test_schema_inspection_result_defaults(self):
        from infra.metadata.schema_inspector import SchemaInspectionResult

        result = SchemaInspectionResult(
            schema_payload={}, table_names=[], table_count=0, column_map={}
        )
        self.assertEqual(result.table_count, 0)
        self.assertEqual(result.table_names, [])
        self.assertEqual(result.column_map, {})


if __name__ == "__main__":
    unittest.main()


@pytest.mark.asyncio
async def test_column_map_qualifies_only_clickhouse_server_scope():
    from infra.metadata.schema_inspector import load_schema_inspection

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(
                schema_json=json.dumps(
                    {
                        "database_scope": "app",
                        "tables": [
                            {
                                "name": "orders",
                                "database": "public",
                                "columns": [{"name": "id"}],
                            }
                        ],
                    }
                )
            )

    class _Db:
        async def execute(self, _statement):
            return _Result()

    result = await load_schema_inspection(_Db(), "source-1")
    assert result.column_map == {"orders": ["id"]}
