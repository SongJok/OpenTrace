from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, time
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, unquote_plus, urlsplit

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from infra.config.settings import settings
from kernel.data_cognition.sql_validator import SQLValidator


def _make_json_safe(val: Any) -> Any:
    """Convert database-native types to JSON-serializable equivalents."""
    if isinstance(val, datetime | date | time):
        return val.isoformat()
    if isinstance(val, Decimal):
        return float(val)
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")
    return val


class SQLExecutor:
    def __init__(self, *, max_rows: int | None = None, timeout_ms: int | None = None) -> None:
        self.max_rows = max(1, int(max_rows or settings.text2sql_max_result_rows))
        self.timeout_ms = max(1, int(timeout_ms or settings.text2sql_statement_timeout_ms))

    def _validated_sql(self, sql: str) -> str:
        return SQLValidator(
            default_limit=self.max_rows,
            max_limit=self.max_rows,
        ).validate(sql)

    def _serialize_rows(self, result: Any) -> list[dict[str, Any]]:
        rows = result.mappings().fetchmany(self.max_rows)
        return [{k: _make_json_safe(v) for k, v in dict(row).items()} for row in rows]

    async def run(self, db: AsyncSession, sql: str) -> list[dict[str, Any]]:
        safe_sql = self._validated_sql(sql)
        result = await asyncio.wait_for(
            db.execute(text(safe_sql)),
            timeout=self.timeout_ms / 1000,
        )
        return self._serialize_rows(result)

    @staticmethod
    def _runtime_dsn(dsn: str) -> str:
        """兼容历史 asyncmy DSN，并统一切换到已通过漏洞门禁的 aiomysql。"""
        return dsn.replace("mysql+asyncmy://", "mysql+aiomysql://", 1)

    async def run_on_dsn(
        self,
        dsn: str,
        sql: str,
        *,
        source_type: str | None = None,
    ) -> list[dict[str, Any]]:
        safe_sql = self._validated_sql(sql)
        if dsn.startswith(("clickhouse+http://", "clickhouse+https://")):
            return await self._run_clickhouse_http_on_dsn(dsn, safe_sql)
        runtime_dsn = self._runtime_dsn(dsn)
        engine = create_async_engine(runtime_dsn, pool_pre_ping=True, future=True)
        try:

            async def _execute() -> list[dict[str, Any]]:
                async with engine.begin() as conn:
                    for setup_sql in self._read_only_setup_statements(dsn, source_type=source_type):
                        await conn.execute(text(setup_sql))
                    result = await conn.execute(text(safe_sql))
                    return self._serialize_rows(result)

            return await asyncio.wait_for(_execute(), timeout=self.timeout_ms / 1000)
        finally:
            await engine.dispose()

    async def _run_clickhouse_http_on_dsn(self, dsn: str, safe_sql: str) -> list[dict[str, Any]]:
        """通过 ClickHouse HTTP 接口执行只读 SQL，兼容 80/8123 等 HTTP 端口。"""

        parsed = urlsplit(
            dsn.replace("clickhouse+http://", "http://", 1).replace(
                "clickhouse+https://", "https://", 1
            )
        )
        if not parsed.hostname:
            raise ValueError("ClickHouse HTTP 地址缺少主机名")
        endpoint = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}/"
        database = unquote(parsed.path.lstrip("/")).strip() or "default"
        username = unquote_plus(parsed.username or "")
        password = unquote_plus(parsed.password or "")
        query = safe_sql.rstrip().rstrip(";") + "\nFORMAT JSONEachRow"
        timeout = httpx.Timeout(self.timeout_ms / 1000)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(
                endpoint,
                params={"database": database},
                content=query.encode("utf-8"),
                auth=(username, password),
            )
        if response.status_code >= 400:
            detail = response.text.strip().replace("\n", " ")[:500]
            raise RuntimeError(f"ClickHouse HTTP 查询失败（{response.status_code}）：{detail}")
        rows: list[dict[str, Any]] = []
        for line in response.text.splitlines():
            if not line.strip():
                continue
            value = json.loads(line)
            if isinstance(value, dict):
                rows.append({key: _make_json_safe(item) for key, item in value.items()})
            if len(rows) >= self.max_rows:
                break
        return rows

    def _read_only_setup_statements(
        self, dsn: str, *, source_type: str | None = None
    ) -> tuple[str, ...]:
        source = str(source_type or "").strip().lower()
        # Doris 使用 MySQL 协议驱动，但并不完整支持 MySQL 的事务级只读语句。
        # 查询只读性仍由 AST 白名单、LIMIT、超时以及数据库只读账号共同保证。
        if source in {"doris", "clickhouse"}:
            return ()
        normalized = dsn.lower()
        if normalized.startswith("postgresql"):
            return (
                "SET TRANSACTION READ ONLY",
                f"SET LOCAL statement_timeout = {self.timeout_ms}",
            )
        if source == "mysql" or (not source and normalized.startswith("mysql")):
            return (
                "SET TRANSACTION READ ONLY",
                f"SET SESSION MAX_EXECUTION_TIME = {self.timeout_ms}",
            )
        return ()
