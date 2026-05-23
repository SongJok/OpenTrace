import unittest


class SchemaInspectorRegressionTests(unittest.TestCase):
    def test_schema_inspector_extracts_table_names(self):
        from infra.metadata.schema_inspector import SchemaInspectionResult, build_schema_hint

        payload = {"tables": [{"name": "orders"}, {"name": "users"}, {"name": ""}]}
        hint = build_schema_hint(payload)
        self.assertIn("orders", hint)
        self.assertIn("users", hint)
        result = SchemaInspectionResult(schema_payload=payload, table_names=["orders", "users"], table_count=2, column_map={})
        self.assertEqual(result.table_count, 2)

    def test_schema_inspector_handles_empty_payload(self):
        from infra.metadata.schema_inspector import build_schema_hint

        hint = build_schema_hint({})
        self.assertIsInstance(hint, str)

    def test_schema_inspection_result_defaults(self):
        from infra.metadata.schema_inspector import SchemaInspectionResult

        result = SchemaInspectionResult(schema_payload={}, table_names=[], table_count=0, column_map={})
        self.assertEqual(result.table_count, 0)
        self.assertEqual(result.table_names, [])
        self.assertEqual(result.column_map, {})


if __name__ == "__main__":
    unittest.main()
