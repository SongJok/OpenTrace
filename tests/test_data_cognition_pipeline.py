"""Unit tests for the DataAgent pipeline components."""

from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from kernel.data_cognition.logical_plan import (
    FilterSpec, JoinSpec, LogicalPlan, OrderBySpec, Projection,
)
from kernel.data_cognition.sql_builder import SQLBuilder
from kernel.data_cognition.sql_dialect import SQLDialectSpec, detect_sql_dialect, render_time_window
from kernel.data_cognition.schema_linker import SchemaLinker, _fuzzy_table_match
from kernel.data_cognition.table_graph import JoinStep, TableRelationshipGraph
from kernel.data_cognition.types import (
    CandidateSQL, EntityMapping, MetricMapping, SemanticContext,
)


class TestSQLDialect(unittest.TestCase):
    def test_detect_mysql_default(self):
        d = detect_sql_dialect("mysql")
        self.assertEqual(d.name, "mysql")
        self.assertFalse(d.supports_interval_days)

    def test_detect_postgres(self):
        d = detect_sql_dialect("postgres")
        self.assertEqual(d.name, "postgres")
        self.assertTrue(d.supports_interval_days)

    def test_detect_clickhouse(self):
        d = detect_sql_dialect("clickhouse")
        self.assertEqual(d.name, "clickhouse")

    def test_detect_doris(self):
        d = detect_sql_dialect("doris")
        self.assertEqual(d.name, "doris")

    def test_render_time_window_mysql(self):
        d = detect_sql_dialect("mysql")
        sql = render_time_window(d, "created_at", 30)
        self.assertIn("DATE_SUB", sql)
        self.assertIn("30", sql)

    def test_render_time_window_postgres(self):
        d = detect_sql_dialect("postgres")
        sql = render_time_window(d, "created_at", 7)
        self.assertIn("INTERVAL", sql)
        self.assertIn("7", sql)

    def test_render_time_window_no_column(self):
        d = detect_sql_dialect("mysql")
        sql = render_time_window(d, None, 30)
        self.assertEqual(sql, "")


class TestLogicalPlan(unittest.TestCase):
    def test_to_dict_roundtrip(self):
        plan = LogicalPlan(
            tables=["orders o"],
            joins=[JoinSpec("o", "users u", "INNER", "o.user_id = u.id")],
            projections=[Projection(expr="COUNT(*)", alias="cnt", agg_func="COUNT")],
            filters=[FilterSpec(expr="o.status = 'active'", is_having=False)],
            group_by=["o.user_id"],
            order_by=[OrderBySpec(expr="cnt", direction="DESC")],
            limit=50,
        )
        data = plan.to_dict()
        restored = LogicalPlan.from_dict(data)
        self.assertEqual(restored.tables, plan.tables)
        self.assertEqual(len(restored.joins), 1)
        self.assertEqual(len(restored.projections), 1)

    def test_validate_unknown_table(self):
        plan = LogicalPlan(tables=["nonexistent_table"])
        issues = plan.validate(available_tables={"orders"}, available_columns={"orders": {"id", "name"}})
        self.assertTrue(issues)  # unknown table = issue

    def test_validate_valid_plan(self):
        plan = LogicalPlan(
            tables=["orders"],
            projections=[Projection(expr="*")],
        )
        issues = plan.validate(available_tables={"orders"}, available_columns={"orders": {"id", "name", "status"}})
        self.assertEqual(len(issues), 0)


class TestSQLBuilder(unittest.TestCase):
    def setUp(self):
        self.mysql_dialect = detect_sql_dialect("mysql")
        self.postgres_dialect = detect_sql_dialect("postgres")

    def test_build_simple_select(self):
        plan = LogicalPlan(tables=["orders o"], limit=10)
        sql = SQLBuilder().build(plan, self.mysql_dialect)
        self.assertIn("SELECT", sql)
        self.assertIn("FROM", sql)
        self.assertIn("orders", sql)
        self.assertIn("LIMIT 10", sql)

    def test_build_with_projections(self):
        plan = LogicalPlan(
            tables=["orders o"],
            projections=[Projection(expr="o.name", alias="name")],
            limit=50,
        )
        sql = SQLBuilder().build(plan, self.mysql_dialect)
        self.assertIn("o.name AS", sql)
        self.assertIn("LIMIT 50", sql)

    def test_build_with_filters(self):
        plan = LogicalPlan(
            tables=["orders o"],
            filters=[FilterSpec(expr="o.status = 'active'")],
            limit=100,
        )
        sql = SQLBuilder().build(plan, self.mysql_dialect)
        self.assertIn("WHERE", sql)
        self.assertIn("o.status", sql)

    def test_build_with_group_by(self):
        plan = LogicalPlan(
            tables=["orders o"],
            projections=[Projection(expr="COUNT(*)", alias="cnt")],
            group_by=["o.user_id"],
            limit=100,
        )
        sql = SQLBuilder().build(plan, self.mysql_dialect)
        self.assertIn("GROUP BY", sql)
        self.assertIn("o.user_id", sql)

    def test_build_with_order_by(self):
        plan = LogicalPlan(
            tables=["orders o"],
            order_by=[OrderBySpec(expr="o.created_at", direction="DESC")],
            limit=10,
        )
        sql = SQLBuilder().build(plan, self.mysql_dialect)
        self.assertIn("ORDER BY", sql)
        self.assertIn("DESC", sql)

    def test_build_with_join(self):
        plan = LogicalPlan(
            tables=["orders o"],
            joins=[JoinSpec("o", "users u", "INNER", "o.user_id = u.id")],
            limit=100,
        )
        sql = SQLBuilder().build(plan, self.mysql_dialect)
        self.assertIn("JOIN", sql)
        self.assertIn("ON", sql)
        self.assertIn("o.user_id", sql)

    def test_build_empty_join_on_clause_defaults_to_1_equals_1(self):
        """Guard against empty on_clause producing invalid SQL."""
        plan = LogicalPlan(
            tables=["orders o"],
            joins=[JoinSpec("o", "users u", "INNER", "")],
            limit=100,
        )
        sql = SQLBuilder().build(plan, self.mysql_dialect)
        self.assertIn("ON 1=1", sql)

    def test_postgres_identifier_escaping(self):
        plan = LogicalPlan(tables=["my_table t"], limit=10)
        sql = SQLBuilder().build(plan, self.postgres_dialect)
        self.assertIn('"my_table"', sql)

    def test_default_limit_injection(self):
        plan = LogicalPlan(tables=["orders"])
        sql = SQLBuilder(default_limit=100).build(plan, self.mysql_dialect)
        self.assertIn("LIMIT 100", sql)

    def test_alias_escaped(self):
        """Table alias should be escaped like other identifiers."""
        plan = LogicalPlan(tables=["orders order"], limit=10)
        sql = SQLBuilder().build(plan, self.postgres_dialect)
        self.assertIn('"order"', sql)


class TestTableGraph(unittest.TestCase):
    def test_register_and_find_path(self):
        graph = TableRelationshipGraph()
        graph.register_fk("orders", "users", "user_id", "id")
        graph.register_fk("orders", "products", "product_id", "id")

        path = graph.find_join_path("users", "orders")
        self.assertIsNotNone(path)
        self.assertEqual(len(path), 1)
        self.assertEqual(path[0].left_table, "users")
        self.assertEqual(path[0].right_table, "orders")

    def test_find_path_for_tables(self):
        graph = TableRelationshipGraph()
        graph.register_fk("orders", "users", "user_id", "id")

        steps = graph.find_path_for_tables(["users", "orders"])
        self.assertEqual(len(steps), 1)

    def test_infer_tables_from_schema_json(self):
        graph = TableRelationshipGraph()
        schema = '{"tables": [{"name": "orders", "foreign_keys": [{"ref_table": "users", "column": "user_id", "ref_column": "id"}]}]}'
        tables = graph.infer_tables_from_schema_hint(schema)
        self.assertIn("orders", tables)
        self.assertIn("users", tables)


class TestSchemaLinker(unittest.TestCase):
    def test_exact_table_match(self):
        linker = SchemaLinker(table_names=["orders", "users"])
        async def _run():
            return await linker.link_entities("show me the orders table")
        result = asyncio.run(_run())
        self.assertTrue(any(e.mapped_table == "orders" for e in result))

    def test_fuzzy_match_reduces_false_positives(self):
        """Word-boundary match should reject partial-word false positives."""
        # Short table name "usr" won't match "user management" (no exact substring, < 5 chars)
        self.assertFalse(_fuzzy_table_match("usr", "user management"))
        # "orders" as exact substring — matches
        self.assertTrue(_fuzzy_table_match("orders", "show me all orders"))
        # 5+ char table name at word boundary — matches
        self.assertTrue(_fuzzy_table_match("order", "I want to order food"))

    def test_metric_linking_chinese(self):
        linker = SchemaLinker()
        async def _run():
            return await linker.link_metrics("销售额是多少")
        result = asyncio.run(_run())
        self.assertTrue(any(m.mention == "销售额" for m in result))

    def test_metric_linking_english(self):
        linker = SchemaLinker()
        async def _run():
            return await linker.link_metrics("What is the total revenue?")
        result = asyncio.run(_run())
        self.assertTrue(any(m.mention == "revenue" for m in result))


class TestQueryExecutor(unittest.TestCase):
    def test_successful_execution_first_attempt(self):
        from kernel.data_cognition.query_executor import QueryExecutor
        from kernel.data_cognition.sql_validator import SQLValidator
        from kernel.data_cognition.sql_builder import SQLBuilder
        from kernel.data_cognition.sql_reflector import SQLReflector

        builder = Mock()
        builder.build.return_value = "SELECT 1"

        validator = Mock()
        validator.validate.return_value = "SELECT 1"
        validator.validate_semantic.return_value = []
        validator.validate_time_filter.return_value = []

        reflector = Mock()
        reflector.validate_result.return_value = Mock(passed=True, issues=[])

        executor = QueryExecutor(
            validator=validator, builder=builder, reflector=reflector, max_retries=2,
        )

        async def _run():
            with patch("kernel.data_cognition.query_executor.SQLExecutor") as exec_cls:
                mock_exec = AsyncMock()
                mock_exec.run_on_dsn.return_value = [{"1": 1}]
                exec_cls.return_value = mock_exec
                rows, sql, warnings = await executor.run_with_retry(
                    plan=LogicalPlan(tables=["test"]),
                    dsn="mysql+asyncmy://test",
                    dialect=detect_sql_dialect("mysql"),
                )
                return rows, sql, warnings

        result = asyncio.run(_run())
        self.assertEqual(len(result[0]), 1)
        builder.build.assert_called_once()

    def test_retry_with_rewritten_sql(self):
        from kernel.data_cognition.query_executor import QueryExecutor
        from kernel.data_cognition.sql_validator import SQLValidator, SQLValidationError

        builder = Mock()
        builder.build.return_value = "SELECT INVALID_COLUMN FROM test"

        call_count = 0

        def validate_side_effect(sql):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise SQLValidationError("Unknown column")
            return sql  # On retry, accept the SQL as-is

        validator = Mock()
        validator.validate.side_effect = validate_side_effect
        validator.validate_semantic.return_value = []
        validator.validate_time_filter.return_value = []

        reflector = Mock()
        reflector.validate_result.return_value = Mock(passed=True, issues=[])

        executor = QueryExecutor(
            validator=validator, builder=builder, reflector=reflector, max_retries=2,
        )

        async def _run():
            with patch("kernel.data_cognition.query_executor.SQLExecutor") as exec_cls, \
                 patch("kernel.data_cognition.sql_rewriter.SQLRewriter") as rewriter_cls:
                mock_exec = AsyncMock()
                mock_exec.run_on_dsn.return_value = [{"result": 1}]
                exec_cls.return_value = mock_exec

                # LLM returns a corrected SQL
                mock_rewriter = AsyncMock()
                mock_rewriter.rewrite.return_value = "SELECT valid_col FROM test LIMIT 100"
                rewriter_cls.return_value = mock_rewriter

                rows, sql, warnings = await executor.run_with_retry(
                    plan=LogicalPlan(tables=["test"]),
                    dsn="mysql+asyncmy://test",
                    dialect=detect_sql_dialect("mysql"),
                )
                return rows, sql, warnings

        result = asyncio.run(_run())
        # The retry should have used the rewritten SQL
        self.assertEqual(len(result[0]), 1)
        self.assertGreater(call_count, 1)  # validation was called more than once


class TestConfidenceScoring(unittest.TestCase):
    def test_pipeline_mode_higher_base(self):
        from agents.data_agent import DataAgentV1
        agent = DataAgentV1()

        # Pipeline with rows and semantic context
        ctx = SemanticContext(
            dimension_mappings={"dim1": {"column": "x"}},
            metric_defs={"metric1": "SUM(x)"},
            time_macros=[{"pattern": "recent"}],
        )
        score = agent._compute_confidence([{"a": 1}], ctx, mode="pipeline")
        self.assertGreaterEqual(score, 0.90)

    def test_llm_direct_mode_lower_base(self):
        from agents.data_agent import DataAgentV1
        agent = DataAgentV1()

        # LLM direct with no semantic context
        score = agent._compute_confidence([], None, mode="llm_direct")
        self.assertEqual(score, 0.60)  # base only

    def test_empty_result_lower_confidence(self):
        from agents.data_agent import DataAgentV1
        agent = DataAgentV1()

        ctx = SemanticContext()
        score = agent._compute_confidence([], ctx, mode="pipeline")
        self.assertLess(score, 0.85)

    def test_multiple_rows_boost_confidence(self):
        from agents.data_agent import DataAgentV1
        agent = DataAgentV1()

        rows = [{"a": i} for i in range(10)]
        ctx = SemanticContext(
            dimension_mappings={"dim1": {"column": "x"}},
            metric_defs={"metric1": "SUM(x)"},
        )
        score = agent._compute_confidence(rows, ctx, mode="pipeline")
        self.assertGreaterEqual(score, 0.90)


class TestSQLRewriterValidation(unittest.TestCase):
    def test_rejects_empty_output(self):
        from kernel.data_cognition.sql_rewriter import SQLRewriter
        rewriter = SQLRewriter()

        async def _run():
            with patch("kernel.data_cognition.sql_rewriter.get_model_gateway") as gw_mock:
                mock_resp = Mock()
                mock_resp.content = ""
                gw_mock.return_value.complete = AsyncMock(return_value=mock_resp)
                return await rewriter.rewrite("SELECT 1", "error", dialect=detect_sql_dialect("mysql"))

        # Empty output should return None (repair failed)
        self.assertIsNone(asyncio.run(_run()))

    def test_rejects_non_select_output(self):
        from kernel.data_cognition.sql_rewriter import SQLRewriter
        rewriter = SQLRewriter()

        async def _run():
            with patch("kernel.data_cognition.sql_rewriter.get_model_gateway") as gw_mock:
                mock_resp = Mock()
                mock_resp.content = "This is not SQL"
                gw_mock.return_value.complete = AsyncMock(return_value=mock_resp)
                return await rewriter.rewrite("SELECT 1", "error", dialect=detect_sql_dialect("mysql"))

        # Non-SELECT output should return None (repair failed)
        self.assertIsNone(asyncio.run(_run()))

    def test_cleans_markdown_fences(self):
        from kernel.data_cognition.sql_rewriter import SQLRewriter
        rewriter = SQLRewriter()

        async def _run():
            with patch("kernel.data_cognition.sql_rewriter.get_model_gateway") as gw_mock:
                mock_resp = Mock()
                mock_resp.content = "```sql\nSELECT * FROM test LIMIT 10\n```"
                gw_mock.return_value.complete = AsyncMock(return_value=mock_resp)
                return await rewriter.rewrite("SELECT 1", "error", dialect=detect_sql_dialect("mysql"))

        result = asyncio.run(_run())
        self.assertIsNotNone(result)
        self.assertNotIn("```", result)
        self.assertIn("SELECT", result)


if __name__ == "__main__":
    unittest.main()
