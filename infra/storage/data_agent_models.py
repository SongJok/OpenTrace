"""DataAgent 平台的运行、治理、画像和评测持久化模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infra.storage.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class DataAgentRunRecord(Base):
    __tablename__ = "data_agent_runs"
    __table_args__ = (
        Index(
            "ix_data_agent_runs_scope_created",
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    mode: Mapped[str] = mapped_column(String(32), nullable=False, default="sql_only")
    state: Mapped[str] = mapped_column(
        String(32), nullable=False, default="researching", index=True
    )
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    research_plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    evidence_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    logical_plan_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    candidates_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    selected_candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    policy_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    preflight_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result_validation_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    trace_json: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    semantic_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DataAgentRunEvent(Base):
    __tablename__ = "data_agent_run_events"
    __table_args__ = (
        UniqueConstraint("run_id", "sequence_number", name="uq_data_agent_run_event_sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataAgentSemanticAsset(Base):
    """业务过程、数据质量、实体和维度等治理资产。"""

    __tablename__ = "data_agent_semantic_assets"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "asset_type",
            "asset_key",
            "version",
            name="uq_data_agent_semantic_asset_version",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_key: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    authority: Mapped[str] = mapped_column(String(32), nullable=False, default="contextual")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    definition_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    business_domain: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataAgentEvaluationCase(Base):
    """冻结数据快照上的问题-SQL-结果评测样例。"""

    __tablename__ = "data_agent_evaluation_cases"
    __table_args__ = (
        Index("ix_data_agent_eval_scope", "tenant_id", "workspace_id", "data_source_id"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    expected_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    expected_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expected_result: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class DataAgentFeedback(Base):
    """用户对候选 SQL 或执行结果的结构化反馈。"""

    __tablename__ = "data_agent_feedback"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_agent_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    verdict: Mapped[str] = mapped_column(String(20), nullable=False)
    candidate_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    corrected_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataAgentProfile(Base):
    """基于有界真实样本生成的表级或字段级数据画像。"""

    __tablename__ = "data_agent_profiles"
    __table_args__ = (
        Index(
            "ix_data_agent_profile_snapshot",
            "data_source_id",
            "schema_fingerprint",
            "table_name",
            "column_name",
        ),
        Index(
            "ix_data_agent_profiles_scope",
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    schema_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    column_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    profile_type: Mapped[str] = mapped_column(String(20), nullable=False, default="column")
    sampling_method: Mapped[str] = mapped_column(String(64), nullable=False, default="bounded_head")
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profile_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="current", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    profiled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
