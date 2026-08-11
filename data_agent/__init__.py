"""独立的企业级 DataAgent 领域核心。

该包只依赖标准库、Pydantic 和 sqlglot。OpenTrace 的数据库、模型网关与 API
通过 ``data_agent.adapters`` 注入，避免 DataAgent 领域反向依赖对话运行时。
"""

from data_agent.contracts import (
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
from data_agent.service import DataAgentService

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
    "DataAgentService",
    "ValidationReport",
    "deterministic_run_id",
]
