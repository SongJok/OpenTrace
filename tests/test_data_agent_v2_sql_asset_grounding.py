from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agents.base import TaskMessage
from agents.data_agent_v2.entity_agent import EntityAgent
from agents.data_agent_v2.intent_agent import IntentAgent
from agents.data_agent_v2.supervisor import DataAgentV2Supervisor
from agents.data_agent_v2.types import CognitiveContext
from kernel.clarification_gate import DataClarificationGate


def _captain_asset_context() -> list[dict]:
    return [
        {
            "id": "asset-captain",
            "title": "队长定级查询",
            "description": "按队长 ID 查询定级记录",
            "tables": ["tuwan_mysql.play_captain_hpay"],
            "columns": [
                "tuwan_mysql.play_captain_hpay.captain_id",
                "tuwan_mysql.play_captain_hpay.grade",
            ],
            "knowledge_metadata": {"questions": ["队长定级数据"]},
            "sql": (
                "SELECT captain_id, grade FROM tuwan_mysql.play_captain_hpay "
                "WHERE captain_id = 100"
            ),
            "reference_only": True,
        }
    ]


@pytest.mark.asyncio
async def test_sql_asset_resolves_captain_id_lookup_without_clarification() -> None:
    ctx = CognitiveContext(
        query="队长id=10159490的定级数据",
        data_source_id="ds-clickhouse",
        database_name="tuwan_mysql",
        dialect="clickhouse",
        table_names=["tuwan_mysql.play_captain_hpay"],
        table_columns={"tuwan_mysql.play_captain_hpay": ["captain_id", "grade", "created_at"]},
        sql_asset_context=_captain_asset_context(),
        intent={"intent_type": "raw_lookup", "confidence": 0.4},
        metrics=[],
    )

    ctx.entities = await EntityAgent()._resolve_entities(ctx)

    assert ctx.entities == [
        {
            "mention": "队长",
            "mapped_table": "tuwan_mysql.play_captain_hpay",
            "mapped_column": "captain_id",
            "mapped_value": "10159490",
            "confidence": 0.86,
            "source": "sql_asset_reference",
        }
    ]
    assert DataClarificationGate().detect(ctx)["needs_clarification"] is False


def test_clickhouse_table_schema_uses_selected_datasource_database() -> None:
    ctx = CognitiveContext(
        query="打印一下 tuwan_mysql.play_captain_hpay 的表结构",
        data_source_id="ds-clickhouse",
        database_name="tuwan_mysql",
        dialect="clickhouse",
        table_names=["tuwan_mysql.play_captain_hpay"],
        table_columns={"tuwan_mysql.play_captain_hpay": ["captain_id", "grade"]},
    )

    sql = IntentAgent()._check_structured_intent(ctx)

    assert sql is not None
    assert "FROM system.columns" in sql
    assert "database = 'tuwan_mysql'" in sql
    assert "table = 'play_captain_hpay'" in sql

    outside_ctx = CognitiveContext(
        query="打印一下 other_database.play_captain_hpay 的表结构",
        database_name="tuwan_mysql",
        dialect="clickhouse",
        table_names=["tuwan_mysql.play_captain_hpay"],
    )
    assert IntentAgent()._check_structured_intent(outside_ctx) is None


def test_supervisor_merges_asset_metric_and_join_rules() -> None:
    ctx = CognitiveContext(
        query="查询收入",
        matched_metrics=[],
        matched_relationships=[],
        sql_asset_context=[
            {
                "id": "asset-revenue",
                "description": "支付成功订单净收入",
                "knowledge_metadata": {
                    "metric_rules": [
                        {
                            "name": "净收入",
                            "formula": "SUM(o.amount) - SUM(o.refund_amount)",
                            "aggregation": "SUM",
                            "source_columns": ["orders.amount", "orders.refund_amount"],
                            "source_tables": ["orders"],
                        }
                    ],
                    "joins": [
                        {
                            "left_table": "orders",
                            "left_column": "customer_id",
                            "right_table": "customers",
                            "right_column": "id",
                            "join_type": "LEFT",
                        }
                    ],
                },
            }
        ],
    )

    grounded = DataAgentV2Supervisor()._merge_sql_asset_knowledge(ctx)

    assert grounded.matched_metrics[0]["name"] == "净收入"
    assert grounded.matched_metrics[0]["source"] == "sql_asset_reference"
    assert grounded.matched_metrics[0]["formula"] == "SUM(o.amount) - SUM(o.refund_amount)"
    assert grounded.matched_relationships[0]["left_table"] == "orders"
    assert grounded.matched_relationships[0]["source"] == "sql_asset_reference"


def test_supervisor_rejects_foreign_database_reference_before_model_planning() -> None:
    supervisor = DataAgentV2Supervisor()
    foreign = CognitiveContext(
        query="查询 other_database.play_captain_hpay 的定级数据",
        database_name="tuwan_mysql",
        table_names=["tuwan_mysql.play_captain_hpay"],
        table_columns={"tuwan_mysql.play_captain_hpay": ["captain_id", "grade"]},
    )
    valid = CognitiveContext(
        query="查询 tuwan_mysql.play_captain_hpay 的定级数据",
        database_name="tuwan_mysql",
        table_names=["tuwan_mysql.play_captain_hpay"],
        table_columns={"tuwan_mysql.play_captain_hpay": ["captain_id", "grade"]},
    )

    assert supervisor._query_database_scope_violation(foreign)
    assert supervisor._query_database_scope_violation(valid) is None


@pytest.mark.asyncio
async def test_supervisor_loads_sql_assets_from_authorized_datasource(monkeypatch) -> None:
    data_source = SimpleNamespace(
        id="ds-clickhouse",
        source_type="clickhouse",
        host="clickhouse.example.com",
        port=8123,
        database="tuwan_mysql",
        username="readonly",
        password_encrypted="encrypted",
    )
    schema_row = SimpleNamespace(
        schema_json=(
            '{"database_scope":"*","tables":['
            '{"database":"tuwan_mysql","name":"play_captain_hpay",'
            '"columns":[{"name":"captain_id"},{"name":"grade"}]}]}'
        ),
        semantic_mappings={},
    )
    sql_asset = SimpleNamespace(
        id="asset-captain",
        title="队长定级查询",
        description="按队长 ID 查询定级记录",
        status="draft",
        quality_status="unverified",
        corpus_role="retrieval",
        executable=True,
        tables=["tuwan_mysql.play_captain_hpay"],
        columns=["tuwan_mysql.play_captain_hpay.captain_id"],
        knowledge_metadata={"questions": ["队长定级数据"]},
        normalized_sql="SELECT captain_id FROM tuwan_mysql.play_captain_hpay",
    )

    class SchemaResult:
        @staticmethod
        def scalar():
            return schema_row

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def execute(self, _statement):
            return SchemaResult()

    retrieve = AsyncMock(return_value=[sql_asset])
    monkeypatch.setattr("infra.storage.database.AsyncSessionLocal", Session)
    monkeypatch.setattr(
        "infra.security.resource_scope.get_accessible_data_source",
        AsyncMock(return_value=data_source),
    )
    monkeypatch.setattr(
        "infra.security.data_source_secrets.decrypt_data_source_secret",
        lambda _value: "secret",
    )
    monkeypatch.setattr(
        "execution.data.db_router.DBRouter.build_dsn",
        lambda _self, _info: "clickhouse+http://readonly:secret@clickhouse.example.com:8123/tuwan_mysql",
    )
    monkeypatch.setattr("services.sql_assets.retrieve_sql_assets", retrieve)

    task = TaskMessage(
        task_id="task-captain",
        agent_type="data",
        query="队长id=10159490的定级数据",
        user_id="user-a",
        params={
            "data_source_id": "ds-clickhouse",
            "tenant_id": "tenant-a",
            "workspace_id": "workspace-a",
        },
    )
    supervisor = DataAgentV2Supervisor()
    ctx = supervisor._init_context(task)

    await supervisor._load_datasource_metadata(task, ctx)

    assert ctx.database_name == "tuwan_mysql"
    assert ctx.table_names == ["tuwan_mysql.play_captain_hpay"]
    assert ctx.sql_asset_context and ctx.sql_asset_context[0]["id"] == "asset-captain"
    assert ctx.sql_asset_context[0]["reference_only"] is True
    assert ctx.metadata_extra == {
        "sql_asset_context_count": 1,
        "sql_asset_context_source": "scoped_sql_assets",
    }
    retrieve.assert_awaited_once()
    kwargs = retrieve.await_args.kwargs
    assert kwargs["tenant_id"] == "tenant-a"
    assert kwargs["workspace_id"] == "workspace-a"
    assert kwargs["data_source_id"] == "ds-clickhouse"
    assert kwargs["include_draft_reference"] is True
    assert kwargs["available_tables"] == ["tuwan_mysql.play_captain_hpay"]
