"""Schema 人工标注、自动建议与统一数据知识上下文测试。"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from infra.storage.models import SchemaMetadata, SchemaTableMetadata
from services.data_knowledge_context import _bounded_json, build_data_knowledge_context
from services.schema_annotations import (
    approve_annotation,
    reconcile_schema_annotations,
    reject_annotation,
)


def test_schema_annotation_api_contract_and_payload_limits() -> None:
    from gateway.api_gateway.routers.schema_annotations import (
        SchemaAnnotationUpsertRequest,
        router,
    )

    paths = {route.path for route in router.routes}
    assert "/databases/{database_id}/schema-annotations" in paths
    assert "/databases/{database_id}/schema-annotations/auto-suggest" in paths
    assert "/databases/{database_id}/schema-annotations/review" in paths
    assert "/databases/{database_id}/schema-annotations/{target_type}/{annotation_id}" in paths

    with pytest.raises(ValidationError, match="column_name"):
        SchemaAnnotationUpsertRequest(target_type="column", table_name="orders")
    with pytest.raises(ValidationError, match="最多 200 项"):
        SchemaAnnotationUpsertRequest(
            target_type="table",
            table_name="orders",
            value_map={str(index): "value" for index in range(201)},
        )


class _ScalarRows:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._rows)


class _AnnotationDB:
    def __init__(self, table_rows=None, column_rows=None):
        self._results = [_ScalarRows(table_rows or []), _ScalarRows(column_rows or [])]
        self.added = []

    async def execute(self, _statement):
        return self._results.pop(0)

    def add(self, record):
        self.added.append(record)


@pytest.mark.asyncio
async def test_schema_reconcile_creates_reviewable_table_and_column_suggestions() -> None:
    db = _AnnotationDB()
    stats = await reconcile_schema_annotations(
        db,
        data_source_id="source-1",
        fingerprint="fingerprint-1",
        schema_payload={
            "tables": [
                {
                    "name": "orders",
                    "comment": "订单事实表",
                    "columns": [
                        {"name": "paid_at", "type": "timestamp", "comment": "支付时间"},
                        {"name": "amount", "type": "decimal", "comment": "订单金额"},
                    ],
                }
            ]
        },
    )

    assert stats == {
        "created": 3,
        "updated": 0,
        "conflicts": 0,
        "unchanged": 0,
        "skipped": 0,
    }
    table = next(item for item in db.added if isinstance(item, SchemaTableMetadata))
    paid_at = next(
        item
        for item in db.added
        if isinstance(item, SchemaMetadata) and item.column_name == "paid_at"
    )
    amount = next(
        item
        for item in db.added
        if isinstance(item, SchemaMetadata) and item.column_name == "amount"
    )
    assert table.business_description == "订单事实表"
    assert table.annotation_status == "suggested"
    assert table.annotation_source == "database_comment"
    assert paid_at.is_time_column is True
    assert amount.is_metric_column is True


@pytest.mark.asyncio
async def test_schema_reconcile_never_overwrites_verified_manual_annotation() -> None:
    table = SchemaTableMetadata(
        id="table-1",
        data_source_id="source-1",
        table_name="orders",
        business_name="交易订单",
        business_description="人工定义",
        annotation_source="manual",
        annotation_confidence=1.0,
        annotation_status="verified",
        source_refs=[],
        suggested_changes={},
    )
    column = SchemaMetadata(
        id="column-1",
        data_source_id="source-1",
        table_name="orders",
        column_name="amount",
        business_name="实付金额",
        business_description="人工口径",
        annotation_source="manual",
        annotation_confidence=1.0,
        annotation_status="verified",
        source_refs=[],
        suggested_changes={},
    )
    db = _AnnotationDB([table], [column])

    stats = await reconcile_schema_annotations(
        db,
        data_source_id="source-1",
        fingerprint="fingerprint-2",
        schema_payload={
            "tables": [
                {
                    "name": "orders",
                    "comment": "数据库订单表",
                    "columns": [{"name": "amount", "type": "decimal", "comment": "数据库金额"}],
                }
            ]
        },
    )

    assert stats["conflicts"] == 2
    assert table.business_name == "交易订单"
    assert table.business_description == "人工定义"
    assert column.business_name == "实付金额"
    assert column.business_description == "人工口径"
    assert table.suggested_changes["source"] == "database_comment"
    assert column.suggested_changes["fields"]["business_description"] == "数据库金额"


def test_accepting_suggestion_applies_changes_and_records_reviewer() -> None:
    record = SchemaTableMetadata(
        id="table-1",
        data_source_id="source-1",
        table_name="orders",
        business_name="订单",
        annotation_source="manual",
        annotation_confidence=1.0,
        annotation_status="verified",
        source_refs=[],
        suggested_changes={
            "fields": {"business_description": "来自已发布 SQL 的口径"},
            "source": "sql_asset",
            "confidence": 0.9,
        },
    )

    approve_annotation(record, user_id="user-1")

    assert record.business_description == "来自已发布 SQL 的口径"
    assert record.annotation_status == "verified"
    assert record.annotation_source == "sql_asset"
    assert record.approved_by == "user-1"
    assert isinstance(record.approved_at, datetime)
    assert record.approved_at.tzinfo == UTC


def test_rejecting_conflict_keeps_verified_manual_annotation() -> None:
    record = SchemaTableMetadata(
        id="table-1",
        data_source_id="source-1",
        table_name="orders",
        business_name="人工订单",
        annotation_source="manual",
        annotation_confidence=1.0,
        annotation_status="verified",
        source_refs=[],
        suggested_changes={
            "fields": {"business_name": "自动订单"},
            "source": "database_comment",
            "confidence": 0.9,
        },
    )

    reject_annotation(record, user_id="user-1")

    assert record.business_name == "人工订单"
    assert record.annotation_status == "verified"
    assert record.suggested_changes == {}


@pytest.mark.asyncio
async def test_unified_data_knowledge_context_contains_governed_assets() -> None:
    table = SimpleNamespace(
        table_name="orders",
        business_name="订单",
        business_description="支付订单事实表",
        aliases=["交易"],
        tags=["收入"],
        annotation_source="manual",
        annotation_status="verified",
        annotation_confidence=1.0,
    )
    column = SimpleNamespace(
        table_name="orders",
        column_name="amount",
        business_name="实付金额",
        business_description="扣除优惠后的支付金额",
        aliases=["收入"],
        tags=["GMV"],
        value_map={},
        semantic_type="metric",
        is_time_column=False,
        time_grain=None,
        is_metric_column=True,
        is_dimension_column=False,
        is_sensitive=False,
        annotation_source="manual",
        annotation_status="verified",
        annotation_confidence=1.0,
    )
    metric = SimpleNamespace(
        name="净收入",
        aliases=["收入"],
        formula="SUM(orders.amount)",
        business_definition="支付成功订单收入",
        unit="元",
        category="收入",
        tags=["GMV"],
        underlying_columns=["orders.amount"],
    )
    relationship = SimpleNamespace(
        left_table="orders",
        left_column="customer_id",
        right_table="customers",
        right_column="id",
        join_type="LEFT",
        cardinality="N:1",
        amplification_risk="low",
    )
    asset = SimpleNamespace(
        title="订单净收入",
        description="支付金额口径",
        tags=["收入"],
        knowledge_metadata={"questions": ["订单收入是多少"]},
    )

    class _DB:
        def __init__(self):
            self.results = [
                _ScalarRows([table]),
                _ScalarRows([column]),
                _ScalarRows([metric]),
                _ScalarRows([relationship]),
            ]

        async def scalar(self, _statement):
            return SimpleNamespace(semantic_mappings={"metrics": {"收入": "SUM(amount)"}})

        async def execute(self, _statement):
            return self.results.pop(0)

    context = await build_data_knowledge_context(
        _DB(),
        data_source_id="source-1",
        question="查询订单收入",
        assets=[asset],
        max_chars=12000,
    )

    assert "实付金额" in context.prompt
    assert "SUM(orders.amount)" in context.prompt
    assert "orders.customer_id" in context.prompt
    assert "订单净收入" in context.prompt
    assert context.counts == {
        "tables": 1,
        "columns": 1,
        "metrics": 1,
        "relationships": 1,
        "sql_assets": 1,
        "truncated_sections": 0,
    }


def test_bounded_knowledge_context_remains_valid_json() -> None:
    import json

    payload = {
        "semantic_mappings": {f"field_{index}": "说明" * 20 for index in range(100)},
        "column_annotations": [
            {"table": "orders", "column": f"column_{index}", "description": "含义" * 20}
            for index in range(100)
        ],
    }

    raw, truncated = _bounded_json(payload, max_chars=1000)

    assert len(raw) <= 1000
    assert json.loads(raw)["_truncated_sections"]
    assert truncated
