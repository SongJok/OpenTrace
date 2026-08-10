"""Text2SQL 端到端服务编排。

该服务明确分离研究、计划、编译、策略、执行和结果回答状态；执行不会因为客户端
断开或模型重试而被隐式触发。
"""

from __future__ import annotations

from datetime import UTC, datetime

from text2sql.compiler import CandidateRanker, SQLGuard
from text2sql.contracts import (
    CandidateSQL,
    DataScope,
    ExecutionMode,
    QueryRequest,
    QueryRun,
    RunState,
    deterministic_run_id,
    utc_now,
)
from text2sql.policy import ExecutionPolicy
from text2sql.ports import (
    AnswerSynthesizer,
    EvidenceProvider,
    InMemoryRunRepository,
    NullAnswerSynthesizer,
    QueryExecutor,
    RunRepository,
    SQLGenerator,
)
from text2sql.research import ResearchPlanner
from text2sql.semantics import LogicalPlanner
from text2sql.skills import SkillRegistry


class Text2SQLService:
    def __init__(
        self,
        *,
        evidence_provider: EvidenceProvider,
        sql_generator: SQLGenerator,
        query_executor: QueryExecutor | None = None,
        answer_synthesizer: AnswerSynthesizer | None = None,
        repository: RunRepository | None = None,
        research_planner: ResearchPlanner | None = None,
        logical_planner: LogicalPlanner | None = None,
        skill_registry: SkillRegistry | None = None,
        sql_guard: SQLGuard | None = None,
        execution_policy: ExecutionPolicy | None = None,
    ) -> None:
        self.evidence_provider = evidence_provider
        self.sql_generator = sql_generator
        self.query_executor = query_executor
        self.answer_synthesizer = answer_synthesizer or NullAnswerSynthesizer()
        self.repository = repository or InMemoryRunRepository()
        self.research_planner = research_planner or ResearchPlanner()
        self.logical_planner = logical_planner or LogicalPlanner()
        self.skill_registry = skill_registry or SkillRegistry()
        self.sql_guard = sql_guard or SQLGuard()
        self.execution_policy = execution_policy or ExecutionPolicy()

    async def create(self, request: QueryRequest) -> QueryRun:
        run = QueryRun(id=deterministic_run_id(request), request=request)
        persisted = False
        save_attempted = False
        run.research_plan = self.research_planner.plan(request.question)
        run.trace.append(
            {
                "stage": "research_plan",
                "steps": [item.source.value for item in run.research_plan.steps],
            }
        )
        try:
            evidence = await self.evidence_provider.collect(
                request.scope, request.question, run.research_plan
            )
            run.evidence = evidence
            run.trace.append(
                {
                    "stage": "evidence",
                    "count": len(evidence.items),
                    "schema_fingerprint": evidence.schema_fingerprint,
                }
            )
            run.logical_plan = self.logical_planner.plan(request, evidence)
            run.logical_plan = self.skill_registry.enrich(run.logical_plan)
            run.trace.append(
                {
                    "stage": "logical_plan",
                    "confidence": run.logical_plan.confidence,
                    "missing": run.logical_plan.missing_information,
                }
            )
            if run.logical_plan.needs_clarification:
                run.state = RunState.NEEDS_CLARIFICATION
                run.warnings.extend(run.logical_plan.missing_information)
                run.trace.append(
                    {
                        "stage": "clarification",
                        "question": run.logical_plan.clarification_question,
                    }
                )
                save_attempted = True
                return await self.repository.save(run)
            raw_candidates = await self.sql_generator.generate(request, run.logical_plan, evidence)
            candidates: list[CandidateSQL] = []
            for raw in raw_candidates:
                candidate = raw if isinstance(raw, CandidateSQL) else CandidateSQL(sql=str(raw))
                candidate.validation = self.sql_guard.validate(
                    candidate.sql, request=request, plan=run.logical_plan, evidence=evidence
                )
                if candidate.validation.normalized_sql:
                    candidate.sql = candidate.validation.normalized_sql
                candidates.append(candidate)
            run.candidates = CandidateRanker().rank(candidates, run.logical_plan)
            viable = [item for item in run.candidates if not item.validation.errors]
            run.trace.append(
                {
                    "stage": "compiled",
                    "candidate_count": len(run.candidates),
                    "viable_count": len(viable),
                    "validation_statuses": [item.validation.status for item in run.candidates],
                }
            )
            if not viable:
                run.state = RunState.BLOCKED
                run.warnings.append("没有候选 SQL 通过安全和语义编译")
                run.trace.append({"stage": "blocked", "reason": "no_viable_candidate"})
                save_attempted = True
                return await self.repository.save(run)
            run.selected_candidate_id = viable[0].id
            run.policy = self.execution_policy.decide(
                request, run.logical_plan, viable[0].validation, evidence
            )
            run.trace.append(
                {
                    "stage": "policy",
                    "allowed": run.policy.allowed,
                    "requires_confirmation": run.policy.requires_confirmation,
                    "risk_level": run.policy.risk_level,
                    "reasons": run.policy.reasons,
                }
            )
            run.state = RunState.READY
            run.warnings.extend(
                item.message for item in viable[0].validation.issues if item.severity == "warning"
            )
            save_attempted = True
            run = await self.repository.save(run)
            persisted = True
            if (
                request.mode == ExecutionMode.EXECUTE_AND_ANSWER
                and request.confirmed
                and run.policy is not None
                and run.policy.allowed
            ):
                return await self.execute(run.id, request.scope, confirmed=True)
            return run
        except (
            LookupError,
            OSError,
            PermissionError,
            RuntimeError,
            TimeoutError,
            TypeError,
            ValueError,
        ) as exc:
            run.state = RunState.FAILED
            run.warnings.append(str(exc)[:2000])
            run.trace.append({"stage": "failed", "error": str(exc)[:2000]})
            if persisted:
                return await self.repository.update(run)
            if save_attempted:
                raise
            return await self.repository.save(run)

    async def execute(
        self,
        run_id: str,
        scope: DataScope,
        *,
        candidate_id: str | None = None,
        confirmed: bool = False,
    ) -> QueryRun:
        run = await self.repository.get(run_id, scope)
        if run is None:
            raise LookupError("text2sql_run_not_found")
        if run.state in {RunState.EXECUTING, RunState.COMPLETED}:
            return run
        if run.evidence is None or run.logical_plan is None:
            raise ValueError("text2sql_run_is_not_executable")
        candidate = (
            next((item for item in run.candidates if item.id == candidate_id), None)
            if candidate_id
            else run.selected_candidate()
        )
        if candidate is None:
            raise ValueError("text2sql_candidate_not_found")
        if not confirmed:
            run.state = RunState.BLOCKED
            run.warnings.append("执行必须显式确认")
            run.trace.append({"stage": "blocked", "reason": "confirmation_required"})
            return await self.repository.update(run)
        current_evidence = await self.evidence_provider.collect(
            scope,
            run.request.question,
            run.research_plan or self.research_planner.plan(run.request.question),
        )
        if run.evidence.schema_fingerprint != current_evidence.schema_fingerprint and (
            run.evidence.schema_fingerprint or current_evidence.schema_fingerprint
        ):
            run.state = RunState.BLOCKED
            run.warnings.append("Schema 已变化，必须重新生成 SQL 后才能执行")
            run.trace.append({"stage": "blocked", "reason": "schema_changed"})
            return await self.repository.update(run)
        candidate.validation = self.sql_guard.validate(
            candidate.sql,
            request=run.request,
            plan=run.logical_plan,
            evidence=current_evidence,
        )
        if candidate.validation.errors:
            run.state = RunState.BLOCKED
            run.warnings.append("最新数据目录下候选 SQL 未通过安全和语义编译")
            run.trace.append({"stage": "blocked", "reason": "revalidation_failed"})
            return await self.repository.update(run)
        if candidate.validation.normalized_sql:
            candidate.sql = candidate.validation.normalized_sql
        run.evidence = current_evidence
        decision = self.execution_policy.decide(
            run.request.model_copy(
                update={"confirmed": True, "mode": ExecutionMode.EXECUTE_AND_ANSWER}
            ),
            run.logical_plan,
            candidate.validation,
            run.evidence,
        )
        run.policy = decision
        if not decision.allowed:
            run.state = RunState.BLOCKED
            run.warnings.extend(decision.reasons)
            run.trace.append(
                {
                    "stage": "blocked",
                    "reason": "policy_denied",
                    "risk_level": decision.risk_level,
                    "reasons": decision.reasons,
                }
            )
            return await self.repository.update(run)
        if self.query_executor is None:
            run.state = RunState.BLOCKED
            run.warnings.append("平台未配置 QueryExecutor，不能执行 SQL")
            run.trace.append({"stage": "blocked", "reason": "executor_unavailable"})
            return await self.repository.update(run)
        run.selected_candidate_id = candidate.id
        if not await self.repository.claim_execution(run.id, scope):
            latest = await self.repository.get(run.id, scope)
            if latest is not None:
                return latest
            raise LookupError("text2sql_run_not_found")
        run.state = RunState.EXECUTING
        run.updated_at = utc_now()
        await self.repository.update(run)
        try:
            result = await self.query_executor.execute(
                scope, candidate.sql, max_rows=run.request.max_rows, evidence=run.evidence
            )
            run.result = result
            run.answer = await self.answer_synthesizer.synthesize(
                run.request, run.logical_plan, result
            )
            run.state = RunState.COMPLETED
            run.completed_at = datetime.now(UTC)
            run.trace.append(
                {
                    "stage": "executed",
                    "returned_rows": result.returned_rows,
                    "truncated": result.truncated,
                }
            )
        except (
            OSError,
            PermissionError,
            RuntimeError,
            TimeoutError,
            TypeError,
            ValueError,
        ) as exc:
            run.state = RunState.FAILED
            run.warnings.append(f"SQL 执行失败：{str(exc)[:2000]}")
            run.trace.append({"stage": "execute_failed", "error": str(exc)[:2000]})
        run.updated_at = utc_now()
        return await self.repository.update(run)
