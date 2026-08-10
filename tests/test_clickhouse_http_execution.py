from __future__ import annotations

import pytest

from execution.data.sql_executor import SQLExecutor, validate_sql_table_scope
from gateway.api_gateway.routers.databases import (
    _fetch_schema_metadata,
    _is_clickhouse_missing_comment_error,
    _schema_sql,
    _validate_database_name,
)
from infra.errors import AppException


class _FakeResponse:
    status_code = 200
    text = '{"ok":1}\n{"ok":2}\n'


class _FakeAsyncClient:
    calls: list[dict] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, endpoint, **kwargs):
        self.calls.append({"endpoint": endpoint, **kwargs})
        return _FakeResponse()


@pytest.mark.asyncio
async def test_clickhouse_http_dsn_uses_json_each_row(monkeypatch):
    monkeypatch.setattr(
        "execution.data.sql_executor.httpx.AsyncClient",
        _FakeAsyncClient,
    )
    _FakeAsyncClient.calls = []

    rows = await SQLExecutor(max_rows=2).run_on_dsn(
        "clickhouse+http://readonly_user:secret@clickhouse.example.com:80/default",
        "SELECT 1 AS ok",
        source_type="clickhouse",
    )

    assert rows == [{"ok": 1}, {"ok": 2}]
    call = _FakeAsyncClient.calls[0]
    assert call["endpoint"] == "http://clickhouse.example.com:80/"
    assert call["params"] == {"database": "default"}
    assert "FORMAT JSONEachRow" in call["content"].decode()
    assert call["auth"] == ("readonly_user", "secret")


def test_clickhouse_empty_database_schema_lists_all_business_databases():
    tables_sql, columns_sql = _schema_sql("clickhouse", "*")

    assert "concat(database, '.', name)" in tables_sql
    assert "database NOT IN ('system'" in tables_sql
    assert "concat(database, '.', table)" in columns_sql
    assert "database NOT IN ('system'" in columns_sql


def test_clickhouse_schema_sql_can_skip_comments_for_legacy_system_tables():
    tables_sql, columns_sql = _schema_sql(
        "clickhouse",
        "*",
        clickhouse_include_comments=False,
    )

    assert "'' AS table_comment" in tables_sql
    assert "'' AS column_comment" in columns_sql
    assert "comment AS table_comment" not in tables_sql
    assert "comment AS column_comment" not in columns_sql


def test_clickhouse_missing_comment_error_is_recognized():
    error = RuntimeError("Code: 47, Missing columns: 'comment'")

    assert _is_clickhouse_missing_comment_error(error) is True
    assert _is_clickhouse_missing_comment_error(RuntimeError("Code: 60, Table not found")) is False


@pytest.mark.asyncio
async def test_clickhouse_schema_metadata_falls_back_without_comments():
    class _LegacyClickHouseExecutor:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def run_on_dsn(self, _dsn, sql, *, source_type):
            assert source_type == "clickhouse"
            self.queries.append(sql)
            if "comment AS" in sql:
                raise RuntimeError("Code: 47, Missing columns: 'comment'")
            if "system.tables" in sql:
                return [{"database_name": "analytics", "table_name": "orders"}]
            return [
                {
                    "database_name": "analytics",
                    "table_name": "analytics.orders",
                    "column_name": "id",
                    "data_type": "UInt64",
                }
            ]

    executor = _LegacyClickHouseExecutor()
    tables, tables_truncated, columns, columns_truncated, used_legacy = (
        await _fetch_schema_metadata(
            executor,
            "clickhouse+http://example.com:8123/default",
            source_type="clickhouse",
            schema_name="*",
            page_size=100,
            max_tables=1000,
            max_columns=1000,
        )
    )

    assert tables == [{"database_name": "analytics", "table_name": "orders"}]
    assert columns[0]["column_name"] == "id"
    assert tables_truncated is False
    assert columns_truncated is False
    assert used_legacy is True
    assert len(executor.queries) == 3
    assert "'' AS table_comment" in executor.queries[1]
    assert "'' AS column_comment" in executor.queries[2]


def test_only_clickhouse_can_leave_database_empty():
    assert _validate_database_name("clickhouse", "") == ""

    with pytest.raises(AppException, match="必须填写数据库名"):
        _validate_database_name("mysql", "")


def test_sql_table_scope_rejects_missing_and_cross_database_tables():
    table_columns = {"analytics.orders": ["id"], "customers": ["id"]}

    validate_sql_table_scope(
        "SELECT id FROM analytics.orders",
        table_columns=table_columns,
        source_type="clickhouse",
    )
    validate_sql_table_scope(
        "WITH scoped AS (SELECT id FROM analytics.orders) SELECT id FROM scoped",
        table_columns=table_columns,
        source_type="clickhouse",
    )

    with pytest.raises(ValueError, match="不存在的表"):
        validate_sql_table_scope(
            "SELECT id FROM other.orders",
            table_columns=table_columns,
            source_type="clickhouse",
        )
    with pytest.raises(ValueError, match="不存在的表"):
        validate_sql_table_scope(
            "SELECT id FROM missing_table",
            table_columns=table_columns,
            source_type="postgres",
        )


@pytest.mark.asyncio
async def test_sql_executor_rejects_cross_database_table_before_connection(monkeypatch):
    monkeypatch.setattr(
        "execution.data.sql_executor.httpx.AsyncClient",
        _FakeAsyncClient,
    )
    _FakeAsyncClient.calls = []

    with pytest.raises(ValueError, match="other.orders"):
        await SQLExecutor().run_on_dsn(
            "clickhouse+http://readonly_user:secret@clickhouse.example.com:80/analytics",
            "SELECT id FROM other.orders",
            source_type="clickhouse",
            table_columns={"analytics.orders": ["id"]},
        )

    assert _FakeAsyncClient.calls == []
