"""DataAgent 核心依赖的端口定义。"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from data_agent.contracts import (
    AnswerCitation,
    CandidateSQL,
    DataScope,
    EvidenceBundle,
    ExecutionResult,
    LearningRecord,
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
        self,
        request: QueryRequest,
        plan: LogicalQueryPlan,
        result: ExecutionResult,
        *,
        evidence: EvidenceBundle,
        citations: list[AnswerCitation],
        result_validation: ResultValidationReport,
    ) -> str: ...


class RunRepository(Protocol):
    async def save(self, run: QueryRun) -> QueryRun: ...

    async def get(self, run_id: str, scope: DataScope) -> QueryRun | None: ...

    async def update(self, run: QueryRun) -> QueryRun: ...

    async def claim_execution(self, run_id: str, scope: DataScope) -> bool: ...


class LearningRepository(Protocol):
    async def record_success(
        self,
        run: QueryRun,
        candidate: CandidateSQL,
        learning: LearningRecord,
    ) -> LearningRecord: ...

    async def record_feedback(
        self,
        run: QueryRun,
        *,
        verdict: str,
        candidate_id: str | None,
        corrected_sql: str | None,
    ) -> LearningRecord | None: ...

    async def record_failure(
        self,
        run: QueryRun,
        candidate: CandidateSQL,
        *,
        stage: str,
        error_codes: list[str],
    ) -> LearningRecord: ...


class NullAnswerSynthesizer:
    async def synthesize(
        self,
        request: QueryRequest,
        plan: LogicalQueryPlan,
        result: ExecutionResult,
        *,
        evidence: EvidenceBundle,
        citations: list[AnswerCitation],
        result_validation: ResultValidationReport,
    ) -> str:
        status = "已返回完整结果" if not result.truncated else "结果已达到返回上限，未声称完整返回"
        labels = " ".join(f"[{item.label}]" for item in citations[:6])
        suffix = f" 证据：{labels}" if labels else ""
        validation_note = ""
        if result_validation.issues:
            messages = "；".join(item.message for item in result_validation.issues[:3])
            validation_note = f" 结果校验提示：{messages}。"
        return (
            f"查询完成，共返回 {result.returned_rows} 行，{status}。" f"{validation_note}{suffix}"
        )


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
