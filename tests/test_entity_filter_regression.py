"""实体分类过滤映射回归测试（例如「队长」→ WHERE role = 'captain'）。

验证：
1. EntityAgent value_map 匹配产生过滤实体
2. PlannerAgent._fallback_plan() 消费实体过滤生成 WHERE
3. 无 value_map 的普通查询仍正常工作
"""
import asyncio
import unittest


class EntityValueMapFilterTests(unittest.TestCase):
    """Test that EntityAgent properly maps value_map labels to filter entities."""

    def setUp(self):
        from agents.data_agent_v2.entity_agent import EntityAgent
        self.agent = EntityAgent()

    def _make_ctx(self, **kwargs):
        from agents.data_agent_v2.types import CognitiveContext

        defaults = {
            "query": "当前队长的人数是多少",
            "data_source_id": "ds-test",
            "dialect": "postgresql",
            "table_names": ["dim_user"],
            "table_columns": {"dim_user": ["id", "role", "grade_name"]},
            "column_semantics": [
                {
                    "table_name": "dim_user",
                    "column_name": "role",
                    "value_map": {"captain": "队长", "member": "队员"},
                },
                {
                    "table_name": "dim_user",
                    "column_name": "grade_name",
                    "value_map": {},
                },
            ],
            "schema_hint": '{"tables":[{"name":"dim_user","columns":[{"name":"role","comment":"角色"}]}]}',
        }
        defaults.update(kwargs)
        return CognitiveContext(**defaults)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_value_map_match_produces_filter_entity(self):
        """Query containing "队长" should produce entity with mapped_column/mapped_value."""
        ctx = self._make_ctx()

        entities = self._run(self.agent._resolve_entities(ctx))

        filter_entities = [e for e in entities if e.get("source") == "value_map_match"]
        self.assertTrue(len(filter_entities) > 0,
                        f"Expected at least one value_map_match entity, got {entities}")

        captain_entity = [e for e in filter_entities if e.get("mapped_value") == "captain"]
        self.assertEqual(len(captain_entity), 1)
        self.assertEqual(captain_entity[0]["mapped_table"], "dim_user")
        self.assertEqual(captain_entity[0]["mapped_column"], "role")
        self.assertEqual(captain_entity[0]["mapped_value"], "captain")
        self.assertEqual(captain_entity[0]["mapped_value_label"], "队长")
        self.assertGreater(captain_entity[0]["confidence"], 0.9)

    def test_no_value_map_match_when_label_not_in_query(self):
        """Query without value_map labels should not produce filter entities."""
        ctx = self._make_ctx(query="统计各等级的人数")

        entities = self._run(self.agent._resolve_entities(ctx))

        filter_entities = [e for e in entities if e.get("source") == "value_map_match"]
        self.assertEqual(len(filter_entities), 0)

    def test_full_pipeline_no_regression_for_normal_query(self):
        """Normal query without value_map should still resolve entities normally."""
        ctx = self._make_ctx(
            query="查看 dim_user 表的所有数据",
        )

        entities = self._run(self.agent._resolve_entities(ctx))

        # Should have exact match for dim_user
        exact_matches = [e for e in entities if e.get("source") == "exact_match"]
        self.assertTrue(len(exact_matches) > 0)
        self.assertEqual(exact_matches[0]["mapped_table"], "dim_user")


class EntityValueMapBoundaryTests(unittest.TestCase):
    """Boundary condition tests for value_map matching."""

    def setUp(self):
        from agents.data_agent_v2.entity_agent import EntityAgent
        self.agent = EntityAgent()

    def _make_ctx(self, **kwargs):
        from agents.data_agent_v2.types import CognitiveContext

        defaults = {
            "query": "测试查询",
            "data_source_id": "ds-test",
            "dialect": "postgresql",
            "table_names": ["dim_user"],
            "table_columns": {"dim_user": ["id", "status", "label"]},
            "column_semantics": [
                {
                    "table_name": "dim_user",
                    "column_name": "status",
                    "value_map": {"active": "激活", "inactive": "未激活"},
                },
            ],
            "schema_hint": '{"tables":[{"name":"dim_user"}]}',
        }
        defaults.update(kwargs)
        return CognitiveContext(**defaults)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_value_map_with_single_quote_in_value(self):
        """DB value containing single quote is preserved in mapped_value."""
        ctx = self._make_ctx(
            query="查询特殊标签的数据",  # "特殊标签" is the label for O'Brien
            column_semantics=[
                {
                    "table_name": "dim_user",
                    "column_name": "label",
                    "value_map": {"O'Brien": "特殊标签"},
                },
            ],
        )

        entities = self._run(self.agent._resolve_entities(ctx))

        filter_entities = [e for e in entities if e.get("source") == "value_map_match"]
        self.assertTrue(len(filter_entities) > 0,
                        f"Expected value_map match for '特殊标签', got {entities}")
        # The DB value O'Brien (with quote) is preserved in mapped_value
        self.assertEqual(filter_entities[0]["mapped_value"], "O'Brien")

    def test_value_map_no_match_when_label_not_in_query(self):
        """Query without value_map label text should not produce filter entities."""
        ctx = self._make_ctx(
            query="查看各等级和状态的数据",  # does NOT contain "激活" or "待处理"
            column_semantics=[
                {
                    "table_name": "dim_user",
                    "column_name": "grade_name",
                    "value_map": {},
                },
                {
                    "table_name": "dim_user",
                    "column_name": "status",
                    "value_map": {"active": "激活", "pending": "待处理"},
                },
            ],
        )

        entities = self._run(self.agent._resolve_entities(ctx))
        filter_entities = [e for e in entities if e.get("source") == "value_map_match"]
        self.assertEqual(len(filter_entities), 0)

    def test_value_map_empty_value_map(self):
        """Column with empty value_map should not produce matches."""
        ctx = self._make_ctx(
            query="查看激活的数据",
            column_semantics=[
                {
                    "table_name": "dim_user",
                    "column_name": "status",
                    "value_map": None,  # No value_map
                },
            ],
        )

        entities = self._run(self.agent._resolve_entities(ctx))
        filter_entities = [e for e in entities if e.get("source") == "value_map_match"]
        self.assertEqual(len(filter_entities), 0)

    def test_value_map_deduplicate_same_filter(self):
        """Same table+column+value should not produce duplicate filter entities."""
        ctx = self._make_ctx(
            query="激活 激活 激活",  # label appears multiple times
            column_semantics=[
                {
                    "table_name": "dim_user",
                    "column_name": "status",
                    "value_map": {"active": "激活"},
                },
            ],
        )

        entities = self._run(self.agent._resolve_entities(ctx))
        filter_entities = [e for e in entities if e.get("source") == "value_map_match"]
        # Should only have one entry despite "激活" appearing 3 times
        self.assertEqual(len(filter_entities), 1)

    def test_value_map_non_string_values(self):
        """value_map with non-string values should be handled gracefully."""
        ctx = self._make_ctx(
            query="数值为1的数据",
            column_semantics=[
                {
                    "table_name": "dim_user",
                    "column_name": "status",
                    "value_map": {1: "数值为1", 0: "数值为0"},
                },
            ],
        )

        entities = self._run(self.agent._resolve_entities(ctx))
        filter_entities = [e for e in entities if e.get("source") == "value_map_match"]
        self.assertTrue(len(filter_entities) > 0)
        self.assertEqual(filter_entities[0]["mapped_value"], "1")


class PlannerFallbackBoundaryTests(unittest.TestCase):
    """Boundary condition tests for PlannerAgent filter generation."""

    def setUp(self):
        from agents.data_agent_v2.planner_agent import PlannerAgent
        self.agent = PlannerAgent()

    def _make_ctx(self, **kwargs):
        from agents.data_agent_v2.types import CognitiveContext

        defaults = {
            "query": "test query",
            "data_source_id": "ds-test",
            "dialect": "postgresql",
            "table_names": ["dim_user"],
            "table_columns": {"dim_user": ["id", "status"]},
            "entities": [],
            "metrics": [],
            "intent": {"intent_type": "raw_lookup", "confidence": 0.7},
        }
        defaults.update(kwargs)
        return CognitiveContext(**defaults)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_sql_injection_single_quote_escaped(self):
        """Filter value with single quote should be doubled (SQL escaping)."""
        ctx = self._make_ctx(
            entities=[
                {
                    "mention": "特殊标签",
                    "mapped_table": "dim_user",
                    "mapped_column": "status",
                    "mapped_value": "O'Brien",
                    "mapped_value_label": "特殊标签",
                    "confidence": 0.92,
                    "source": "value_map_match",
                },
            ],
        )

        plan = self._run(self.agent._fallback_plan(ctx))
        filters = plan.get("filters", [])
        entity_filters = [f for f in filters if "O''Brien" in f.get("expr", "")]
        self.assertTrue(len(entity_filters) > 0,
                        f"Expected escaped value O''Brien in filter, got: {filters}")

    def test_table_with_spaces_in_name(self):
        """Table name with spaces should have alias from second word."""
        ctx = self._make_ctx(
            table_names=["dim user"],
            entities=[
                {
                    "mention": "队长",
                    "mapped_table": "dim user",
                    "mapped_column": "role",
                    "mapped_value": "captain",
                    "confidence": 0.92,
                    "source": "value_map_match",
                },
            ],
        )

        # _table_alias("dim user") → "user" (second word)
        alias = self.agent._table_alias("dim user")
        self.assertEqual(alias, "user")

    def test_table_alias_single_word(self):
        """Single-word table name should have first-letter alias."""
        alias = self.agent._table_alias("dim_user")
        self.assertEqual(alias, "d")

    def test_table_alias_with_extra_spaces(self):
        """Table name with extra whitespace should still work."""
        alias = self.agent._table_alias("  orders   extra  ")
        self.assertEqual(alias, "extra")  # second word after strip+split


class PlannerFallbackFilterTests(unittest.TestCase):
    """Test that PlannerAgent._fallback_plan() correctly consumes entity filters."""

    def setUp(self):
        from agents.data_agent_v2.planner_agent import PlannerAgent
        self.agent = PlannerAgent()

    def _make_ctx(self, **kwargs):
        from agents.data_agent_v2.types import CognitiveContext

        defaults = {
            "query": "当前队长的人数是多少",
            "data_source_id": "ds-test",
            "dialect": "postgresql",
            "table_names": ["dim_user"],
            "table_columns": {"dim_user": ["id", "role", "grade_name"]},
            "intent": {
                "intent_type": "aggregation",
                "confidence": 0.85,
                "dimensions": [],
                "filters": ["队长"],
            },
            "entities": [
                {
                    "mention": "队长",
                    "mapped_table": "dim_user",
                    "mapped_column": "role",
                    "mapped_value": "captain",
                    "mapped_value_label": "队长",
                    "confidence": 0.92,
                    "source": "value_map_match",
                },
            ],
            "metrics": [],
            "schema_hint": '{"tables":[{"name":"dim_user"}]}',
        }
        defaults.update(kwargs)
        return CognitiveContext(**defaults)

    def _run(self, coro):
        return asyncio.run(coro)

    def test_fallback_plan_includes_entity_filter(self):
        """Entity with mapped_column/mapped_value should become a WHERE filter."""
        ctx = self._make_ctx()

        plan = self._run(self.agent._fallback_plan(ctx))

        filters = plan.get("filters", [])
        entity_filters = [f for f in filters if "captain" in f.get("expr", "")]
        self.assertTrue(len(entity_filters) > 0,
                        f"Expected filter with 'captain', got filters: {filters}")
        # SQLBuilder aliases "dim_user" → "d", so filter should use alias
        self.assertIn("captain", entity_filters[0]["expr"])
        self.assertFalse(entity_filters[0].get("is_having", True))

    def test_fallback_plan_filter_uses_alias(self):
        """Filter expression must use table alias matching SQLBuilder."""
        ctx = self._make_ctx()

        plan = self._run(self.agent._fallback_plan(ctx))

        filters = plan.get("filters", [])
        entity_filters = [f for f in filters if "captain" in f.get("expr", "")]
        expr = entity_filters[0]["expr"]
        # dim_user → alias "d" (first letter, lowercased)
        self.assertIn("d.role", expr)
        self.assertIn("'captain'", expr)

    def test_fallback_plan_table_selection_excludes_filter_entities(self):
        """Filter-type entities (with mapped_column) should not add to tables list."""
        ctx = self._make_ctx()

        plan = self._run(self.agent._fallback_plan(ctx))

        tables = plan.get("tables", [])
        # dim_user should still be in tables (from table_names, not from filter entity)
        self.assertIn("dim_user", tables)

    def test_fallback_plan_all_filter_entities_still_gets_tables(self):
        """When all entities are filter-type, tables still from their mapped_table."""
        ctx = self._make_ctx(
            table_names=[],  # No tables from ctx directly
            entities=[
                {
                    "mention": "队长",
                    "mapped_table": "dim_user",
                    "mapped_column": "role",
                    "mapped_value": "captain",
                    "mapped_value_label": "队长",
                    "confidence": 0.92,
                    "source": "value_map_match",
                },
            ],
        )

        plan = self._run(self.agent._fallback_plan(ctx))

        tables = plan.get("tables", [])
        self.assertIn("dim_user", tables,
                      "Tables should include mapped_table from filter entities when no other tables")

    def test_fallback_plan_without_entity_filters(self):
        """Entity without mapped_column should NOT produce a filter."""
        ctx = self._make_ctx(
            entities=[
                {
                    "mention": "dim_user",
                    "mapped_table": "dim_user",
                    "confidence": 1.0,
                    "source": "exact_match",
                },
            ],
            intent={"intent_type": "raw_lookup", "confidence": 0.7, "filters": []},
        )

        plan = self._run(self.agent._fallback_plan(ctx))

        filters = plan.get("filters", [])
        # No entity-based filters should exist
        non_time_filters = [f for f in filters
                            if not f.get("expr", "").startswith("__TIME_FILTER__")]
        self.assertEqual(len(non_time_filters), 0,
                         f"Expected no entity filters, got: {non_time_filters}")


if __name__ == "__main__":
    unittest.main()
