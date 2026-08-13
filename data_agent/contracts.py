"""DataAgent 平台的稳定领域契约。

模型输出、工具返回和数据库执行结果都必须先落入这些结构化契约，再进入下一阶段。
任何阶段都不能通过自由文本隐式传递安全边界或业务口径。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ExecutionMode(str, Enum):
    SQL_ONLY = "sql_only"
    EXECUTE_AND_ANSWER = "execute_and_answer"


class RunState(str, Enum):
    RESEARCHING = "researching"
    NEEDS_CLARIFICATION = "needs_clarification"
    READY = "ready"
    BLOCKED = "blocked"
    EXECUTING = "executing"
    COMPLETED = "completed"
    FAILED = "failed"


class EvidenceType(str, Enum):
    SCHEMA = "schema"
    COLUMN_PROFILE = "column_profile"
    METRIC = "metric"
    ENTITY = "entity"
    RELATIONSHIP = "relationship"
    SQL_ASSET = "sql_asset"
    BUSINESS_PROCESS = "business_process"
    BUSINESS_RULE = "business_rule"
    POLICY = "policy"
    REPORT = "report"
    LINEAGE = "lineage"
    KNOWLEDGE = "knowledge"
    DATA_QUALITY = "data_quality"
    EXECUTION_MEMORY = "execution_memory"
    FAILURE_MEMORY = "failure_memory"
    SKILL = "skill"
    SOURCE_POLICY = "source_policy"


class Authority(str, Enum):
    LIVE_SYSTEM = "live_system"
    GOVERNED = "governed"
    VERIFIED = "verified"
    CONTEXTUAL = "contextual"
    INFERRED = "inferred"
    UNVERIFIED = "unverified"

    @property
    def weight(self) -> float:
        return {
            Authority.LIVE_SYSTEM: 1.0,
            Authority.GOVERNED: 0.98,
            Authority.VERIFIED: 0.90,
            Authority.CONTEXTUAL: 0.65,
            Authority.INFERRED: 0.40,
            Authority.UNVERIFIED: 0.20,
        }[self]


class DataScope(ContractModel):
    user_id: str = Field(..., min_length=1, max_length=128)
    tenant_id: str = Field(default="default", min_length=1, max_length=128)
    workspace_id: str = Field(default="default", min_length=1, max_length=128)
    data_source_id: str = Field(..., min_length=1, max_length=128)


class DataSourceCandidate(ContractModel):
    data_source_id: str
    name: str
    source_type: str
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)
    trust_score: float = Field(default=0.0, ge=0.0, le=1.0)
    blocked: bool = False
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    matched_terms: list[str] = Field(default_factory=list)


class DataSourceDecision(ContractModel):
    status: str = Field(pattern="^(selected|needs_clarification|no_source)$")
    question: str
    selected_data_source_id: str | None = None
    selected_data_source_name: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reason: str = ""
    candidates: list[DataSourceCandidate] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_selection(self) -> DataSourceDecision:
        if self.status == "selected" and not self.selected_data_source_id:
            raise ValueError("selected_data_source_id is required when source is selected")
        if self.status != "selected" and (
            self.selected_data_source_id or self.selected_data_source_name
        ):
            raise ValueError("unselected source decision cannot carry a selected data source")
        return self


class QueryRequest(ContractModel):
    question: str = Field(..., min_length=1, max_length=8192)
    scope: DataScope
    run_purpose: str = Field(default="online", pattern="^(online|evaluation)$")
    mode: ExecutionMode = ExecutionMode.SQL_ONLY
    clarification_context: str | None = Field(default=None, max_length=4000)
    candidate_count: int = Field(default=3, ge=1, le=5)
    max_rows: int = Field(default=100, ge=1, le=10000)
    confirmed: bool = False
    requested_tables: list[str] = Field(default_factory=list, max_length=100)
    requested_output: str | None = Field(default=None, max_length=1000)
    timezone: str = Field(default="Asia/Shanghai", min_length=1, max_length=64)
    as_of: datetime | None = None
    minimum_confidence: float = Field(default=0.75, ge=0.0, le=1.0)
    idempotency_key: str | None = Field(default=None, max_length=255)
    source_decision: DataSourceDecision | None = None

    @model_validator(mode="after")
    def validate_source_decision(self) -> QueryRequest:
        if self.source_decision is None:
            return self
        if self.source_decision.status != "selected":
            raise ValueError("query request requires a selected data source decision")
        if self.source_decision.selected_data_source_id != self.scope.data_source_id:
            raise ValueError("source decision does not match query data source scope")
        return self


def deterministic_run_id(request: QueryRequest) -> str:
    """为带幂等键的请求生成跨进程稳定的运行 ID。"""

    if not request.idempotency_key:
        return str(uuid4())
    scope = request.scope
    seed = ":".join(
        (
            scope.user_id,
            scope.tenant_id,
            scope.workspace_id,
            scope.data_source_id,
            request.idempotency_key,
        )
    )
    return str(uuid5(NAMESPACE_URL, seed))


class ResearchStep(ContractModel):
    source: EvidenceType
    reason: str = Field(..., min_length=1, max_length=500)
    required: bool = True
    max_items: int = Field(default=20, ge=1, le=200)


class ResearchPlan(ContractModel):
    steps: list[ResearchStep] = Field(default_factory=list)
    budget: int = Field(default=12, ge=1, le=50)
    stop_conditions: list[str] = Field(default_factory=list)


class EvidenceItem(ContractModel):
    id: str = Field(default_factory=lambda: str(uuid4()), max_length=128)
    type: EvidenceType
    source_id: str = Field(..., min_length=1, max_length=255)
    source_name: str = Field(default="", max_length=255)
    authority: Authority = Authority.CONTEXTUAL
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    version: str | None = Field(default=None, max_length=128)
    scope: dict[str, str] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    citation: str | None = Field(default=None, max_length=2000)
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    sensitive: bool = False


class EvidenceBundle(ContractModel):
    items: list[EvidenceItem] = Field(default_factory=list)
    schema_fingerprint: str | None = None
    semantic_version: str | None = None
    dialect: str = "mysql"
    database_name: str = ""
    table_columns: dict[str, list[str]] = Field(default_factory=dict)
    data_freshness: dict[str, Any] = Field(default_factory=dict)
    authority_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    collection_warnings: list[str] = Field(default_factory=list)

    def of_type(self, item_type: EvidenceType) -> list[EvidenceItem]:
        return [item for item in self.items if item.type == item_type]

    def payloads(self, item_type: EvidenceType) -> list[dict[str, Any]]:
        return [item.payload for item in self.of_type(item_type)]

    @property
    def highest_authority(self) -> float:
        if not self.items:
            return 0.0
        return max(item.authority.weight * item.confidence for item in self.items)


class MetricSpec(ContractModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    formula: str = ""
    aggregation: str | None = None
    underlying_columns: list[str] = Field(default_factory=list)
    required_filters: list[str] = Field(default_factory=list)
    grain: str | None = None
    time_field: str | None = None
    unit: str | None = None
    owner: str | None = None
    business_domain: str | None = None
    version: int | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    source_evidence_id: str | None = None


class DimensionSpec(ContractModel):
    name: str
    column: str | None = None
    table: str | None = None
    hierarchy: list[str] = Field(default_factory=list)
    source_evidence_id: str | None = None


class JoinSpec(ContractModel):
    left_table: str
    left_column: str
    right_table: str
    right_column: str
    join_type: str = "LEFT"
    cardinality: str | None = None
    amplification_risk: str | None = None
    verified: bool = False
    source_evidence_id: str | None = None


class FilterSpec(ContractModel):
    field: str | None = None
    operator: str = "="
    value: Any = None
    source: str = "user"
    required: bool = False


class LogicalQueryPlan(ContractModel):
    question: str
    intent: str = "lookup"
    entities: list[str] = Field(default_factory=list)
    required_tables: list[str] = Field(default_factory=list)
    metrics: list[MetricSpec] = Field(default_factory=list)
    dimensions: list[DimensionSpec] = Field(default_factory=list)
    joins: list[JoinSpec] = Field(default_factory=list)
    filters: list[FilterSpec] = Field(default_factory=list)
    time_window: dict[str, Any] = Field(default_factory=dict)
    business_scenario: str = "general"
    grain: list[str] = Field(default_factory=list)
    comparison: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    authority_conflicts: list[dict[str, Any]] = Field(default_factory=list)
    output_shape: str = "table"
    assumptions: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    needs_clarification: bool = False
    clarification_question: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_clarification(self) -> LogicalQueryPlan:
        if self.needs_clarification and not self.clarification_question:
            raise ValueError("clarification_question is required when clarification is needed")
        return self


class ValidationIssue(ContractModel):
    code: str
    message: str
    severity: str = Field(default="error", pattern="^(error|warning|info)$")
    evidence_id: str | None = None


class ValidationReport(ContractModel):
    status: str = Field(default="fail", pattern="^(pass|warn|fail)$")
    issues: list[ValidationIssue] = Field(default_factory=list)
    normalized_sql: str = ""
    referenced_tables: list[str] = Field(default_factory=list)
    referenced_columns: list[str] = Field(default_factory=list)
    estimated_cost: dict[str, Any] = Field(default_factory=dict)
    completeness: dict[str, Any] = Field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


class CandidateSQL(ContractModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    sql: str
    source: str = "model"
    rank: int = 0
    score: float = 0.0
    validation: ValidationReport = Field(default_factory=ValidationReport)
    assumptions: list[str] = Field(default_factory=list)
    supporting_memory_ids: list[str] = Field(default_factory=list)


class ExecutionResult(ContractModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    returned_rows: int = 0
    total_rows: int | None = None
    truncated: bool = False
    columns: list[str] = Field(default_factory=list)
    duration_ms: int = 0
    freshness: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    snapshot_id: str | None = None


class PreflightReport(ContractModel):
    status: str = Field(default="pass", pattern="^(pass|warn|fail)$")
    estimated_rows: int | None = None
    estimated_bytes: int | None = None
    estimated_cost: dict[str, Any] = Field(default_factory=dict)
    issues: list[ValidationIssue] = Field(default_factory=list)
    explain_rows: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


class ResultValidationReport(ContractModel):
    status: str = Field(default="pass", pattern="^(pass|warn|fail)$")
    issues: list[ValidationIssue] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)
    baseline: dict[str, Any] = Field(default_factory=dict)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "error"]


class PolicyDecision(ContractModel):
    allowed: bool = False
    requires_confirmation: bool = True
    reasons: list[str] = Field(default_factory=list)
    risk_level: str = Field(default="high", pattern="^(low|medium|high|blocked)$")


class AnswerCitation(ContractModel):
    label: str = Field(pattern="^(R|E)[1-9][0-9]*$")
    evidence_id: str = Field(..., min_length=1, max_length=255)
    evidence_type: str = Field(..., min_length=1, max_length=64)
    title: str = Field(..., min_length=1, max_length=500)
    authority: str = Field(..., min_length=1, max_length=64)
    version: str | None = None
    citation: str | None = None
    reason: str = ""
    excerpt: str = ""


class LearningRecord(ContractModel):
    pattern_key: str
    status: str = Field(pattern="^(ineligible|observed|trusted|rejected|stale)$")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    observation_count: int = Field(default=0, ge=0)
    success_count: int = Field(default=0, ge=0)
    failure_count: int = Field(default=0, ge=0)
    reusable: bool = False
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class QueryRun(ContractModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    request: QueryRequest
    state: RunState = RunState.RESEARCHING
    research_plan: ResearchPlan | None = None
    evidence: EvidenceBundle | None = None
    logical_plan: LogicalQueryPlan | None = None
    candidates: list[CandidateSQL] = Field(default_factory=list)
    selected_candidate_id: str | None = None
    policy: PolicyDecision | None = None
    preflight: PreflightReport | None = None
    result: ExecutionResult | None = None
    result_validation: ResultValidationReport | None = None
    answer: str | None = None
    answer_citations: list[AnswerCitation] = Field(default_factory=list)
    answer_metadata: dict[str, Any] = Field(default_factory=dict)
    learning: LearningRecord | None = None
    warnings: list[str] = Field(default_factory=list)
    trace: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    def selected_candidate(self) -> CandidateSQL | None:
        if self.selected_candidate_id:
            return next(
                (item for item in self.candidates if item.id == self.selected_candidate_id), None
            )
        return self.candidates[0] if self.candidates else None
