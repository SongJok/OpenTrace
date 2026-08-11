"""DataAgent 核心依赖的端口定义。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from data_agent.contracts import (
    CandidateSQL,
    DataScope,
    EvidenceBundle,
    ExecutionResult,
    LogicalQueryPlan,
    QueryRequest,
    QueryRun,
    ResearchPlan,
    ResultValidationReport,
    RunState,
)


class EvidenceProvider(Protocol):
    async def collect(
        self, scope: DataScope, question: str, plan: ResearchPlan
    ) -> EvidenceBundle: ...


class SQLGenerator(Protocol):
    async def generate(
        self,
        request: QueryRequest,
        logical_plan: LogicalQueryPlan,
        evidence: EvidenceBundle,
    ) -> Sequence[CandidateSQL | str]: ...


class QueryExecutor(Protocol):
    async def execute(
        self,
        scope: DataScope,
        sql: str,
        *,
        max_rows: int,
        evidence: EvidenceBundle,
    ) -> ExecutionResult: ...


class ResultValidatorPort(Protocol):
    def validate(
        self,
        plan: LogicalQueryPlan,
        result: ExecutionResult,
        evidence: EvidenceBundle,
    ) -> ResultValidationReport: ...


class AnswerSynthesizer(Protocol):
    async def synthesize(
        self, request: QueryRequest, plan: LogicalQueryPlan, result: ExecutionResult
    ) -> str: ...


class RunRepository(Protocol):
    async def save(self, run: QueryRun) -> QueryRun: ...

    async def get(self, run_id: str, scope: DataScope) -> QueryRun | None: ...

    async def update(self, run: QueryRun) -> QueryRun: ...

    async def claim_execution(self, run_id: str, scope: DataScope) -> bool: ...


class NullAnswerSynthesizer:
    async def synthesize(
        self, request: QueryRequest, plan: LogicalQueryPlan, result: ExecutionResult
    ) -> str:
        status = "已返回完整结果" if not result.truncated else "结果已达到返回上限，未声称完整返回"
        return f"查询完成，共返回 {result.returned_rows} 行，{status}。"


class InMemoryRunRepository:
    """测试和本地开发用的最小持久化端口实现。"""

    def __init__(self) -> None:
        self._runs: dict[str, QueryRun] = {}

    async def save(self, run: QueryRun) -> QueryRun:
        existing = self._runs.get(run.id)
        if existing is not None:
            return existing
        self._runs[run.id] = run
        return run

    async def get(self, run_id: str, scope: DataScope) -> QueryRun | None:
        run = self._runs.get(run_id)
        if run is None or run.request.scope != scope:
            return None
        return run

    async def update(self, run: QueryRun) -> QueryRun:
        self._runs[run.id] = run
        return run

    async def claim_execution(self, run_id: str, scope: DataScope) -> bool:
        run = await self.get(run_id, scope)
        if run is None or run.state in {RunState.EXECUTING, RunState.COMPLETED}:
            return False
        run.state = RunState.EXECUTING
        return True
