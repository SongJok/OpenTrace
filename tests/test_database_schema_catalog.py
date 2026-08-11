"""大规模数据库 Schema 同步与分页目录合约。"""

from __future__ import annotations

import json
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from gateway.api_gateway.routers.databases import _fetch_schema_rows, _schema_catalog_page


class _PagedMetadataExecutor:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.queries: list[str] = []

    async def run_on_dsn(
        self,
        _dsn: str,
        sql: str,
        *,
        source_type: str | None = None,
    ) -> list[dict[str, object]]:
        assert source_type
        self.queries.append(sql)
        match = re.search(r"LIMIT (\d+) OFFSET (\d+)$", sql)
        assert match is not None
        limit, offset = (int(value) for value in match.groups())
        return self.rows[offset : offset + limit]


@pytest.mark.asyncio
async def test_schema_metadata_fetches_all_rows_beyond_data_agent_500_limit() -> None:
    source_rows = [{"table_name": f"table_{index:04d}"} for index in range(1250)]
    executor = _PagedMetadataExecutor(source_rows)

    rows, truncated = await _fetch_schema_rows(
        executor,
        "postgresql+asyncpg://example",
        "SELECT table_name FROM information_schema.tables ORDER BY table_name",
        source_type="postgres",
        page_size=200,
        max_rows=2000,
    )

    assert len(rows) == 1250
    assert rows[-1]["table_name"] == "table_1249"
    assert truncated is False
    assert len(executor.queries) == 7


@pytest.mark.asyncio
async def test_schema_metadata_reports_independent_safety_budget() -> None:
    source_rows = [{"table_name": f"table_{index:04d}"} for index in range(1250)]
    executor = _PagedMetadataExecutor(source_rows)

    rows, truncated = await _fetch_schema_rows(
        executor,
        "mysql+aiomysql://example",
        "SELECT table_name FROM information_schema.tables ORDER BY table_name",
        source_type="mysql",
        page_size=200,
        max_rows=1000,
    )

    assert len(rows) == 1000
    assert truncated is True
    assert "OFFSET 800" in executor.queries[-1]


def test_schema_catalog_pages_and_searches_more_than_500_tables() -> None:
    payload = {
        "schema": "*",
        "databases": ["analytics", "finance"],
        "table_count": 1250,
        "tables": [
            {
                "name": f"analytics.fact_order_{index:04d}",
                "database": "analytics" if index % 2 == 0 else "finance",
                "qualified_name": f"analytics.fact_order_{index:04d}",
                "comment": "订单事实表" if index == 1100 else "",
                "columns": [],
            }
            for index in range(1250)
        ],
    }

    page, pagination = _schema_catalog_page(
        payload,
        search="订单事实",
        database="analytics",
        offset=0,
        limit=100,
    )
    assert pagination == {
        "offset": 0,
        "limit": 100,
        "count": 1,
        "total": 1,
        "has_more": False,
        "next_offset": None,
    }
    assert page["table_count"] == 1250
    assert page["tables"][0]["name"] == "analytics.fact_order_1100"

    page, pagination = _schema_catalog_page(
        payload,
        search="",
        database=None,
        offset=500,
        limit=100,
    )
    assert len(page["tables"]) == 100
    assert page["tables"][0]["name"] == "analytics.fact_order_0500"
    assert pagination["total"] == 1250
    assert pagination["has_more"] is True
    assert pagination["next_offset"] == 600


@pytest.mark.asyncio
async def test_schema_catalog_endpoint_keeps_scope_and_returns_bounded_page(monkeypatch) -> None:
    from gateway.api_gateway.routers import databases

    payload = {
        "table_count": 750,
        "tables": [{"name": f"table_{index:04d}", "columns": []} for index in range(750)],
    }

    class _Result:
        def scalar_one_or_none(self):
            return SimpleNamespace(schema_json=json.dumps(payload))

    db = SimpleNamespace(execute=AsyncMock(return_value=_Result()))
    owned = AsyncMock(return_value=SimpleNamespace(id="source-1"))
    monkeypatch.setattr(databases, "_owned_data_source", owned)
    user = SimpleNamespace(id="user-1")
    request = SimpleNamespace()

    result = await databases.get_database_schema(
        request,
        "source-1",
        search="",
        database=None,
        offset=500,
        limit=100,
        current_user=user,
        db=db,
    )

    owned.assert_awaited_once_with(db, request, user, "source-1", "view")
    assert len(result["schema"]["tables"]) == 100
    assert result["schema"]["tables"][0]["name"] == "table_0500"
    assert result["pagination"]["total"] == 750
    assert result["pagination"]["next_offset"] == 600


def test_schema_sync_limits_are_declared_in_all_configuration_truth_sources() -> None:
    from infra.config.settings import AppSettings

    assert AppSettings.model_fields["database_schema_sync_page_size"].default == 2000
    assert AppSettings.model_fields["database_schema_sync_max_tables"].default == 100000
    assert AppSettings.model_fields["database_schema_sync_max_columns"].default == 1000000
