"""独立的企业级 Text2SQL 领域核心。

该包只依赖标准库、Pydantic 和 sqlglot。OpenTrace 的数据库、模型网关与 API
通过 ``text2sql.adapters`` 注入，避免 Text2SQL 领域反向依赖对话运行时。
"""

from text2sql.contracts import (
    CandidateSQL,
    DataScope,
    EvidenceBundle,
    EvidenceItem,
    ExecutionMode,
    LogicalQueryPlan,
    QueryRequest,
    QueryRun,
    RunState,
    ValidationReport,
    deterministic_run_id,
)
from text2sql.service import Text2SQLService

__all__ = [
    "CandidateSQL",
    "DataScope",
    "EvidenceBundle",
    "EvidenceItem",
    "ExecutionMode",
    "LogicalQueryPlan",
    "QueryRequest",
    "QueryRun",
    "RunState",
    "Text2SQLService",
    "ValidationReport",
    "deterministic_run_id",
]
