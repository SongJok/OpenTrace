"""DataAgent 执行经验的 PostgreSQL 持久化适配器。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from data_agent.contracts import CandidateSQL, LearningRecord, QueryRun
from data_agent.learning import plan_pattern_key, result_signature, sql_structure_hash
from infra.config.settings import settings
from infra.storage.data_agent_models import DataAgentFailurePattern, DataAgentLearningPattern


class OpenTraceLearningRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _scope_key(run: QueryRun) -> str:
        return "__global__"

    @staticmethod
    def _statement(run: QueryRun, pattern_key: str):
        scope = run.request.scope
        evidence = run.evidence
        return select(DataAgentLearningPattern).where(
            DataAgentLearningPattern.user_id == scope.user_id,
            DataAgentLearningPattern.tenant_id == scope.tenant_id,
            DataAgentLearningPattern.workspace_id == scope.workspace_id,
            DataAgentLearningPattern.data_source_id == scope.data_source_id,
            DataAgentLearningPattern.scope_key == "__global__",
            DataAgentLearningPattern.pattern_key == pattern_key,
            DataAgentLearningPattern.schema_fingerprint
            == str(evidence.schema_fingerprint if evidence else ""),
            DataAgentLearningPattern.semantic_version
            == str(evidence.semantic_version if evidence else ""),
        )

    @staticmethod
    def _contract(pattern: DataAgentLearningPattern, reasons: list[str]) -> LearningRecord:
        return LearningRecord(
            pattern_key=pattern.pattern_key,
            status=pattern.status,
            confidence=float(pattern.confidence or 0.0),
            observation_count=pattern.observation_count,
            success_count=pattern.success_count,
            failure_count=pattern.failure_count,
            reusable=pattern.status == "trusted",
            reasons=reasons,
            evidence_ids=list(pattern.evidence_ids or []),
        )

    async def record_success(
        self,
        run: QueryRun,
        candidate: CandidateSQL,
        learning: LearningRecord,
    ) -> LearningRecord:
        if learning.status == "ineligible" or run.logical_plan is None or run.evidence is None:
            return learning
        pattern = await self.db.scalar(self._statement(run, learning.pattern_key).with_for_update())
        created = False
        if pattern is None:
            pattern = DataAgentLearningPattern(
                user_id=run.request.scope.user_id,
                tenant_id=run.request.scope.tenant_id,
                workspace_id=run.request.scope.workspace_id,
                scope_key=self._scope_key(run),
                data_source_id=run.request.scope.data_source_id,
                pattern_key=learning.pattern_key,
                question_examples=[run.request.question],
                logical_plan_json=run.logical_plan.model_dump(mode="json"),
                selected_sql=candidate.sql,
                sql_structure_hash=sql_structure_hash(candidate.sql, dialect=run.evidence.dialect),
                schema_fingerprint=run.evidence.schema_fingerprint or "",
                semantic_version=run.evidence.semantic_version or "",
                evidence_ids=run.logical_plan.evidence_ids,
                validation_summary=self._validation_summary(run, candidate),
                confidence=learning.confidence,
                observation_count=1,
                success_count=1,
                failure_count=0,
                status="observed",
                last_run_id=run.id,
                last_result_signature=(
                    result_signature(run.result.rows) if run.result is not None else None
                ),
                last_verified_at=datetime.now(UTC),
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(pattern)
                    await self.db.flush()
                created = True
            except IntegrityError:
                pattern = await self.db.scalar(
                    self._statement(run, learning.pattern_key).with_for_update()
                )
                if pattern is None:
                    raise
        if not created:
            if pattern.last_run_id == run.id:
                return self._contract(pattern, ["本次执行已记录，未重复累计经验"])
            pattern.observation_count += 1
            pattern.success_count += 1
            pattern.question_examples = list(
                dict.fromkeys([*(pattern.question_examples or []), run.request.question])
            )[-10:]
            pattern.logical_plan_json = run.logical_plan.model_dump(mode="json")
            pattern.selected_sql = candidate.sql
            pattern.sql_structure_hash = sql_structure_hash(
                candidate.sql, dialect=run.evidence.dialect
            )
            pattern.evidence_ids = run.logical_plan.evidence_ids
            pattern.validation_summary = self._validation_summary(run, candidate)
            pattern.confidence = max(float(pattern.confidence or 0.0), learning.confidence)
            pattern.last_run_id = run.id
            pattern.last_result_signature = (
                result_signature(run.result.rows) if run.result is not None else None
            )
            pattern.last_verified_at = datetime.now(UTC)

        if (
            pattern.success_count >= settings.data_agent_learning_trust_min_success
            and pattern.failure_count == 0
            and pattern.confidence >= settings.data_agent_learning_min_confidence
        ):
            pattern.status = "trusted"
        elif pattern.status != "rejected":
            pattern.status = "observed"
        await self.db.flush()
        return self._contract(
            pattern,
            [
                (
                    "已通过真实执行持续强化"
                    if pattern.status == "trusted"
                    else "已记录成功观察，达到重复成功阈值后才会成为可信经验"
                )
            ],
        )

    async def record_feedback(
        self,
        run: QueryRun,
        *,
        verdict: str,
        candidate_id: str | None,
        corrected_sql: str | None,
    ) -> LearningRecord | None:
        if run.logical_plan is None or run.evidence is None:
            return None
        key = plan_pattern_key(run.logical_plan)
        pattern = await self.db.scalar(self._statement(run, key).with_for_update())
        if pattern is None:
            return None
        pattern.observation_count += 1
        summary = dict(pattern.validation_summary or {})
        summary["last_feedback"] = {
            "verdict": verdict,
            "candidate_id": candidate_id,
            "corrected_sql_pending_review": corrected_sql,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        pattern.validation_summary = summary
        if verdict == "correct":
            pattern.success_count += 1
            if (
                pattern.success_count >= settings.data_agent_learning_trust_min_success
                and pattern.failure_count == 0
            ):
                pattern.status = "trusted"
        else:
            pattern.failure_count += 1
            pattern.status = "rejected"
            pattern.confidence = max(0.0, float(pattern.confidence or 0.0) - 0.25)
        await self.db.flush()
        return self._contract(pattern, ["人工反馈已更新经验可信状态"])

    async def record_failure(
        self,
        run: QueryRun,
        candidate: CandidateSQL,
        *,
        stage: str,
        error_codes: list[str],
    ) -> LearningRecord:
        if run.logical_plan is None or run.evidence is None:
            return LearningRecord(
                pattern_key="missing-plan",
                status="ineligible",
                failure_count=1,
                reasons=["失败运行缺少逻辑计划或版本化证据，未形成模式"],
            )
        pattern_key = plan_pattern_key(run.logical_plan)
        scope = run.request.scope
        schema_fingerprint = str(run.evidence.schema_fingerprint or "")
        semantic_version = str(run.evidence.semantic_version or "")
        normalized_stage = str(stage or "failed")[:64]
        statement = select(DataAgentFailurePattern).where(
            DataAgentFailurePattern.user_id == scope.user_id,
            DataAgentFailurePattern.tenant_id == scope.tenant_id,
            DataAgentFailurePattern.workspace_id == scope.workspace_id,
            DataAgentFailurePattern.data_source_id == scope.data_source_id,
            DataAgentFailurePattern.pattern_key == pattern_key,
            DataAgentFailurePattern.schema_fingerprint == schema_fingerprint,
            DataAgentFailurePattern.semantic_version == semantic_version,
            DataAgentFailurePattern.failure_stage == normalized_stage,
        )
        pattern = await self.db.scalar(statement.with_for_update())
        created = False
        if pattern is None:
            pattern = DataAgentFailurePattern(
                user_id=scope.user_id,
                tenant_id=scope.tenant_id,
                workspace_id=scope.workspace_id,
                data_source_id=scope.data_source_id,
                pattern_key=pattern_key,
                schema_fingerprint=schema_fingerprint,
                semantic_version=semantic_version,
                failure_stage=normalized_stage,
                error_codes=list(dict.fromkeys(error_codes))[:20],
                question_examples=[run.request.question],
                candidate_sql_hash=sql_structure_hash(candidate.sql, dialect=run.evidence.dialect),
                failure_count=1,
                last_run_id=run.id,
                last_failure_at=datetime.now(UTC),
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(pattern)
                    await self.db.flush()
                created = True
            except IntegrityError:
                pattern = await self.db.scalar(statement.with_for_update())
                if pattern is None:
                    raise
        if not created and pattern.last_run_id != run.id:
            pattern.failure_count += 1
            pattern.error_codes = list(dict.fromkeys([*(pattern.error_codes or []), *error_codes]))[
                :20
            ]
            pattern.question_examples = list(
                dict.fromkeys([*(pattern.question_examples or []), run.request.question])
            )[-10:]
            pattern.candidate_sql_hash = sql_structure_hash(
                candidate.sql, dialect=run.evidence.dialect
            )
            pattern.last_run_id = run.id
            pattern.last_failure_at = datetime.now(UTC)
        await self.db.flush()
        return LearningRecord(
            pattern_key=pattern_key,
            status="rejected",
            confidence=0.0,
            observation_count=pattern.failure_count,
            failure_count=pattern.failure_count,
            reusable=False,
            reasons=[f"已记录 {normalized_stage} 失败模式，禁止作为成功经验复用"],
            evidence_ids=list(run.logical_plan.evidence_ids),
        )

    @staticmethod
    def _validation_summary(run: QueryRun, candidate: CandidateSQL) -> dict:
        return {
            "sql_validation": candidate.validation.model_dump(mode="json"),
            "preflight": run.preflight.model_dump(mode="json") if run.preflight else {},
            "result_validation": (
                run.result_validation.model_dump(mode="json") if run.result_validation else {}
            ),
        }
