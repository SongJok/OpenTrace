"""Text2SQL Run 的 OpenTrace ORM 持久化适配器。"""

from __future__ import annotations

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from infra.storage.text2sql_models import Text2SQLRunEvent, Text2SQLRunRecord
from text2sql.contracts import DataScope, QueryRun, RunState


class OpenTraceRunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _scope_filter(statement, scope: DataScope):
        scoped = statement.where(
            Text2SQLRunRecord.user_id == scope.user_id,
            Text2SQLRunRecord.tenant_id == scope.tenant_id,
            Text2SQLRunRecord.workspace_id == scope.workspace_id,
            Text2SQLRunRecord.data_source_id == scope.data_source_id,
        )
        if scope.project_id is None:
            return scoped.where(Text2SQLRunRecord.project_id.is_(None))
        return scoped.where(Text2SQLRunRecord.project_id == scope.project_id)

    @staticmethod
    def _record_to_run(record: Text2SQLRunRecord) -> QueryRun:
        return QueryRun.model_validate(
            {
                "id": record.id,
                "request": record.request_json,
                "state": record.state,
                "research_plan": record.research_plan_json or None,
                "evidence": record.evidence_json or None,
                "logical_plan": record.logical_plan_json or None,
                "candidates": record.candidates_json or [],
                "selected_candidate_id": record.selected_candidate_id,
                "policy": record.policy_json or None,
                "result": record.result_json or None,
                "answer": record.answer,
                "warnings": record.warnings_json or [],
                "trace": record.trace_json or [],
                "created_at": record.created_at,
                "updated_at": record.updated_at,
                "completed_at": record.completed_at,
            }
        )

    async def _append_events(self, run: QueryRun, previous_count: int = 0) -> None:
        events = run.trace[previous_count:]
        if not events:
            return
        current = await self.db.scalar(
            select(func.max(Text2SQLRunEvent.sequence_number)).where(
                Text2SQLRunEvent.run_id == run.id
            )
        )
        sequence = int(current or 0)
        for event in events:
            sequence += 1
            payload = dict(event) if isinstance(event, dict) else {"value": str(event)}
            event_type = str(payload.pop("stage", "trace"))
            self.db.add(
                Text2SQLRunEvent(
                    run_id=run.id,
                    sequence_number=sequence,
                    event_type=event_type,
                    payload=payload,
                )
            )

    @staticmethod
    def _apply(run: QueryRun, record: Text2SQLRunRecord) -> None:
        payload = run.model_dump(mode="json")
        record.question = run.request.question
        record.mode = run.request.mode.value
        record.state = run.state.value
        record.request_json = payload["request"]
        record.research_plan_json = payload.get("research_plan") or {}
        record.evidence_json = payload.get("evidence") or {}
        record.logical_plan_json = payload.get("logical_plan") or {}
        record.candidates_json = payload.get("candidates") or []
        record.selected_candidate_id = run.selected_candidate_id
        record.policy_json = payload.get("policy") or {}
        record.result_json = payload.get("result") or {}
        record.answer = run.answer
        record.warnings_json = run.warnings
        record.trace_json = run.trace
        record.schema_fingerprint = run.evidence.schema_fingerprint if run.evidence else None
        record.semantic_version = run.evidence.semantic_version if run.evidence else None
        record.completed_at = run.completed_at

    async def save(self, run: QueryRun) -> QueryRun:
        record = Text2SQLRunRecord(
            id=run.id,
            user_id=run.request.scope.user_id,
            tenant_id=run.request.scope.tenant_id,
            workspace_id=run.request.scope.workspace_id,
            project_id=run.request.scope.project_id,
            data_source_id=run.request.scope.data_source_id,
        )
        self._apply(run, record)
        self.db.add(record)
        try:
            await self.db.flush()
            await self._append_events(run)
            return run
        except IntegrityError:
            await self.db.rollback()
            existing = await self.get(run.id, run.request.scope)
            if existing is not None:
                return existing
            raise

    async def get(self, run_id: str, scope: DataScope) -> QueryRun | None:
        statement = self._scope_filter(
            select(Text2SQLRunRecord).where(Text2SQLRunRecord.id == run_id), scope
        )
        record = await self.db.scalar(statement)
        return self._record_to_run(record) if record else None

    async def update(self, run: QueryRun) -> QueryRun:
        record = await self.db.scalar(
            self._scope_filter(
                select(Text2SQLRunRecord).where(Text2SQLRunRecord.id == run.id), run.request.scope
            )
        )
        if record is None:
            raise LookupError("text2sql_run_not_found")
        previous_count = len(record.trace_json or [])
        self._apply(run, record)
        await self.db.flush()
        await self._append_events(run, previous_count)
        return run

    async def claim_execution(self, run_id: str, scope: DataScope) -> bool:
        statement = (
            update(Text2SQLRunRecord)
            .where(
                Text2SQLRunRecord.id == run_id,
                Text2SQLRunRecord.user_id == scope.user_id,
                Text2SQLRunRecord.tenant_id == scope.tenant_id,
                Text2SQLRunRecord.workspace_id == scope.workspace_id,
                Text2SQLRunRecord.data_source_id == scope.data_source_id,
                (
                    Text2SQLRunRecord.project_id.is_(None)
                    if scope.project_id is None
                    else Text2SQLRunRecord.project_id == scope.project_id
                ),
                Text2SQLRunRecord.state.in_(
                    [RunState.READY.value, RunState.BLOCKED.value, RunState.FAILED.value]
                ),
            )
            .values(state=RunState.EXECUTING.value)
        )
        result = await self.db.execute(statement)
        return bool(result.rowcount and result.rowcount > 0)
