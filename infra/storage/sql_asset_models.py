"""SQL 语料资产、查询计划与候选的持久化模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infra.storage.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class SQLAssetSource(Base):
    __tablename__ = "sql_asset_sources"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "project_id",
            "content_sha256",
            name="uq_sql_asset_source_scope_hash",
        ),
        Index(
            "uq_sql_asset_source_global_hash",
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "content_sha256",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
            sqlite_where=text("project_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False, default="text/plain")
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    dialect: Mapped[str] = mapped_column(String(32), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(32), nullable=False, default="sqlglot-v1")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="parsed", index=True)
    statement_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parse_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SQLAsset(Base):
    __tablename__ = "sql_assets"
    __table_args__ = (
        UniqueConstraint("source_id", "statement_index", name="uq_sql_asset_source_statement"),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "project_id",
            "sql_hash",
            name="uq_sql_asset_scope_hash",
        ),
        Index(
            "uq_sql_asset_global_hash",
            "tenant_id",
            "workspace_id",
            "data_source_id",
            "sql_hash",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
            sqlite_where=text("project_id IS NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sql_asset_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    statement_index: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    normalized_sql: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    structure_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    statement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    executable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    corpus_role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="retrieval", index=True
    )
    quality_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="unverified", index=True
    )
    domain: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    owner: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dialect: Mapped[str] = mapped_column(String(32), nullable=False)
    tables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    lineage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    knowledge_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    risk_flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    verification_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retrieval_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validation_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_start_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_end_line: Mapped[int | None] = mapped_column(Integer, nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SQLQueryDraft(Base):
    __tablename__ = "sql_query_drafts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    group_type: Mapped[str] = mapped_column(String(20), nullable=False, default="alternative")
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="awaiting_confirmation", index=True
    )
    output_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="sql_only")
    query_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    clarification: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    dialect: Mapped[str] = mapped_column(String(32), nullable=False)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    selected_candidate_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    execution_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    execution_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SQLQueryCandidate(Base):
    __tablename__ = "sql_query_candidates"
    __table_args__ = (
        UniqueConstraint("draft_id", "position", name="uq_sql_query_candidate_position"),
        UniqueConstraint("draft_id", "sql_hash", name="uq_sql_query_candidate_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    draft_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("sql_query_drafts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    sql_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    validation_report: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    execution_status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    result_rows: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
