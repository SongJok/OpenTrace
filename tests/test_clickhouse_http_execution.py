from __future__ import annotations

import pytest

from execution.data.sql_executor import SQLExecutor
from gateway.api_gateway.routers.databases import _schema_sql, _validate_database_name
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


def test_only_clickhouse_can_leave_database_empty():
    assert _validate_database_name("clickhouse", "") == ""

    with pytest.raises(AppException, match="必须填写数据库名"):
        _validate_database_name("mysql", "")
