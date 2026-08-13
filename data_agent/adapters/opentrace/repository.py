"""DataAgent Run 的 OpenTrace ORM 持久化适配器。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from data_agent.contracts import DataScope, QueryRun, RunState
from data_agent.learning import result_signature, sql_structure_hash
from infra.config.settings import settings
from infra.storage.data_agent_models import (
    DataAgentResultArtifact,
    DataAgentRunEvent,
    DataAgentRunRecord,
)


class OpenTraceRunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _scope_filter(statement, scope: DataScope):
        return statement.where(
            DataAgentRunRecord.user_id == scope.user_id,
            DataAgentRunRecord.tenant_id == scope.tenant_id,
            DataAgentRunRecord.workspace_id == scope.workspace_id,
            DataAgentRunRecord.data_source_id == scope.data_source_id,
        )

    @staticmethod
    def _record_to_run(record: DataAgentRunRecord) -> QueryRun:
        request_payload = dict(record.request_json or {})
        if record.source_decision_json and not request_payload.get("source_decision"):
            request_payload["source_decision"] = record.source_decision_json
        return QueryRun.model_validate(
            {
                "id": record.id,
                "request": request_payload,
                "state": record.state,
                "research_plan": record.research_plan_json or None,
                "evidence": record.evidence_json or None,
                "logical_plan": record.logical_plan_json or None,
                "candidates": record.candidates_json or [],
                "selected_candidate_id": record.selected_candidate_id,
                "policy": record.policy_json or None,
                "preflight": record.preflight_json or None,
                "result": record.result_json or None,
                "result_validation": record.result_validation_json or None,
                "answer": record.answer,
                "answer_citations": record.answer_citations_json or [],
                "answer_metadata": record.answer_metadata_json or {},
                "learning": record.learning_json or None,
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
            select(func.max(DataAgentRunEvent.sequence_number)).where(
                DataAgentRunEvent.run_id == run.id
            )
        )
        sequence = int(current or 0)
        for event in events:
            sequence += 1
            payload = dict(event) if isinstance(event, dict) else {"value": str(event)}
            event_type = str(payload.pop("stage", "trace"))
            self.db.add(
                DataAgentRunEvent(
                    run_id=run.id,
                    sequence_number=sequence,
                    event_type=event_type,
                    payload=payload,
                )
            )

    @staticmethod
    def _apply(run: QueryRun, record: DataAgentRunRecord) -> None:
        payload = run.model_dump(mode="json")
        record.question = run.request.question
        record.run_purpose = run.request.run_purpose
        record.mode = run.request.mode.value
        record.state = run.state.value
        record.request_json = payload["request"]
        record.research_plan_json = payload.get("research_plan") or {}
        record.evidence_json = payload.get("evidence") or {}
        record.logical_plan_json = payload.get("logical_plan") or {}
        record.candidates_json = payload.get("candidates") or []
        record.selected_candidate_id = run.selected_candidate_id
        record.policy_json = payload.get("policy") or {}
        record.preflight_json = payload.get("preflight") or {}
        record.result_json = payload.get("result") or {}
        record.result_validation_json = payload.get("result_validation") or {}
        record.answer = run.answer
        record.source_decision_json = (
            run.request.source_decision.model_dump(mode="json")
            if run.request.source_decision
            else {}
        )
        record.answer_citations_json = payload.get("answer_citations") or []
        record.answer_metadata_json = payload.get("answer_metadata") or {}
        record.learning_json = payload.get("learning") or {}
        record.warnings_json = run.warnings
        record.trace_json = run.trace
        record.schema_fingerprint = run.evidence.schema_fingerprint if run.evidence else None
        record.semantic_version = run.evidence.semantic_version if run.evidence else None
        record.completed_at = run.completed_at

    async def save(self, run: QueryRun) -> QueryRun:
        record = DataAgentRunRecord(
            id=run.id,
            user_id=run.request.scope.user_id,
            tenant_id=run.request.scope.tenant_id,
            workspace_id=run.request.scope.workspace_id,
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
            select(DataAgentRunRecord).where(DataAgentRunRecord.id == run_id), scope
        )
        record = await self.db.scalar(statement)
        return self._record_to_run(record) if record else None

    async def update(self, run: QueryRun) -> QueryRun:
        record = await self.db.scalar(
            self._scope_filter(
                select(DataAgentRunRecord).where(DataAgentRunRecord.id == run.id), run.request.scope
            )
        )
        if record is None:
            raise LookupError("data_agent_run_not_found")
        previous_count = len(record.trace_json or [])
        self._apply(run, record)
        await self.db.flush()
        await self._persist_result_artifact(run)
        await self._append_events(run, previous_count)
        return run

    async def _persist_result_artifact(self, run: QueryRun) -> None:
        """快照只首次写入，后续恢复不能覆盖既有审计事实。"""

        result = run.result
        candidate = run.selected_candidate()
        if result is None or candidate is None or not result.snapshot_id:
            return
        existing = await self.db.get(DataAgentResultArtifact, result.snapshot_id)
        if existing is not None:
            return
        evidence = run.evidence
        self.db.add(
            DataAgentResultArtifact(
                id=result.snapshot_id,
                run_id=run.id,
                user_id=run.request.scope.user_id,
                tenant_id=run.request.scope.tenant_id,
                workspace_id=run.request.scope.workspace_id,
                data_source_id=run.request.scope.data_source_id,
                sql_structure_hash=sql_structure_hash(
                    candidate.sql, dialect=evidence.dialect if evidence else ""
                ),
                result_signature=result_signature(result.rows),
                schema_fingerprint=evidence.schema_fingerprint if evidence else None,
                semantic_version=evidence.semantic_version if evidence else None,
                returned_rows=result.returned_rows,
                total_rows=result.total_rows,
                truncated=result.truncated,
                columns_json=list(result.columns),
                validation_json=(
                    run.result_validation.model_dump(mode="json") if run.result_validation else {}
                ),
                freshness_json=dict(result.freshness),
                expires_at=datetime.now(UTC)
                + timedelta(days=max(1, int(settings.enterprise_default_retention_days))),
            )
        )
        await self.db.flush()

    async def claim_execution(self, run_id: str, scope: DataScope) -> bool:
        statement = (
            update(DataAgentRunRecord)
            .where(
                DataAgentRunRecord.id == run_id,
                DataAgentRunRecord.user_id == scope.user_id,
                DataAgentRunRecord.tenant_id == scope.tenant_id,
                DataAgentRunRecord.workspace_id == scope.workspace_id,
                DataAgentRunRecord.data_source_id == scope.data_source_id,
                DataAgentRunRecord.state.in_(
                    [RunState.READY.value, RunState.BLOCKED.value, RunState.FAILED.value]
                ),
            )
            .values(state=RunState.EXECUTING.value)
        )
        result = await self.db.execute(statement)
        return bool(result.rowcount and result.rowcount > 0)
