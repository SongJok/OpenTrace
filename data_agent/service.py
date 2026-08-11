"""DataAgent 端到端服务编排。

该服务明确分离研究、计划、编译、策略、执行和结果回答状态；执行不会因为客户端
断开或模型重试而被隐式触发。
"""

from __future__ import annotations

from datetime import UTC, datetime

from data_agent.compiler import CandidateRanker, SQLGuard
from data_agent.contracts import (
    CandidateSQL,
    DataScope,
    EvidenceType,
    ExecutionMode,
    QueryRequest,
    QueryRun,
    RunState,
    deterministic_run_id,
    utc_now,
)
from data_agent.policy import ExecutionPolicy
from data_agent.ports import (
    AnswerSynthesizer,
    EvidenceProvider,
    InMemoryRunRepository,
    NullAnswerSynthesizer,
    QueryExecutor,
    ResultValidatorPort,
    RunRepository,
    SQLGenerator,
)
from data_agent.research import ResearchPlanner
from data_agent.result_validation import ResultValidator
from data_agent.semantics import LogicalPlanner
from data_agent.skills import SkillRegistry


class DataAgentService:
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
        result_validator: ResultValidatorPort | None = None,
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
        self.result_validator = result_validator or ResultValidator()

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
            if any(
                item.type == EvidenceType.SOURCE_POLICY
                and bool(item.payload.get("blocked") or item.payload.get("deny_sql_generation"))
                for item in evidence.items
            ):
                run.state = RunState.BLOCKED
                run.warnings.append("数据源治理策略禁止生成 SQL")
                run.trace.append({"stage": "blocked", "reason": "generation_policy_denied"})
                save_attempted = True
                return await self.repository.save(run)
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
            seen_sql: set[str] = set()
            for raw in raw_candidates:
                candidate = raw if isinstance(raw, CandidateSQL) else CandidateSQL(sql=str(raw))
                candidate.validation = self.sql_guard.validate(
                    candidate.sql, request=request, plan=run.logical_plan, evidence=evidence
                )
                if candidate.validation.normalized_sql:
                    candidate.sql = candidate.validation.normalized_sql
                fingerprint = " ".join(candidate.sql.lower().split())
                if fingerprint in seen_sql:
                    continue
                seen_sql.add(fingerprint)
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
            raise LookupError("data_agent_run_not_found")
        if run.state in {RunState.EXECUTING, RunState.COMPLETED}:
            return run
        if run.evidence is None or run.logical_plan is None:
            raise ValueError("data_agent_run_is_not_executable")
        candidate = (
            next((item for item in run.candidates if item.id == candidate_id), None)
            if candidate_id
            else run.selected_candidate()
        )
        if candidate is None:
            raise ValueError("data_agent_candidate_not_found")
        if not confirmed:
            run.state = RunState.BLOCKED
            run.warnings.append("执行必须显式确认")
            run.trace.append({"stage": "blocked", "reason": "confirmation_required"})
            return await self.repository.update(run)
        try:
            current_evidence = await self.evidence_provider.collect(
                scope,
                run.request.question,
                run.research_plan or self.research_planner.plan(run.request.question),
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
            run.completed_at = datetime.now(UTC)
            run.warnings.append(f"执行前证据重检失败：{str(exc)[:2000]}")
            run.trace.append({"stage": "evidence_refresh_failed", "error": str(exc)[:2000]})
            return await self.repository.update(run)
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
        preflight = getattr(self.query_executor, "preflight", None)
        if callable(preflight):
            try:
                run.preflight = await preflight(scope, candidate.sql, evidence=run.evidence)
            except (
                OSError,
                PermissionError,
                RuntimeError,
                TimeoutError,
                TypeError,
                ValueError,
            ) as exc:
                run.state = RunState.FAILED
                run.completed_at = datetime.now(UTC)
                run.warnings.append(f"执行前 EXPLAIN 预检失败：{str(exc)[:2000]}")
                run.trace.append({"stage": "preflight_failed", "error": str(exc)[:2000]})
                return await self.repository.update(run)
            candidate.validation.estimated_cost = dict(run.preflight.estimated_cost)
            run.trace.append(
                {
                    "stage": "preflight",
                    "status": run.preflight.status,
                    "estimated_rows": run.preflight.estimated_rows,
                    "estimated_bytes": run.preflight.estimated_bytes,
                    "issues": [item.model_dump(mode="json") for item in run.preflight.issues],
                }
            )
            if run.preflight.errors:
                run.state = RunState.BLOCKED
                run.warnings.extend(item.message for item in run.preflight.errors)
                return await self.repository.update(run)
        run.selected_candidate_id = candidate.id
        if not await self.repository.claim_execution(run.id, scope):
            latest = await self.repository.get(run.id, scope)
            if latest is not None:
                return latest
            raise LookupError("data_agent_run_not_found")
        run.state = RunState.EXECUTING
        run.updated_at = utc_now()
        await self.repository.update(run)
        try:
            result = await self.query_executor.execute(
                scope, candidate.sql, max_rows=run.request.max_rows, evidence=run.evidence
            )
            run.result = result
            run.result_validation = self.result_validator.validate(
                run.logical_plan, result, run.evidence
            )
            run.trace.append(
                {
                    "stage": "result_validation",
                    "status": run.result_validation.status,
                    "issues": [
                        item.model_dump(mode="json") for item in run.result_validation.issues
                    ],
                }
            )
            run.warnings.extend(item.message for item in run.result_validation.issues)
            if run.result_validation.errors:
                run.answer = None
                run.state = RunState.FAILED
            else:
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
            run.completed_at = datetime.now(UTC)
            run.warnings.append(f"SQL 执行失败：{str(exc)[:2000]}")
            run.trace.append({"stage": "execute_failed", "error": str(exc)[:2000]})
        run.updated_at = utc_now()
        return await self.repository.update(run)
