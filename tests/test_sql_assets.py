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
    assert "sql_asset_sources.project_id IS NULL" in str(db.scalar_statements[1])


@pytest.mark.asyncio
async def test_data_agent_generation_mode_never_enters_v1_or_v2_execution(monkeypatch) -> None:
    expected = AgentResult(
        task_id="task-1",
        agent_type="data",
        status="success",
        content="draft",
    )
    generate = AsyncMock(return_value=expected)
    monkeypatch.setattr(DataAgent, "_generate_sql_draft", generate)
    monkeypatch.setattr(
        DataAgent,
        "_get_v1",
        MagicMock(side_effect=AssertionError("generation_only 不得进入 V1 执行路径")),
    )

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
async def test_stale_executing_draft_is_recovered_and_retried(monkeypatch) -> None:
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

    result = await sql_assets.execute_sql_query_draft(
        db,
        draft_id=draft.id,
        user_id=draft.user_id,
        tenant_id=draft.tenant_id,
        workspace_id=draft.workspace_id,
        candidate_ids=[candidate.id],
    )

    assert result["status"] == "completed"
    assert result["execution_summary"]["recovery_count"] == 1
    assert candidate.execution_status == "completed"
    executor.run_on_dsn.assert_awaited_once()


@pytest.mark.asyncio
async def test_draft_execution_revalidates_project_binding(monkeypatch) -> None:
    schema = {"tables": [{"name": "orders"}]}
    draft = _draft(fingerprint=sql_assets.schema_fingerprint(schema))
    draft.project_id = "project-1"
    candidate = _candidate("candidate-1", "SELECT id FROM orders LIMIT 100", 1)
    await _patch_execution_scope(monkeypatch, draft, [candidate], schema)
    validate_project = AsyncMock(side_effect=ValidationException("Project 未绑定该数据源"))
    monkeypatch.setattr(sql_assets, "_validate_project_scope", validate_project)
    executor = MagicMock()
    monkeypatch.setattr(sql_assets, "SQLExecutor", executor)
    db = SimpleNamespace(commit=AsyncMock())

    with pytest.raises(ValidationException, match="Project 未绑定"):
        await sql_assets.execute_sql_query_draft(
            db,
            draft_id=draft.id,
            user_id=draft.user_id,
            tenant_id=draft.tenant_id,
            workspace_id=draft.workspace_id,
            candidate_ids=[candidate.id],
        )

    validate_project.assert_awaited_once()
    executor.assert_not_called()


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

    import tools.builtin_tools.analytics_tools  # noqa: F401
    from tools.registry.registry import registry

    tool = registry.get("execute_sql_draft")
    assert tool is not None
    assert tool.side_effect == "write"
    assert tool.max_retries == 0


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
        project_id=None,
    )

    assert rows == []
    compiled = str(db.statement)
    for column in (
        "sql_assets.tenant_id",
        "sql_assets.workspace_id",
        "sql_assets.data_source_id",
        "sql_assets.status",
        "sql_assets.executable",
        "sql_assets.dialect",
    ):
        assert column in compiled
