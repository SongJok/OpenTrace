"""OpenTrace 只读数据源执行适配器。"""

from __future__ import annotations

import re
import time
from typing import Any

from data_agent.contracts import (
    DataScope,
    EvidenceBundle,
    ExecutionResult,
    PreflightReport,
    ValidationIssue,
)
from execution.data.db_router import DBConnectionInfo, DBRouter
from execution.data.sql_executor import SQLExecutor
from infra.config.settings import settings
from infra.security.data_source_secrets import decrypt_data_source_secret
from infra.storage.models import DataSource


class OpenTraceQueryExecutor:
    def __init__(self, data_source: DataSource) -> None:
        self.data_source = data_source
        self.router = DBRouter()

    def _dsn(self) -> str:
        password = decrypt_data_source_secret(self.data_source.password_encrypted)
        return self.router.build_dsn(
            DBConnectionInfo(
                source_type=self.data_source.source_type,
                host=self.data_source.host,
                port=self.data_source.port,
                database=self.data_source.database,
                username=self.data_source.username,
                password=password,
            )
        )

    async def preflight(
        self,
        scope: DataScope,
        sql: str,
        *,
        evidence: EvidenceBundle,
    ) -> PreflightReport:
        if scope.data_source_id != self.data_source.id:
            raise PermissionError("data_source_scope_mismatch")
        try:
            rows = await SQLExecutor(
                max_rows=200,
                timeout_ms=settings.data_agent_preflight_timeout_ms,
            ).explain_on_dsn(
                self._dsn(),
                sql,
                source_type=self.data_source.source_type,
                table_columns=evidence.table_columns,
            )
        except (OSError, RuntimeError, TimeoutError, TypeError, ValueError) as exc:
            severity = "error" if settings.data_agent_preflight_required else "warning"
            return PreflightReport(
                status="fail" if severity == "error" else "warn",
                issues=[
                    ValidationIssue(
                        code="explain_failed",
                        message=f"执行前 EXPLAIN 失败：{str(exc)[:500]}",
                        severity=severity,
                    )
                ],
            )

        estimated_rows, estimated_bytes = self._estimates(rows)
        issues: list[ValidationIssue] = []
        if (
            estimated_rows is not None
            and estimated_rows > settings.data_agent_preflight_max_estimated_rows
        ):
            issues.append(
                ValidationIssue(
                    code="estimated_rows_exceeded",
                    message=(
                        f"预计扫描 {estimated_rows} 行，超过平台上限 "
                        f"{settings.data_agent_preflight_max_estimated_rows}"
                    ),
                )
            )
        if (
            estimated_bytes is not None
            and estimated_bytes > settings.data_agent_preflight_max_estimated_bytes
        ):
            issues.append(
                ValidationIssue(
                    code="estimated_bytes_exceeded",
                    message=(
                        f"预计扫描 {estimated_bytes} 字节，超过平台上限 "
                        f"{settings.data_agent_preflight_max_estimated_bytes}"
                    ),
                )
            )
        status = "fail" if any(item.severity == "error" for item in issues) else "pass"
        return PreflightReport(
            status=status,
            estimated_rows=estimated_rows,
            estimated_bytes=estimated_bytes,
            estimated_cost={
                "estimated_rows": estimated_rows,
                "estimated_bytes": estimated_bytes,
                "source": "database_explain",
            },
            issues=issues,
            explain_rows=rows[:50],
        )

    @staticmethod
    def _estimates(rows: list[dict[str, Any]]) -> tuple[int | None, int | None]:
        row_values: list[int] = []
        byte_values: list[int] = []
        for row in rows:
            for key, value in row.items():
                lowered = str(key).lower()
                if isinstance(value, int | float):
                    if lowered in {"rows", "estimated_rows", "rows_before_limit_at_least"}:
                        row_values.append(int(value))
                    if lowered in {"bytes", "estimated_bytes", "read_bytes"}:
                        byte_values.append(int(value))
                text = str(value or "")
                row_values.extend(int(match) for match in re.findall(r"\brows=(\d+)", text))
                byte_values.extend(int(match) for match in re.findall(r"\bbytes=(\d+)", text))
        return (max(row_values) if row_values else None, max(byte_values) if byte_values else None)

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
        started = time.monotonic()
        rows = await SQLExecutor(max_rows=max_rows).run_on_dsn(
            self._dsn(),
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
