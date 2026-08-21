from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.base import AgentResult, TaskMessage
from agents.data_agent import DataAgent
from infra.errors import NotFoundException, ValidationException
from infra.storage.models import MetricDefinition, MetricLineage, SchemaMetadata, TableRelationship
from services import sql_assets

SCHEMA_COLUMNS = {
    "orders": ["id", "created_at", "amount", "customer_id"],
    "customers": ["id", "name", "phone"],
}


def test_sql_asset_parser_classifies_read_only_and_etl_without_execution() -> None:
    parsed = sql_assets.parse_sql_assets(
        """
        -- 可发布查询
        SELECT customer_id, SUM(amount) AS revenue
        FROM orders
        GROUP BY customer_id;

        INSERT INTO monthly_orders (customer_id, revenue)
        SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id;
        """,
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )

    assert len(parsed) == 2
    assert parsed[0].asset_type == "query"
    assert parsed[0].executable is True
    assert "--" not in parsed[0].normalized_sql
    assert parsed[1].asset_type == "etl"
    assert parsed[1].executable is False
    assert parsed[1].lineage["write_tables"] == ["monthly_orders"]
    assert "SQLExecutor" not in inspect.getsource(sql_assets.create_sql_asset_source)
    assert "DBRouter" not in inspect.getsource(sql_assets.create_sql_asset_source)


def test_etl_learning_requires_all_tables_to_exist_in_selected_database() -> None:
    table_columns = {
        "orders": ["customer_id", "amount"],
        "monthly_orders": ["customer_id", "revenue"],
    }
    valid = sql_assets.parse_sql_assets(
        """
        INSERT INTO monthly_orders (customer_id, revenue)
        SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id
        """,
        dialect="postgres",
        table_columns=table_columns,
    )[0]
    cross_database = sql_assets.parse_sql_assets(
        """
        INSERT INTO archive.monthly_orders (customer_id, revenue)
        SELECT customer_id, SUM(amount) FROM orders GROUP BY customer_id
        """,
        dialect="postgres",
        table_columns=table_columns,
    )[0]
    missing_source = sql_assets.parse_sql_assets(
        """
        INSERT INTO monthly_orders (customer_id, revenue)
        SELECT customer_id, SUM(amount) FROM missing_orders GROUP BY customer_id
        """,
        dialect="postgres",
        table_columns=table_columns,
    )[0]

    assert valid.asset_type == "etl"
    assert valid.executable is False
    assert valid.validation_report["status"] == "pass"
    assert valid.knowledge_metadata["metric_rules"][0]["source_columns"] == ["orders.amount"]
    assert cross_database.validation_report["status"] == "fail"
    assert "archive.monthly_orders" in "；".join(cross_database.validation_report["errors"])
    assert missing_source.validation_report["status"] == "fail"
    assert "missing_orders" in "；".join(missing_source.validation_report["errors"])


def test_sql_asset_parser_extracts_structured_and_narrative_comments() -> None:
    parsed = sql_assets.parse_sql_assets(
        """
        -- @title: 按渠道统计净收入
        -- @description: 支付金额扣除退款金额
        -- 仅统计支付成功订单
        -- @questions: 各渠道收入是多少；渠道 GMV 趋势
        -- @tags: 订单, 渠道, 收入
        -- @metrics: 净收入=SUM(orders.amount-refunds.amount)
        -- @dimensions: 渠道=channels.name
        -- @joins: orders.channel_id=channels.id;orders.id=refunds.order_id
        -- @time-column: orders.paid_at
        -- @grain: day
        SELECT channels.name, SUM(orders.amount) AS revenue
        FROM orders
        LEFT JOIN channels ON orders.channel_id = channels.id
        GROUP BY channels.name;
        """,
        dialect="postgres",
        table_columns={
            **SCHEMA_COLUMNS,
            "channels": ["id", "name"],
        },
    )[0]

    assert parsed.title == "按渠道统计净收入"
    assert "支付成功" in parsed.description
    assert parsed.tags == ["订单", "渠道", "收入"]
    assert parsed.knowledge_metadata["questions"] == ["各渠道收入是多少", "渠道 GMV 趋势"]
    assert parsed.knowledge_metadata["metrics"][0]["name"] == "净收入"
    assert {"name": "渠道", "table": "channels", "column": "name"} in (
        parsed.knowledge_metadata["dimensions"]
    )
    assert len(parsed.knowledge_metadata["joins"]) == 2
    assert parsed.knowledge_metadata["time_columns"] == ["orders.paid_at"]
    assert parsed.knowledge_metadata["grain"] == "day"
    assert "@title" not in parsed.normalized_sql


def test_sql_asset_parser_keeps_plain_comments_as_business_description() -> None:
    parsed = sql_assets.parse_sql_assets(
        "-- 订单收入业务口径\n-- 排除测试订单\nSELECT amount FROM orders",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]

    assert parsed.description == "订单收入业务口径\n排除测试订单"


def test_sql_asset_parser_infers_inner_join_and_aggregate_knowledge() -> None:
    parsed = sql_assets.parse_sql_assets(
        """
        SELECT customers.name, SUM(orders.amount) AS revenue
        FROM orders
        JOIN customers ON orders.customer_id = customers.id
        GROUP BY customers.name
        """,
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]

    assert parsed.knowledge_metadata["joins"][0]["join_type"] == "INNER"
    assert {"name": "revenue", "formula": "SUM(orders.amount)"} in (
        parsed.knowledge_metadata["metrics"]
    )
    cte = sql_assets.parse_sql_assets(
        """
        WITH scoped AS (
            SELECT o.amount, o.customer_id FROM orders AS o
        )
        SELECT SUM(scoped.amount) AS revenue
        FROM scoped
        GROUP BY scoped.customer_id
        """,
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    assert cte.knowledge_metadata["metric_rules"][0]["source_columns"] == ["orders.amount"]
    assert cte.knowledge_metadata["metric_rules"][0]["source_tables"] == ["orders"]


def test_sql_asset_parser_extracts_metric_rules_without_losing_legacy_metric_shape() -> None:
    parsed = sql_assets.parse_sql_assets(
        """
        SELECT channel_id,
               SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END) AS revenue
        FROM orders
        WHERE is_test = false
        GROUP BY channel_id
        """,
        dialect="postgres",
        table_columns={"orders": ["channel_id", "status", "amount", "is_test"]},
    )[0]

    assert parsed.knowledge_metadata["metrics"] == [
        {
            "name": "revenue",
            "formula": "SUM(CASE WHEN status = 'paid' THEN amount ELSE 0 END)",
        }
    ]
    rule = parsed.knowledge_metadata["metric_rules"][0]
    assert rule["aggregation"] == "SUM"
    assert rule["source_columns"] == ["orders.amount", "orders.status"]
    assert "is_test = FALSE" in rule["filters"]
    assert "status = 'paid'" in rule["filters"]
    assert rule["grain"] == "channel_id"


def test_sql_asset_parser_rejects_unknown_and_sensitive_columns() -> None:
    unknown = sql_assets.parse_sql_assets(
        "SELECT missing FROM orders",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    sensitive = sql_assets.parse_sql_assets(
        "SELECT phone FROM customers",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
        sensitive_columns={("customers", "phone")},
    )[0]
    star = sql_assets.parse_sql_assets(
        "SELECT * FROM customers",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
        sensitive_columns={("customers", "phone")},
    )[0]

    assert unknown.executable is False
    assert "不存在列" in unknown.validation_report["errors"][0]
    assert sensitive.executable is False
    assert "敏感字段" in sensitive.validation_report["errors"][0]
    assert star.executable is False
    assert "SELECT *" in star.validation_report["errors"][0]


def test_sql_asset_parser_supports_clickhouse_cross_database_tables() -> None:
    qualified = sql_assets.parse_sql_assets(
        "SELECT id FROM ods.orders",
        dialect="clickhouse",
        table_columns={"ods.orders": ["id", "created_at"]},
    )[0]
    ambiguous = sql_assets.parse_sql_assets(
        "SELECT id FROM orders",
        dialect="clickhouse",
        table_columns={"ods.orders": ["id"], "dwd.orders": ["id"]},
    )[0]

    assert qualified.executable is True
    assert ambiguous.executable is False
    assert "使用 database.table" in ambiguous.validation_report["errors"][0]


def test_sql_asset_parser_checks_unqualified_join_columns() -> None:
    sensitive = sql_assets.parse_sql_assets(
        "SELECT phone FROM customers JOIN orders ON customers.id = orders.customer_id",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
        sensitive_columns={("customers", "phone")},
    )[0]
    unknown = sql_assets.parse_sql_assets(
        "SELECT missing FROM customers JOIN orders ON customers.id = orders.customer_id",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    ambiguous = sql_assets.parse_sql_assets(
        "SELECT id FROM customers JOIN orders ON customers.id = orders.customer_id",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]

    assert sensitive.executable is False
    assert "敏感字段" in "；".join(sensitive.validation_report["errors"])
    assert unknown.executable is False
    assert "不存在列" in "；".join(unknown.validation_report["errors"])
    assert ambiguous.executable is False
    assert "歧义" in "；".join(ambiguous.validation_report["errors"])


def test_sql_asset_parser_checks_cte_and_derived_table_columns() -> None:
    cte_unknown = sql_assets.parse_sql_assets(
        "WITH customer_ids AS (SELECT id FROM customers) SELECT phone FROM customer_ids",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    derived_unknown = sql_assets.parse_sql_assets(
        "SELECT scoped.phone FROM (SELECT id FROM customers) AS scoped",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    cte_sensitive = sql_assets.parse_sql_assets(
        "WITH customer_phones AS (SELECT phone FROM customers) SELECT phone FROM customer_phones",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
        sensitive_columns={("customers", "phone")},
    )[0]

    assert cte_unknown.executable is False
    assert "不存在列" in "；".join(cte_unknown.validation_report["errors"])
    assert derived_unknown.executable is False
    assert "不存在列" in "；".join(derived_unknown.validation_report["errors"])
    assert cte_sensitive.executable is False
    assert "customers.phone" in "；".join(cte_sensitive.validation_report["errors"])


def test_sql_asset_parser_accepts_select_aliases_and_valid_derived_columns() -> None:
    select_alias = sql_assets.parse_sql_assets(
        "SELECT amount AS total FROM orders ORDER BY total",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    derived = sql_assets.parse_sql_assets(
        "SELECT scoped.id FROM (SELECT id FROM customers) AS scoped",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    cte_star = sql_assets.parse_sql_assets(
        "WITH customer_ids AS (SELECT id FROM customers) SELECT * FROM customer_ids",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
        sensitive_columns={("customers", "phone")},
    )[0]
    shadowed_alias = sql_assets.parse_sql_assets(
        """
        SELECT scoped.amount
        FROM orders AS scoped
        WHERE EXISTS (SELECT 1 FROM customers AS scoped WHERE scoped.id > 0)
        """,
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
        sensitive_columns={("orders", "id")},
    )[0]

    assert select_alias.executable is True
    assert derived.executable is True
    assert cte_star.executable is True
    assert shadowed_alias.executable is True


def test_sql_asset_parser_warns_when_known_table_has_no_column_metadata() -> None:
    parsed = sql_assets.parse_sql_assets(
        "SELECT id FROM orders",
        dialect="postgres",
        table_columns={"orders": []},
    )[0]

    assert parsed.executable is True
    assert "跳过字段级静态校验" in "；".join(parsed.validation_report["warnings"])

    sensitive = sql_assets.parse_sql_assets(
        "SELECT phone FROM customers",
        dialect="postgres",
        table_columns={"customers": []},
        sensitive_columns={("customers", "phone")},
    )[0]
    sensitive_star = sql_assets.parse_sql_assets(
        "SELECT * FROM customers",
        dialect="postgres",
        table_columns={"customers": []},
        sensitive_columns={("customers", "phone")},
    )[0]

    assert sensitive.executable is False
    assert "敏感字段" in "；".join(sensitive.validation_report["errors"])
    assert sensitive_star.executable is False
    assert "SELECT *" in "；".join(sensitive_star.validation_report["errors"])


def test_sql_candidate_never_silently_discards_multiple_statements() -> None:
    statements = sql_assets._split_sql_statements(
        "SELECT id FROM orders; SELECT name FROM customers;",
        dialect="postgres",
    )
    assert len(statements) == 2
    with pytest.raises(sql_assets.SQLValidationError, match="exactly one statement"):
        sql_assets._validated_candidate(
            "SELECT id FROM orders; SELECT name FROM customers;",
            dialect="postgres",
            table_columns=SCHEMA_COLUMNS,
            sensitive_columns=set(),
        )


def test_sql_asset_normalization_provides_stable_dedup_hash() -> None:
    first = sql_assets.parse_sql_assets(
        "SELECT id FROM orders",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    second = sql_assets.parse_sql_assets(
        "-- comment\n select id from orders;",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]

    assert first.sql_hash == second.sql_hash


def test_sql_asset_ast_structure_hash_deduplicates_literals_and_marks_risks() -> None:
    first = sql_assets.parse_sql_assets(
        "SELECT id FROM orders WHERE customer_id = 100 AND created_at >= '2026-01-01'",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    second = sql_assets.parse_sql_assets(
        "SELECT id FROM orders WHERE customer_id = 200 AND created_at >= '2026-08-01'",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]

    assert first.sql_hash != second.sql_hash
    assert first.structure_hash == second.structure_hash
    assert {"hardcoded_id", "hardcoded_date", "missing_limit"}.issubset(first.risk_flags)
    aggregate = sql_assets.parse_sql_assets(
        "SELECT COUNT(*) AS total FROM orders",
        dialect="postgres",
        table_columns=SCHEMA_COLUMNS,
    )[0]
    assert "select_star" not in aggregate.risk_flags
    create_source = inspect.getsource(sql_assets.create_sql_asset_source)
    assert "SQLAsset.structure_hash.in_" in create_source
    assert '"structure_duplicate_count"' in create_source


def test_query_plan_uses_governed_asset_knowledge_and_can_request_clarification() -> None:
    asset = SimpleNamespace(
        id="asset-1",
        domain="订单",
        tables=["orders", "channels"],
        columns=["orders.amount", "channels.name"],
        knowledge_metadata={
            "metrics": [{"name": "净收入", "formula": "SUM(orders.amount)"}],
            "dimensions": [{"name": "渠道", "table": "channels", "column": "name"}],
            "filters": ["orders.status='paid'"],
            "assumptions": ["按支付时间统计"],
            "joins": [
                {
                    "left_table": "orders",
                    "left_column": "channel_id",
                    "right_table": "channels",
                    "right_column": "id",
                }
            ],
        },
    )

    plan = sql_assets.build_query_plan("最近30天各渠道净收入", [asset])
    ambiguous = sql_assets.build_query_plan("查询收入", [])

    assert plan["needs_clarification"] is False
    assert plan["metrics"] == ["净收入"]
    assert plan["dimensions"] == ["渠道"]
    assert plan["time_range"] == {"type": "last_n", "value": 30, "unit": "天"}
    assert plan["joins"] == ["orders.channel_id=channels.id"]
    assert plan["filters"] == []
    assert plan["available_filters"] == ["orders.status='paid'"]
    explicit = sql_assets.build_query_plan("最近30天 orders.status='paid' 各渠道净收入", [asset])
    assert explicit["filters"] == ["orders.status='paid'"]
    assert ambiguous["needs_clarification"] is True
    assert "收入" in ambiguous["clarification_question"]


def test_query_plan_combines_multiple_metric_contracts_and_required_filters() -> None:
    revenue_asset = SimpleNamespace(
        id="asset-revenue",
        domain="订单",
        tables=["orders"],
        columns=["orders.amount", "orders.status", "orders.is_test"],
        knowledge_metadata={
            "metrics": [{"name": "净收入", "formula": "SUM(orders.amount)"}],
            "metric_rules": [
                {
                    "name": "净收入",
                    "formula": "SUM(orders.amount)",
                    "aggregation": "SUM",
                    "source_columns": ["orders.amount"],
                    "source_tables": ["orders"],
                    "filters": ["orders.status = 'paid'", "orders.is_test = FALSE"],
                    "filter_contracts": [
                        {
                            "expression": "orders.status = 'paid'",
                            "policy": "required",
                            "source": "where",
                        },
                        {
                            "expression": "orders.is_test = FALSE",
                            "policy": "required",
                            "source": "where",
                        },
                    ],
                    "grain": "day",
                }
            ],
        },
    )
    count_asset = SimpleNamespace(
        id="asset-count",
        domain="订单",
        tables=["orders"],
        columns=["orders.id"],
        knowledge_metadata={
            "metrics": [{"name": "支付订单数", "formula": "COUNT(DISTINCT orders.id)"}],
            "metric_rules": [
                {
                    "name": "支付订单数",
                    "formula": "COUNT(DISTINCT orders.id)",
                    "aggregation": "COUNT",
                    "source_columns": ["orders.id"],
                    "source_tables": ["orders"],
                    "filters": [],
                    "filter_contracts": [],
                    "grain": "day",
                }
            ],
        },
    )

    plan = sql_assets.build_query_plan("最近30天净收入和支付订单数", [revenue_asset, count_asset])

    assert plan["metrics"] == ["净收入", "支付订单数"]
    assert {item["source_asset_id"] for item in plan["metric_contracts"]} == {
        "asset-revenue",
        "asset-count",
    }
    assert all(item["enforcement"] == "required" for item in plan["metric_contracts"])
    assert plan["required_filters"] == [
        "orders.status = 'paid'",
        "orders.is_test = FALSE",
    ]
    assert plan["filters"] == plan["required_filters"]


def test_query_plan_prefers_published_metric_definition_over_asset_variant() -> None:
    asset = SimpleNamespace(
        id="asset-revenue",
        domain="订单",
        tables=["orders"],
        columns=["orders.amount"],
        knowledge_metadata={
            "metrics": [{"name": "净收入", "formula": "SUM(orders.amount)"}],
            "metric_rules": [
                {
                    "name": "净收入",
                    "formula": "SUM(orders.amount)",
                    "source_columns": ["orders.amount"],
                    "source_tables": ["orders"],
                }
            ],
        },
    )
    governed = SimpleNamespace(
        id="metric-1",
        name="净收入",
        aliases=["实收"],
        formula="SUM(orders.amount - orders.refund_amount)",
        underlying_columns=["orders.amount", "orders.refund_amount"],
        agg_function="SUM",
    )

    plan = sql_assets.build_query_plan("查询实收", [asset], governed_metrics=[governed])

    assert plan["metrics"] == ["净收入"]
    assert plan["metric_contracts"][0]["formula"] == ("SUM(orders.amount - orders.refund_amount)")
    assert plan["metric_contracts"][0]["source_metric_id"] == "metric-1"
    assert plan["metric_contracts"][0]["enforcement"] == "required"


def test_metric_contract_coverage_rejects_incomplete_candidate() -> None:
    contracts = [
        {
            "name": "净收入",
            "formula": "SUM(orders.amount)",
            "source_columns": ["orders.amount"],
            "source_tables": ["orders"],
            "filter_contracts": [
                {
                    "expression": "orders.status = 'paid'",
                    "policy": "required",
                    "source": "where",
                }
            ],
            "enforcement": "required",
        },
        {
            "name": "支付订单数",
            "formula": "COUNT(DISTINCT orders.id)",
            "source_columns": ["orders.id"],
            "source_tables": ["orders"],
            "filter_contracts": [],
            "enforcement": "required",
        },
    ]
    complete = sql_assets._validate_metric_contract_coverage(
        """
        SELECT SUM(o.amount) AS revenue, COUNT(DISTINCT o.id) AS order_count
        FROM orders AS o
        WHERE o.status = 'paid'
        LIMIT 100
        """,
        dialect="postgres",
        metric_contracts=contracts,
    )
    incomplete = sql_assets._validate_metric_contract_coverage(
        "SELECT SUM(amount) AS revenue, COUNT(*) AS order_count FROM orders LIMIT 100",
        dialect="postgres",
        metric_contracts=contracts,
    )
    wrong_source = sql_assets._validate_metric_contract_coverage(
        """
        SELECT SUM(refunds.amount) AS revenue, COUNT(DISTINCT orders.id) AS order_count
        FROM orders JOIN refunds ON orders.id = refunds.order_id
        WHERE orders.status = 'paid'
        LIMIT 100
        """,
        dialect="postgres",
        metric_contracts=contracts,
    )
    qualified_contract = {
        **contracts[0],
        "source_tables": ["ods.orders"],
        "source_columns": ["ods.orders.amount"],
        "filter_contracts": [],
    }
    wrong_database = sql_assets._validate_metric_contract_coverage(
        "SELECT SUM(amount) FROM dwd.orders LIMIT 100",
        dialect="clickhouse",
        metric_contracts=[qualified_contract],
    )

    assert complete["status"] == "pass"
    assert complete["covered_metrics"] == ["净收入", "支付订单数"]
    assert incomplete["status"] == "fail"
    assert any("支付订单数" in error and "指标公式" in error for error in incomplete["errors"])
    assert any("固有过滤" in error for error in incomplete["errors"])
    assert any("orders.amount" in error for error in wrong_source["errors"])
    assert any("ods.orders" in error for error in wrong_database["errors"])


def test_schema_fingerprint_only_tracks_query_relevant_structure() -> None:
    original = {
        "schema": "public",
        "table_count": 1,
        "synced_at": 1,
        "tables": [
            {
                "name": "orders",
                "comment": "旧描述",
                "columns": [
                    {"name": "id", "type": "BIGINT", "comment": "主键"},
                    {"name": "amount", "type": "DECIMAL(12, 2)"},
                ],
            }
        ],
    }
    metadata_only_change = {
        **original,
        "table_count": 99,
        "synced_at": 999,
        "tables": [
            {
                "name": "orders",
                "comment": "新描述",
                "columns": [
                    {"name": "amount", "type": "decimal(12,2)", "comment": "金额"},
                    {"name": "id", "type": "bigint", "comment": "订单主键"},
                ],
            }
        ],
    }
    structural_change = {
        **metadata_only_change,
        "tables": [
            {
                "name": "orders",
                "columns": [
                    {"name": "id", "type": "bigint"},
                    {"name": "total_amount", "type": "decimal(12,2)"},
                ],
            }
        ],
    }

    assert sql_assets.schema_fingerprint(original) == sql_assets.schema_fingerprint(
        metadata_only_change
    )
    assert sql_assets.schema_fingerprint(original) != sql_assets.schema_fingerprint(
        structural_change
    )
    assert sql_assets.schema_fingerprint(original, {("orders", "amount")}) != (
        sql_assets.schema_fingerprint(original)
    )


def test_result_rows_are_bounded_by_storage_budget() -> None:
    rows = [{"id": index, "payload": "x" * 128} for index in range(10)]

    bounded, truncated = sql_assets._bounded_result_rows(rows, max_bytes=350)

    assert 0 < len(bounded) < len(rows)
    assert truncated is True
    assert len(str(bounded).encode("utf-8")) < 500


def test_sql_asset_status_transitions_are_governed() -> None:
    sql_assets.validate_asset_status_transition("draft", "published")
    sql_assets.validate_asset_status_transition("published", "deprecated")
    sql_assets.validate_asset_status_transition("deprecated", "published")

    with pytest.raises(ValidationException, match="状态不能从 published 变更为 rejected"):
        sql_assets.validate_asset_status_transition("published", "rejected")


@pytest.mark.asyncio
async def test_published_sql_asset_promotes_reviewable_knowledge_candidates(monkeypatch) -> None:
    asset = SimpleNamespace(
        id="asset-1",
        data_source_id="source-1",
        description="订单收入口径",
        tags=["订单", "收入"],
        schema_fingerprint="fingerprint-1",
        knowledge_metadata={
            "metrics": [{"name": "净收入", "formula": "SUM(orders.amount)"}],
            "dimensions": [{"name": "渠道", "table": "orders", "column": "channel_id"}],
            "joins": [
                {
                    "left_table": "orders",
                    "left_column": "customer_id",
                    "right_table": "customers",
                    "right_column": "id",
                    "join_type": "LEFT",
                }
            ],
            "time_columns": ["orders.paid_at"],
            "grain": "day",
        },
    )
    monkeypatch.setattr(
        sql_assets,
        "load_schema_inspection",
        AsyncMock(
            return_value=SimpleNamespace(
                column_map={
                    "orders": ["amount", "channel_id", "customer_id", "paid_at"],
                    "customers": ["id"],
                }
            )
        ),
    )

    class _DB:
        def __init__(self):
            self.added = []

        async def scalar(self, _statement):
            return None

        def add(self, record):
            self.added.append(record)

    db = _DB()
    stats = await sql_assets.promote_sql_asset_knowledge(db, asset=asset, user_id="user-1")

    assert stats == {
        "metrics_created": 1,
        "relationships_created": 1,
        "annotations_suggested": 2,
    }
    metric = next(item for item in db.added if isinstance(item, MetricDefinition))
    lineage = next(item for item in db.added if isinstance(item, MetricLineage))
    relationship = next(item for item in db.added if isinstance(item, TableRelationship))
    annotations = [item for item in db.added if isinstance(item, SchemaMetadata)]
    assert metric.status == "draft"
    assert metric.formula == "SUM(orders.amount)"
    assert lineage.metric_id == metric.id
    assert lineage.depends_on_column == "orders.amount"
    assert lineage.lineage_type == "sql_asset_inferred"
    assert relationship.is_verified is False
    assert {item.column_name for item in annotations} == {"channel_id", "paid_at"}
    assert all(item.annotation_status == "suggested" for item in annotations)


@pytest.mark.asyncio
async def test_quarantined_etl_learns_reviewable_knowledge_once(monkeypatch) -> None:
    valid = SimpleNamespace(
        id="etl-valid",
        asset_type="etl",
        corpus_role="quarantine",
        executable=False,
        validation_report={"status": "pass"},
        verification_metadata={},
    )
    invalid = SimpleNamespace(
        id="etl-invalid",
        asset_type="etl",
        corpus_role="quarantine",
        executable=False,
        validation_report={"status": "fail"},
        verification_metadata={},
    )
    promote = AsyncMock(
        return_value={
            "metrics_created": 2,
            "relationships_created": 1,
            "annotations_suggested": 3,
        }
    )
    monkeypatch.setattr(sql_assets, "promote_sql_asset_knowledge", promote)

    first = await sql_assets.learn_quarantined_etl_assets(
        SimpleNamespace(), assets=[valid, invalid], user_id="user-1"
    )
    second = await sql_assets.learn_quarantined_etl_assets(
        SimpleNamespace(), assets=[valid, invalid], user_id="user-1"
    )

    assert first == {
        "assets_learned": 1,
        "metrics_created": 2,
        "relationships_created": 1,
        "annotations_suggested": 3,
    }
    assert second == {
        "assets_learned": 0,
        "metrics_created": 0,
        "relationships_created": 0,
        "annotations_suggested": 0,
    }
    promote.assert_awaited_once()
    assert valid.verification_metadata["knowledge_learning_mode"] == "etl_read_only_extract"
    assert invalid.verification_metadata == {}


@pytest.mark.asyncio
async def test_duplicate_upload_is_serialized_and_scoped_to_global_assets() -> None:
    existing = SimpleNamespace(id="source-existing")

    class EmptyResult:
        @staticmethod
        def scalars():
            return SimpleNamespace(all=lambda: [])

    class CaptureDB:
        def __init__(self) -> None:
            self.scalar_statements = []

        async def scalar(self, statement):
            self.scalar_statements.append(statement)
            return None if len(self.scalar_statements) == 1 else existing

        async def execute(self, statement):
            return EmptyResult()

    db = CaptureDB()
    source, assets, deduplicated = await sql_assets.create_sql_asset_source(
        db,
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        data_source_id="source-1",
        filename="orders.sql",
        content_type="application/sql",
        source_text="SELECT id FROM orders",
        dialect="postgres",
    )

    assert source is existing
    assert assets == []
    assert deduplicated is True
    assert "FOR UPDATE" in str(db.scalar_statements[0])
    assert "sql_asset_sources.workspace_id" in str(db.scalar_statements[1])


@pytest.mark.asyncio
async def test_data_agent_online_entry_always_generates_governed_draft(monkeypatch) -> None:
    expected = AgentResult(
        task_id="task-1",
        agent_type="data",
        status="success",
        content="draft",
    )
    generate = AsyncMock(return_value=expected)
    monkeypatch.setattr(DataAgent, "_generate_sql_draft", generate)
    result = await DataAgent().execute(
        TaskMessage(
            task_id="task-1",
            agent_type="data",
            query="查询订单",
            user_id="user-1",
            params={"generation_only": True},
        )
    )

    assert result is expected
    generate.assert_awaited_once()


def _draft(*, fingerprint: str) -> SimpleNamespace:
    return SimpleNamespace(
        id="draft-1",
        user_id="user-1",
        tenant_id="tenant-1",
        workspace_id="workspace-1",
        project_id=None,
        conversation_id=None,
        response_id=None,
        data_source_id="source-1",
        question="订单统计",
        group_type="batch",
        status="awaiting_confirmation",
        dialect="postgres",
        schema_fingerprint=fingerprint,
        selected_candidate_ids=[],
        execution_summary={},
        execution_started_at=None,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_at=datetime.now(UTC),
    )


def _candidate(candidate_id: str, sql: str, position: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=candidate_id,
        draft_id="draft-1",
        position=position,
        title=f"SQL 方案 {position}",
        description="test",
        sql=sql,
        sql_hash=sql_assets._hash_text(sql),
        asset_ids=[],
        tables=["orders"],
        columns=["id"],
        assumptions=[],
        validation_report={"status": "pass"},
        selected=False,
        execution_status="pending",
        result_rows=[],
        row_count=0,
        error_message=None,
        executed_at=None,
    )


async def _patch_execution_scope(monkeypatch, draft, candidates, schema_payload) -> None:
    monkeypatch.setattr(
        sql_assets,
        "load_scoped_draft",
        AsyncMock(return_value=(draft, candidates)),
    )
    monkeypatch.setattr(
        sql_assets,
        "get_accessible_data_source",
        AsyncMock(
            return_value=SimpleNamespace(
                id="source-1",
                source_type="postgres",
                host="db",
                port=5432,
                database="app",
                username="reader",
                password_encrypted="encrypted",
            )
        ),
    )
    monkeypatch.setattr(
        sql_assets,
        "load_schema_inspection",
        AsyncMock(
            return_value=SimpleNamespace(
                schema_payload=schema_payload,
                column_map=SCHEMA_COLUMNS,
            )
        ),
    )
    monkeypatch.setattr(sql_assets, "_sensitive_columns", AsyncMock(return_value=set()))


@pytest.mark.asyncio
async def test_draft_execution_rejects_schema_drift_before_executor(monkeypatch) -> None:
    original_schema = {"tables": [{"name": "orders"}]}
    current_schema = {"tables": [{"name": "orders"}, {"name": "customers"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(original_schema))
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    await _patch_execution_scope(monkeypatch, draft, [candidate], current_schema)
    executor = MagicMock()
    monkeypatch.setattr(sql_assets, "SQLExecutor", executor)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(ValidationException, match="Schema 已变化"):
        await sql_assets.execute_sql_query_draft(
            db,
            draft_id=draft.id,
            user_id=draft.user_id,
            tenant_id=draft.tenant_id,
            workspace_id=draft.workspace_id,
            candidate_ids=[candidate.id],
        )

    executor.assert_not_called()


@pytest.mark.asyncio
async def test_draft_execution_rejects_tampered_sql_hash(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    candidate.sql = "SELECT amount FROM orders LIMIT 100"
    await _patch_execution_scope(monkeypatch, draft, [candidate], schema)
    monkeypatch.setattr(sql_assets, "_sensitive_columns", AsyncMock(return_value=set()))
    executor = MagicMock()
    monkeypatch.setattr(sql_assets, "SQLExecutor", executor)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(ValidationException, match="完整性校验失败"):
        await sql_assets.execute_sql_query_draft(
            db,
            draft_id=draft.id,
            user_id=draft.user_id,
            tenant_id=draft.tenant_id,
            workspace_id=draft.workspace_id,
            candidate_ids=[candidate.id],
        )

    executor.assert_not_called()


@pytest.mark.asyncio
async def test_batch_execution_records_partial_failure(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    candidates = [
        _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1),
        _candidate("candidate-2", "SELECT amount FROM orders LIMIT 100", 2),
    ]
    await _patch_execution_scope(monkeypatch, draft, candidates, schema)
    monkeypatch.setattr(sql_assets, "_sensitive_columns", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        sql_assets,
        "_validated_candidate",
        MagicMock(return_value=("sql", {"status": "pass"}, ["orders"], ["id"])),
    )
    monkeypatch.setattr(sql_assets, "decrypt_data_source_secret", MagicMock(return_value="pw"))
    router = MagicMock()
    router.build_dsn.return_value = "postgresql+asyncpg://reader:pw@db/app"
    monkeypatch.setattr(sql_assets, "DBRouter", MagicMock(return_value=router))
    executor = MagicMock()
    executor.run_on_dsn = AsyncMock(side_effect=[[{"id": 1}], RuntimeError("timeout")])
    monkeypatch.setattr(sql_assets, "SQLExecutor", MagicMock(return_value=executor))
    db = SimpleNamespace(commit=AsyncMock())

    result = await sql_assets.execute_sql_query_draft(
        db,
        draft_id=draft.id,
        user_id=draft.user_id,
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        execute_all=True,
    )

    assert result["status"] == "partially_failed"
    assert result["execution_summary"]["requested"] == 2
    assert result["execution_summary"]["succeeded"] == 1
    assert result["execution_summary"]["failed"] == 1
    assert candidates[0].execution_status == "completed"
    assert candidates[1].execution_status == "failed"
    assert candidates[1].error_message == "timeout"


@pytest.mark.asyncio
async def test_completed_candidate_is_idempotent_and_not_executed_again(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    draft.status = "completed"
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    candidate.execution_status = "completed"
    candidate.result_rows = [{"id": 1}]
    candidate.row_count = 1
    draft.selected_candidate_ids = [candidate.id]
    await _patch_execution_scope(monkeypatch, draft, [candidate], schema)
    monkeypatch.setattr(sql_assets, "decrypt_data_source_secret", MagicMock(return_value="pw"))
    executor = MagicMock()
    monkeypatch.setattr(sql_assets, "SQLExecutor", executor)
    db = SimpleNamespace(commit=AsyncMock())

    result = await sql_assets.execute_sql_query_draft(
        db,
        draft_id=draft.id,
        user_id=draft.user_id,
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        candidate_ids=[candidate.id],
    )

    assert result["status"] == "completed"
    assert result["candidates"][0]["rows"] == [{"id": 1}]
    executor.assert_not_called()


@pytest.mark.asyncio
async def test_failed_candidate_requires_explicit_retry_and_can_succeed(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    draft.status = "failed"
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    candidate.execution_status = "failed"
    candidate.error_message = "timeout"
    draft.selected_candidate_ids = [candidate.id]
    await _patch_execution_scope(monkeypatch, draft, [candidate], schema)
    monkeypatch.setattr(sql_assets, "_sensitive_columns", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        sql_assets,
        "_validated_candidate",
        MagicMock(return_value=("sql", {"status": "pass"}, ["orders"], ["id"])),
    )
    monkeypatch.setattr(sql_assets, "decrypt_data_source_secret", MagicMock(return_value="pw"))
    router = MagicMock()
    router.build_dsn.return_value = "postgresql+asyncpg://reader:pw@db/app"
    monkeypatch.setattr(sql_assets, "DBRouter", MagicMock(return_value=router))
    executor = MagicMock()
    executor.run_on_dsn = AsyncMock(return_value=[{"id": 1}])
    monkeypatch.setattr(sql_assets, "SQLExecutor", MagicMock(return_value=executor))
    db = SimpleNamespace(commit=AsyncMock())

    unchanged = await sql_assets.execute_sql_query_draft(
        db,
        draft_id=draft.id,
        user_id=draft.user_id,
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        candidate_ids=[candidate.id],
    )
    assert unchanged["candidates"][0]["execution_status"] == "failed"
    executor.run_on_dsn.assert_not_awaited()

    retried = await sql_assets.execute_sql_query_draft(
        db,
        draft_id=draft.id,
        user_id=draft.user_id,
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        candidate_ids=[candidate.id],
        retry_failed=True,
    )

    assert retried["status"] == "completed"
    assert retried["candidates"][0]["execution_status"] == "completed"
    assert retried["candidates"][0]["rows"] == [{"id": 1}]
    executor.run_on_dsn.assert_awaited_once()


@pytest.mark.asyncio
async def test_executing_draft_rejects_concurrent_execution(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    draft.status = "executing"
    draft.execution_started_at = datetime.now(UTC)
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    candidate.execution_status = "executing"
    await _patch_execution_scope(monkeypatch, draft, [candidate], schema)
    executor = MagicMock()
    monkeypatch.setattr(sql_assets, "SQLExecutor", executor)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(ValidationException, match="正在执行"):
        await sql_assets.execute_sql_query_draft(
            db,
            draft_id=draft.id,
            user_id=draft.user_id,
            tenant_id=draft.tenant_id,
            workspace_id=draft.workspace_id,
            candidate_ids=[candidate.id],
        )

    executor.assert_not_called()


@pytest.mark.asyncio
async def test_stale_executing_draft_requires_reconciliation_without_retry(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    draft.status = "executing"
    draft.execution_started_at = (
        datetime.now(UTC) - sql_assets.EXECUTION_STALE_AFTER - timedelta(seconds=1)
    )
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    candidate.execution_status = "executing"
    await _patch_execution_scope(monkeypatch, draft, [candidate], schema)
    monkeypatch.setattr(sql_assets, "_sensitive_columns", AsyncMock(return_value=set()))
    monkeypatch.setattr(
        sql_assets,
        "_validated_candidate",
        MagicMock(return_value=("sql", {"status": "pass"}, ["orders"], ["id"])),
    )
    monkeypatch.setattr(sql_assets, "decrypt_data_source_secret", MagicMock(return_value="pw"))
    router = MagicMock()
    router.build_dsn.return_value = "postgresql+asyncpg://reader:pw@db/app"
    monkeypatch.setattr(sql_assets, "DBRouter", MagicMock(return_value=router))
    executor = MagicMock()
    executor.run_on_dsn = AsyncMock(return_value=[{"id": 1}])
    monkeypatch.setattr(sql_assets, "SQLExecutor", MagicMock(return_value=executor))
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(ValidationException, match="结果未知") as exc_info:
        await sql_assets.execute_sql_query_draft(
            db,
            draft_id=draft.id,
            user_id=draft.user_id,
            tenant_id=draft.tenant_id,
            workspace_id=draft.workspace_id,
            candidate_ids=[candidate.id],
        )

    assert exc_info.value.details["requires_reconciliation"] is True
    assert draft.status == "requires_reconciliation"
    assert draft.execution_summary["reconciliation_count"] == 1
    assert draft.execution_summary["unknown_candidate_ids"] == [candidate.id]
    assert candidate.execution_status == "unknown"
    executor.run_on_dsn.assert_not_awaited()
    db.commit.assert_awaited_once()

    with pytest.raises(ValidationException, match="不会自动重试"):
        await sql_assets.execute_sql_query_draft(
            db,
            draft_id=draft.id,
            user_id=draft.user_id,
            tenant_id=draft.tenant_id,
            workspace_id=draft.workspace_id,
            candidate_ids=[candidate.id],
            retry_failed=True,
        )
    executor.run_on_dsn.assert_not_awaited()


@pytest.mark.asyncio
async def test_draft_execution_uses_workspace_scope(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    await _patch_execution_scope(monkeypatch, draft, [candidate], schema)
    monkeypatch.setattr(sql_assets, "decrypt_data_source_secret", MagicMock(return_value="pw"))
    executor = MagicMock()
    executor.run_on_dsn = AsyncMock(return_value=[{"id": 1}])
    monkeypatch.setattr(sql_assets, "SQLExecutor", MagicMock(return_value=executor))
    db = SimpleNamespace(commit=AsyncMock())

    result = await sql_assets.execute_sql_query_draft(
        db,
        draft_id=draft.id,
        user_id=draft.user_id,
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        candidate_ids=[candidate.id],
    )
    assert result["status"] == "completed"


def test_sql_asset_migration_and_responses_approval_contract() -> None:
    root = Path(__file__).resolve().parents[1]
    migration = (root / "alembic/versions/r0016_sql_assets.py").read_text(encoding="utf-8")
    assert 'down_revision = "r0015_enterprise_workbench_templates"' in migration
    assert "sql_asset_sources" in migration
    assert "sql_query_candidates" in migration
    assert "ENABLE ROW LEVEL SECURITY" in migration

    governance_migration = (root / "alembic/versions/r0017_sql_asset_governance.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "r0016_sql_assets"' in governance_migration
    assert "execution_started_at" in governance_migration
    assert "project_id" in governance_migration
    assert "uq_sql_asset_source_global_hash" in governance_migration

    knowledge_migration = (root / "alembic/versions/r0018_data_knowledge_annotations.py").read_text(
        encoding="utf-8"
    )
    assert 'down_revision = "r0017_sql_asset_governance"' in knowledge_migration
    assert "schema_table_metadata" in knowledge_migration
    assert "knowledge_metadata" in knowledge_migration

    corpus_migration = (
        root / "alembic/versions/r0019_sql_asset_corpus_and_query_plans.py"
    ).read_text(encoding="utf-8")
    assert 'down_revision = "r0018_data_knowledge"' in corpus_migration
    assert "structure_hash" in corpus_migration
    assert "corpus_role" in corpus_migration
    assert "query_plan" in corpus_migration

    import tools.builtin_tools.analytics_tools  # noqa: F401
    from tools.registry.registry import registry

    tool = registry.get("execute_sql_draft")
    assert tool is not None
    assert tool.side_effect == "write"
    assert tool.max_retries == 0
    assert "retry_failed" in tool.parameters["properties"]


def test_public_query_routes_only_generate_drafts() -> None:
    from gateway.api_gateway.routers.data import data_query
    from gateway.api_gateway.routers.databases import query_database

    for handler in (data_query, query_database):
        source = inspect.getsource(handler)
        assert "generate_sql_query_draft" in source
        assert "SQLExecutor" not in source
        assert "run_on_dsn" not in source

    supervisor_source = inspect.getsource(
        __import__(
            "agents.data_agent_v2.supervisor", fromlist=["DataAgentV2Supervisor"]
        ).DataAgentV2Supervisor.execute
    )
    assert "if reflection_enabled and not dry_run" in supervisor_source


@pytest.mark.asyncio
async def test_draft_lookup_uses_full_user_tenant_workspace_scope() -> None:
    class CaptureDB:
        statement = None

        async def scalar(self, statement):
            self.statement = statement
            return None

    db = CaptureDB()
    with pytest.raises(NotFoundException):
        await sql_assets.load_scoped_draft(
            db,
            draft_id="draft-other",
            user_id="user-a",
            tenant_id="tenant-a",
            workspace_id="workspace-a",
        )

    compiled = str(db.statement)
    assert "sql_query_drafts.id" in compiled
    assert "sql_query_drafts.user_id" in compiled
    assert "sql_query_drafts.tenant_id" in compiled
    assert "sql_query_drafts.workspace_id" in compiled


@pytest.mark.asyncio
async def test_asset_retrieval_only_uses_published_scoped_assets() -> None:
    class EmptyResult:
        @staticmethod
        def scalars():
            return SimpleNamespace(all=lambda: [])

    class CaptureDB:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    db = CaptureDB()
    rows = await sql_assets.retrieve_sql_assets(
        db,
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        data_source_id="source-a",
        question="订单收入",
        dialect="postgres",
    )

    assert rows == []
    compiled = str(db.statement)
    for column in (
        "sql_assets.tenant_id",
        "sql_assets.workspace_id",
        "sql_assets.data_source_id",
        "sql_assets.status",
        "sql_assets.corpus_role",
        "sql_assets.quality_status",
        "sql_assets.executable",
        "sql_assets.dialect",
    ):
        assert column in compiled


@pytest.mark.asyncio
async def test_asset_retrieval_uses_valid_draft_as_scoped_reference_fallback() -> None:
    def asset(**overrides):
        defaults = {
            "id": "asset-draft",
            "title": "历史定级查询",
            "description": "",
            "domain": None,
            "tags": [],
            "knowledge_metadata": {},
            "tables": ["tuwan_mysql.play_captain_hpay"],
            "columns": ["tuwan_mysql.play_captain_hpay.captain_id"],
            "normalized_sql": (
                "SELECT captain_id FROM tuwan_mysql.play_captain_hpay WHERE captain_id = 1"
            ),
            "status": "draft",
            "corpus_role": "retrieval",
            "quality_status": "unverified",
            "asset_type": "query",
            "executable": True,
            "validation_report": {"status": "pass"},
            "created_at": datetime.now(UTC),
            "retrieval_count": 0,
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    valid = asset()
    etl = asset(
        id="asset-etl",
        asset_type="etl",
        executable=False,
        normalized_sql="INSERT INTO target SELECT * FROM source",
    )
    stale = asset(
        id="asset-stale",
        tables=["other_database.other_table"],
        normalized_sql="SELECT id FROM other_database.other_table",
    )
    failed = asset(id="asset-failed", quality_status="failed")

    class Result:
        @staticmethod
        def scalars():
            return SimpleNamespace(all=lambda: [valid, etl, stale, failed])

    class CaptureDB:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return Result()

    db = CaptureDB()
    rows = await sql_assets.retrieve_sql_assets(
        db,
        tenant_id="tenant-a",
        workspace_id="workspace-a",
        data_source_id="source-a",
        question="完全没有关键词命中",
        dialect="clickhouse",
        include_draft_reference=True,
        available_tables=["tuwan_mysql.play_captain_hpay"],
    )

    assert rows == [valid]
    assert valid.retrieval_count == 1
    compiled = str(db.statement)
    assert "sql_assets.tenant_id" in compiled
    assert "sql_assets.workspace_id" in compiled
    assert "sql_assets.data_source_id" in compiled
    assert "sql_assets.dialect" in compiled
