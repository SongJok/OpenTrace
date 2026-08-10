"""OpenTrace 只读数据源执行适配器。"""

from __future__ import annotations

import time

from execution.data.db_router import DBConnectionInfo, DBRouter
from execution.data.sql_executor import SQLExecutor
from infra.security.data_source_secrets import decrypt_data_source_secret
from infra.storage.models import DataSource
from text2sql.contracts import DataScope, EvidenceBundle, ExecutionResult


class OpenTraceQueryExecutor:
    def __init__(self, data_source: DataSource) -> None:
        self.data_source = data_source
        self.router = DBRouter()

    async def execute(
        self,
        scope: DataScope,
        sql: str,
        *,
        max_rows: int,
        evidence: EvidenceBundle,
    ) -> ExecutionResult:
        if scope.data_source_id != self.data_source.id:
            raise PermissionError("data_source_scope_mismatch")
        password = decrypt_data_source_secret(self.data_source.password_encrypted)
        dsn = self.router.build_dsn(
            DBConnectionInfo(
                source_type=self.data_source.source_type,
                host=self.data_source.host,
                port=self.data_source.port,
                database=self.data_source.database,
                username=self.data_source.username,
                password=password,
            )
        )
        started = time.monotonic()
        rows = await SQLExecutor(max_rows=max_rows).run_on_dsn(
            dsn,
            sql,
            source_type=self.data_source.source_type,
            table_columns=evidence.table_columns,
        )
        returned = len(rows)
        truncated = returned >= max_rows
        return ExecutionResult(
            rows=rows,
            returned_rows=returned,
            total_rows=None,
            truncated=truncated,
            columns=list(rows[0]) if rows else [],
            duration_ms=int((time.monotonic() - started) * 1000),
            freshness=evidence.data_freshness,
            warnings=["结果达到 max_rows，total_rows 未知"] if truncated else [],
        )
