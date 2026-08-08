"""
ORM Models — User, ChatSession, TraceLog.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY

try:
    from sqlalchemy import JSON
except ImportError:
    from sqlalchemy.dialects.postgresql import JSONB as JSON
try:
    from pgvector.sqlalchemy import Vector
except Exception:  # pragma: no cover
    Vector = None
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from infra.config.constants import DEFAULT_TIMEZONE
from infra.config.settings import settings
from infra.storage.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | active | disabled
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # admin | user
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    sessions: Mapped[list[ChatSession]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} email={self.email}>"


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    display_title: Mapped[str] = mapped_column(String(255), nullable=True)
    turn_count: Mapped[int] = mapped_column(Integer, default=0)
    last_decision_type: Mapped[str] = mapped_column(String(50), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), default=list, nullable=False)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_active: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    archived_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    org_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    enabled_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    disabled_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Active response and branch root make conversation continuation explicit;
    # the UI no longer needs to infer lineage from legacy TraceLog rows.
    active_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    branch_root_response_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )
    is_temporary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    assistant_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    conversation_instructions: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")
    trace_logs: Mapped[list[TraceLog]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    messages: Mapped[list[Message]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    conversation_state: Mapped[ConversationState | None] = relationship(
        back_populates="session", uselist=False, passive_deletes=True
    )
    attachments: Mapped[list[Attachment]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<ChatSession id={self.id} user={self.user_id}>"


class TraceLog(Base):
    __tablename__ = "trace_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=True, index=True
    )
    trace_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    span_id: Mapped[str] = mapped_column(String(32), nullable=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=True)
    decision_type: Mapped[str] = mapped_column(String(50), nullable=True)
    validation_score: Mapped[float] = mapped_column(Float, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    reasoning_steps_json: Mapped[str] = mapped_column(Text, nullable=True)
    execution_graph_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    session: Mapped[ChatSession] = relationship(back_populates="trace_logs")

    def __repr__(self) -> str:
        return f"<TraceLog id={self.id} session={self.session_id}>"


class Message(Base):
    """Per-message storage — independent rows for user, assistant, tool, system messages.

    Replaces the flat {role, content} dict history with structured per-message rows
    that support tool_calls, tool responses, multimodal content, and version history.
    TraceLog remains as the turn-level aggregate for backward compatibility.
    """

    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    turn_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    role: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # system | user | assistant | tool
    content: Mapped[str] = mapped_column(Text, nullable=True)  # nullable for tool-call-only msgs
    tool_calls: Mapped[dict] = mapped_column(JSON, nullable=True)  # list of tool call dicts
    tool_call_id: Mapped[str] = mapped_column(String(128), nullable=True)  # for tool response msgs
    name: Mapped[str] = mapped_column(String(128), nullable=True)  # tool name
    content_type: Mapped[str] = mapped_column(
        String(30), nullable=False, default="text"
    )  # text | multimodal | tool_calls | tool_response
    content_blocks: Mapped[dict] = mapped_column(JSON, nullable=True)  # for multimodal
    version: Mapped[int] = mapped_column(Integer, default=1)
    parent_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    model: Mapped[str] = mapped_column(String(100), nullable=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="done"
    )  # done | interrupted | streaming
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ChatSession] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<Message id={self.id} role={self.role} session={self.session_id}>"


class ResponseRecord(Base):
    """Canonical, resumable result of one chat turn.

    ``TraceLog`` remains the legacy aggregate.  New response clients use this
    record together with ``ResponseItem`` and ``ResponseEvent`` so synchronous
    and streaming clients observe the same durable turn state.
    """

    __tablename__ = "responses"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_responses_tenant_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    parent_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued", index=True)
    mode: Mapped[str] = mapped_column(String(20), nullable=False, default="sync")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    request_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    goal_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ConversationShare(Base):
    """Revocable, immutable public snapshot of a conversation's active branch."""

    __tablename__ = "conversation_shares"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    public_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResponseToolExecution(Base):
    """Durable idempotency ledger for tool calls in a Response turn."""

    __tablename__ = "response_tool_executions"
    __table_args__ = (
        UniqueConstraint("response_id", "call_id", name="uq_response_tool_execution_call"),
        UniqueConstraint("idempotency_key", name="uq_response_tool_execution_idempotency"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    response_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    arguments: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    result: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    side_effect: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    side_effect_level: Mapped[str] = mapped_column(String(20), nullable=False, default="read")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ResponseItem(Base):
    """A response message, tool call, tool result, citation, or artifact."""

    __tablename__ = "response_items"
    __table_args__ = (
        UniqueConstraint("response_id", "sequence_number", name="uq_response_items_sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    response_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str | None] = mapped_column(String(20), nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResponseEvent(Base):
    """Append-only semantic events used for SSE replay and auditing."""

    __tablename__ = "response_events"
    __table_args__ = (
        UniqueConstraint("response_id", "sequence_number", name="uq_response_events_sequence"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    response_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sequence_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResponseModelCall(Base):
    """Auditable provider invocation belonging to a canonical Response."""

    __tablename__ = "response_model_calls"
    __table_args__ = (UniqueConstraint("response_id", "call_id", name="uq_response_model_call"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    response_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="query")
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="completed")
    call_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(20), default="text")  # pdf|txt|docx|md
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    content: Mapped[str] = mapped_column(Text, nullable=True)  # 原始文本
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(20), default="pending"
    )  # pending|processing|ready|error
    chunk_strategy: Mapped[int] = mapped_column(Integer, default=1)  # 1=context-aware, 2-8=reserved
    doc_metadata: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship()
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )
    llmwiki_entries: Mapped[list[DocumentLLMWiki]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Document id={self.id} title={self.title}>"


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # embedding stored as JSON string for compatibility, with optional pgvector column
    embedding_json: Mapped[str] = mapped_column(Text, nullable=True)
    embedding_dims: Mapped[int] = mapped_column(
        Integer, nullable=False, default=settings.embedding_dims
    )
    embedding_vector = mapped_column(
        Vector(settings.embedding_dims) if Vector else Text, nullable=True
    )
    chunk_metadata: Mapped[str] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="chunks")
    llmwiki_entries: Mapped[list[DocumentLLMWiki]] = relationship(
        back_populates="chunk", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<DocumentChunk id={self.id} doc={self.document_id} idx={self.chunk_index}>"


class DocumentLLMWiki(Base):
    __tablename__ = "document_llmwiki"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    chunk_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=True, index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    embedding_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_dims: Mapped[int] = mapped_column(
        Integer, nullable=False, default=settings.embedding_dims
    )
    embedding_vector = mapped_column(
        Vector(settings.embedding_dims) if Vector else Text, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    document: Mapped[Document] = relationship(back_populates="llmwiki_entries")
    chunk: Mapped[DocumentChunk | None] = relationship(back_populates="llmwiki_entries")

    def __repr__(self) -> str:
        return f"<DocumentLLMWiki id={self.id} doc={self.document_id} chunk={self.chunk_id}>"


# ═══════════════════════════════════════════════════════════════════════════
# Knowledge Orchestration — raw assets are compiled into governed knowledge.
# DocumentChunk remains an evidence segment; it is deliberately not a knowledge
# page or claim.  This preserves provenance and prevents generated summaries
# from becoming authoritative without an explicit publication state.
# ═══════════════════════════════════════════════════════════════════════════


class KnowledgeSpace(Base):
    """企业知识治理边界，独立于临时 Project 生命周期。"""

    __tablename__ = "knowledge_spaces"
    __table_args__ = (
        UniqueConstraint("tenant_id", "workspace_id", "slug", name="uq_knowledge_space_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    space_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="project", index=True
    )
    visibility: Mapped[str] = mapped_column(
        String(20), nullable=False, default="members", index=True
    )
    default_classification: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", index=True
    )
    publish_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="review")
    review_cycle_days: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    space_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeSpaceMember(Base):
    """空间级 ReBAC 关系；subject 可为用户、部门、组、岗位或项目。"""

    __tablename__ = "knowledge_space_members"
    __table_args__ = (
        UniqueConstraint(
            "space_id", "subject_type", "subject_id", name="uq_knowledge_space_member_subject"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    subject_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user", index=True
    )
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer", index=True)
    granted_by: Mapped[str] = mapped_column(String(36), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EnterpriseDirectoryPrincipal(Base):
    """企业目录中的部门、用户组和岗位；外部 ID 在租户工作区内稳定。"""

    __tablename__ = "enterprise_directory_principals"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "principal_type",
            "external_id",
            name="uq_enterprise_directory_principal",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    principal_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    parent_external_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    attributes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EnterpriseDirectoryMembership(Base):
    """企业用户到目录主体的持久化成员关系。"""

    __tablename__ = "enterprise_directory_memberships"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "user_id",
            "principal_id",
            name="uq_enterprise_directory_membership",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    principal_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("enterprise_directory_principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    membership_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EnterpriseDirectorySyncRun(Base):
    """SCIM/HR/手工目录同步的审计记录。"""

    __tablename__ = "enterprise_directory_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running", index=True)
    cursor: Mapped[str | None] = mapped_column(String(512), nullable=True)
    authoritative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    requested_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EnterpriseWorkbenchTemplate(Base):
    """按企业目录主体投影员工场景顺序的组织工作台模板。"""

    __tablename__ = "enterprise_workbench_templates"
    __table_args__ = (
        Index(
            "ix_enterprise_workbench_templates_scope_status",
            "tenant_id",
            "workspace_id",
            "status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    audience_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="principals", index=True
    )
    scenario_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="inactive", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    updated_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EnterpriseWorkbenchTemplateTarget(Base):
    """组织工作台模板与部门、岗位或用户组的作用范围。"""

    __tablename__ = "enterprise_workbench_template_targets"
    __table_args__ = (
        UniqueConstraint(
            "template_id",
            "principal_id",
            name="uq_enterprise_workbench_template_target",
        ),
        Index(
            "ix_enterprise_workbench_template_targets_scope",
            "tenant_id",
            "workspace_id",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    template_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("enterprise_workbench_templates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    principal_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("enterprise_directory_principals.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EnterpriseCognitiveEntity(Base):
    """公司或部门的一等认知实体，负责绑定目录主体与治理知识空间。"""

    __tablename__ = "enterprise_cognitive_entities"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "entity_type",
            "entity_key",
            name="uq_enterprise_cognitive_entity_scope_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    entity_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    entity_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    directory_principal_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("enterprise_directory_principals.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    knowledge_space_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EnterpriseCognitiveVersion(Base):
    """企业认知的可审核版本；只有 published 版本会进入 Responses 上下文。"""

    __tablename__ = "enterprise_cognitive_versions"
    __table_args__ = (
        UniqueConstraint("entity_id", "version", name="uq_enterprise_cognitive_entity_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    entity_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("enterprise_cognitive_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    classification: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", index=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    mission: Mapped[str] = mapped_column(Text, nullable=False, default="")
    vision: Mapped[str] = mapped_column(Text, nullable=False, default="")
    values: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    responsibilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    products_services: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    operating_principles: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    terminology: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    key_contacts: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    source_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    context_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    review_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    published_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CompanyProfile(Base):
    """当前部署唯一绑定的公司；singleton_key 从数据库层保证只能存在一家公司。"""

    __tablename__ = "company_profiles"
    __table_args__ = (UniqueConstraint("singleton_key", name="uq_company_profiles_singleton"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    singleton_key: Mapped[str] = mapped_column(
        String(20), nullable=False, default="primary", unique=True
    )
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    short_name: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    current_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    last_maintenance_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_daily_maintenance_date: Mapped[str | None] = mapped_column(
        String(10), nullable=True, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CompanyBrainSource(Base):
    """企业大脑的内部来源；只允许企业大脑服务读取原文并执行蒸馏。"""

    __tablename__ = "company_brain_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    folder: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    memory_tier: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source_content: Mapped[str] = mapped_column(Text, nullable=False)
    processed_content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    processing_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CompanyBrainVersion(Base):
    """COMPANY.md 的不可变草稿/发布版本。"""

    __tablename__ = "company_brain_versions"
    __table_args__ = (UniqueConstraint("company_id", "version", name="uq_company_brain_version"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    company_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("company_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    long_term_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    medium_term_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    short_term_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    trigger: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    change_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    published_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgePrincipalMembership(Base):
    """用户到部门、组和岗位主体的映射，可由 SCIM/HR 系统同步。"""

    __tablename__ = "knowledge_principal_memberships"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "user_id",
            "principal_type",
            "principal_id",
            name="uq_knowledge_principal_membership",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    principal_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    principal_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="manual")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    membership_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeSpaceProject(Base):
    """Project 挂载长期 Knowledge Space，而不是拥有其生命周期。"""

    __tablename__ = "knowledge_space_projects"
    __table_args__ = (
        UniqueConstraint("space_id", "project_id", name="uq_knowledge_space_project"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    attached_by: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeConnector(Base):
    """企业知识源连接器状态；凭据只保存外部 credential 引用。"""

    __tablename__ = "knowledge_connectors"
    __table_args__ = (UniqueConstraint("space_id", "name", name="uq_knowledge_connector_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    space_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    connector_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="push", index=True
    )
    base_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    credential_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sync_cursor: Mapped[str | None] = mapped_column(Text, nullable=True)
    sync_interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    connector_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeSyncRun(Base):
    __tablename__ = "knowledge_sync_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    connector_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    cursor_before: Mapped[str | None] = mapped_column(Text, nullable=True)
    cursor_after: Mapped[str | None] = mapped_column(Text, nullable=True)
    stats: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeSyncItem(Base):
    """连接器增量 Snapshot 的持久化执行项，由 Worker 可恢复领取。"""

    __tablename__ = "knowledge_sync_items"
    __table_args__ = (
        UniqueConstraint("run_id", "external_id", name="uq_knowledge_sync_item_external"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_sync_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    connector_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_connectors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    external_id: Mapped[str] = mapped_column(String(512), nullable=False)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_type: Mapped[str] = mapped_column(String(20), nullable=False, default="text")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    authority: Mapped[str] = mapped_column(String(32), nullable=False, default="external")
    classification: Mapped[str | None] = mapped_column(String(20), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    acl_snapshot: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_by: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeSource(Base):
    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "document_id", name="uq_knowledge_source_document_scope"
        ),
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "connector_id",
            "external_ref",
            name="uq_knowledge_source_connector_ref",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    space_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    connector_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_connectors.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    steward_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False, default="document")
    external_ref: Mapped[str | None] = mapped_column(String(512), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    authority: Mapped[str] = mapped_column(String(32), nullable=False, default="contextual")
    classification: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", index=True
    )
    source_system: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    sync_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="current", index=True
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    active_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    effective_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    review_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeSourcePermission(Base):
    """从外部知识源同步的细粒度 ACL；与空间权限取交集。"""

    __tablename__ = "knowledge_source_permissions"
    __table_args__ = (
        UniqueConstraint(
            "source_id", "subject_type", "subject_id", name="uq_knowledge_source_permission"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    subject_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default="view")
    inherited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_ref: Mapped[str | None] = mapped_column(String(512), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeSourceVersion(Base):
    __tablename__ = "knowledge_source_versions"
    __table_args__ = (
        UniqueConstraint("source_id", "version_number", name="uq_knowledge_source_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    compiler_version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    raw_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    compiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeReviewTask(Base):
    """知识版本发布审批任务，发布动作必须留下明确决策。"""

    __tablename__ = "knowledge_review_tasks"
    __table_args__ = (
        UniqueConstraint("source_version_id", name="uq_knowledge_review_source_version"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    space_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("knowledge_spaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    required_role: Mapped[str] = mapped_column(String(20), nullable=False, default="publisher")
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    assigned_to: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    diff_summary: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgePage(Base):
    __tablename__ = "knowledge_pages"
    __table_args__ = (
        UniqueConstraint("source_version_id", "slug", name="uq_knowledge_page_version_slug"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    page_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="overview", index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="knowledge_page_v1"
    )
    authority: Mapped[str] = mapped_column(String(32), nullable=False, default="contextual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    page_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeClaim(Base):
    __tablename__ = "knowledge_claims"
    __table_args__ = (
        UniqueConstraint("page_id", "claim_hash", name="uq_knowledge_claim_page_hash"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    page_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False, default="fact", index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    claim_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    evidence_chunk_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    evidence_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    authority: Mapped[str] = mapped_column(String(32), nullable=False, default="contextual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    valid_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claim_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_page_id", "target_page_id", "relation_type", name="uq_knowledge_relation"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_version_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("knowledge_source_versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    source_page_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_page_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("knowledge_pages.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    authority: Mapped[str] = mapped_column(String(32), nullable=False, default="contextual")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft", index=True)
    relation_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeCompilationJob(Base):
    __tablename__ = "knowledge_compilation_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending", index=True)
    compiler_version: Mapped[str] = mapped_column(String(64), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeLintIssue(Base):
    __tablename__ = "knowledge_lint_issues"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "issue_key", name="uq_knowledge_lint_issue_scope"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    issue_key: Mapped[str] = mapped_column(String(128), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning", index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open", index=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class KnowledgeFeedback(Base):
    __tablename__ = "knowledge_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    target_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    target_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    feedback_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    correction: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class KnowledgeRule(Base):
    """Executable metadata-layer rule/schema with explicit approval state."""

    __tablename__ = "knowledge_rules"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id", "workspace_id", "rule_key", "version", name="uq_knowledge_rule_version"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    rule_type: Mapped[str] = mapped_column(String(32), nullable=False, default="schema")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    schema_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    instructions: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class KnowledgeObservation(Base):
    """Metacognition telemetry used to propose rule evolution."""

    __tablename__ = "knowledge_observations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    metric: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    dimensions: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trigger: Mapped[str] = mapped_column(String(64), nullable=False, default="scheduled")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class KnowledgeMergeCase(Base):
    """Human-in-the-loop case for conflicting claims or duplicate concepts."""

    __tablename__ = "knowledge_merge_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    entity_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    conflict_type: Mapped[str] = mapped_column(
        String(64), nullable=False, default="duplicate_claim"
    )
    candidate_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    resolution: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RedisShadowKV(Base):
    """Shadow table for Redis data: dual-write + read fallback source."""

    __tablename__ = "redis_shadow_kv"
    __table_args__ = (UniqueConstraint("redis_db", "redis_key", name="uq_redis_shadow_db_key"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    redis_db: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    redis_key: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    data_type: Mapped[str] = mapped_column(String(20), nullable=False, default="string")
    payload_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    expire_at_ts: Mapped[float] = mapped_column(Float, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ReasoningTrace(Base):
    __tablename__ = "reasoning_traces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=True, index=True)
    phase: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=True)
    score: Mapped[float] = mapped_column(Float, nullable=True)
    iteration: Mapped[int] = mapped_column(Integer, default=0)
    phase_metadata: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ToolStat(Base):
    __tablename__ = "tool_stats"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tool_name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, default=0)
    avg_latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    last_error: Mapped[str] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    response: Mapped[str] = mapped_column(Text, nullable=True)
    feedback_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    score: Mapped[float] = mapped_column(Float, nullable=True)
    correction: Mapped[str] = mapped_column(Text, nullable=True)
    feedback_metadata: Mapped[str] = mapped_column(Text, nullable=True)
    # DataAgent V2 learning loop fields
    agent_trace_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    corrected_metric_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    corrected_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    learning_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserMemory(Base):
    __tablename__ = "user_memories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    memory_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="fact")
    personal_category: Mapped[str] = mapped_column(
        String(30), nullable=False, default="profile", index=True
    )
    memory_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.5)
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user", index=True)
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    source_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    supersedes_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserMemoryRelation(Base):
    """持久化用户记忆关系图；PostgreSQL 是事实来源，Redis 仅可作投影。"""

    __tablename__ = "user_memory_relations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "workspace_id",
            "source_memory_id",
            "target_memory_id",
            "relation_type",
            name="uq_user_memory_relation_edge",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_memory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_memory_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("user_memories.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="related_to", index=True
    )
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    relation_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserMemorySettings(Base):
    __tablename__ = "user_memory_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False, unique=True)
    memory_learning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    preference_learning_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryConstitution(Base):
    """工作区记忆宪法的不可变版本。"""

    __tablename__ = "memory_constitutions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "version",
            name="uq_memory_constitution_scope_version",
        ),
        Index(
            "uq_memory_constitution_active_scope",
            "tenant_id",
            "workspace_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryConstitutionAudit(Base):
    """记忆宪法决策审计；不保存原始敏感内容。"""

    __tablename__ = "memory_constitution_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    subject_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    memory_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    constitution_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    categories_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatConstitution(Base):
    """工作区聊天宪法的不可变版本。"""

    __tablename__ = "chat_constitutions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "version",
            name="uq_chat_constitution_scope_version",
        ),
        Index(
            "uq_chat_constitution_active_scope",
            "tenant_id",
            "workspace_id",
            unique=True,
            postgresql_where=text("is_active = true"),
            sqlite_where=text("is_active = 1"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    rules_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ChatConstitutionAudit(Base):
    """聊天宪法判定审计；不保存原始用户输入。"""

    __tablename__ = "chat_constitution_audits"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    subject_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    constitution_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    reason_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    categories_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_length: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserCustomInstruction(Base):
    """Explicit user instructions, kept separate from learned memory."""

    __tablename__ = "user_custom_instructions"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "tenant_id", "workspace_id", name="uq_custom_instruction_scope"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(128), index=True, nullable=False, default="default"
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), index=True, nullable=False, default="default"
    )
    about_user: Mapped[str] = mapped_column(Text, nullable=False, default="")
    response_style: Mapped[str] = mapped_column(Text, nullable=False, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AssistantProfile(Base):
    """User-facing assistant personality and execution defaults."""

    __tablename__ = "assistant_profiles"
    __table_args__ = (
        UniqueConstraint("user_id", "tenant_id", "name", name="uq_assistant_profile_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    personality: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_model_profile: Mapped[str] = mapped_column(String(20), nullable=False, default="auto")
    tool_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    memory_policy: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    built_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Project(Base):
    """Conversation workspace with isolated instructions and memory scope."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    memory_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="default")
    assistant_profile_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data_source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResponseApproval(Base):
    """Durable pause point for a side-effecting tool call."""

    __tablename__ = "response_approvals"
    __table_args__ = (UniqueConstraint("response_id", "call_id", name="uq_response_approval_call"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    response_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    call_id: Mapped[str] = mapped_column(String(128), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(128), nullable=False)
    side_effect_level: Mapped[str] = mapped_column(String(20), nullable=False, default="write")
    arguments: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ResponseOutbox(Base):
    """Transactional hand-off from PostgreSQL to Redis Streams."""

    __tablename__ = "response_outbox"
    __table_args__ = (UniqueConstraint("event_key", name="uq_response_outbox_event_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    aggregate_type: Mapped[str] = mapped_column(String(32), nullable=False, default="response")
    aggregate_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    available_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class GoalRun(Base):
    __tablename__ = "goal_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    success_criteria: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued", index=True)
    plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class GoalCheckpoint(Base):
    __tablename__ = "goal_checkpoints"
    __table_args__ = (UniqueConstraint("goal_id", "step_number", name="uq_goal_checkpoint_step"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    goal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("goal_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="completed")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalendarEvent(Base):
    """用户个人日历事件；重复事件按 RFC5545 规则在查询时展开。"""

    __tablename__ = "calendar_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    location: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    event_type: Mapped[str] = mapped_column(String(32), nullable=False, default="event")
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TIMEZONE)
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recurrence_rule: Mapped[str | None] = mapped_column(String(512), nullable=True)
    reminder_minutes: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=lambda: [15])
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="confirmed", index=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class CalendarEventRevision(Base):
    """日历事件不可变更的修订账本；当前状态仍以 CalendarEvent 为准。"""

    __tablename__ = "calendar_event_revisions"
    __table_args__ = (UniqueConstraint("event_id", "revision", name="uq_calendar_event_revision"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    changed_fields: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    source_response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class CalendarReminderDelivery(Base):
    """日历提醒投递账本，防止 Worker 重启或并发轮询造成重复通知。"""

    __tablename__ = "calendar_reminder_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "occurrence_start",
            "reminder_minutes",
            name="uq_calendar_reminder_delivery",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    event_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calendar_events.id", ondelete="CASCADE"), nullable=False, index=True
    )
    occurrence_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    reminder_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MemoryCandidate(Base):
    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    response_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("responses.id", ondelete="CASCADE"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    scope_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="fact")
    personal_category: Mapped[str] = mapped_column(
        String(30), nullable=False, default="profile", index=True
    )
    memory_key: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    salience: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    observations: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    learning_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="model")
    constitution_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryEvidence(Base):
    __tablename__ = "memory_evidence"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    memory_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    candidate_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("memory_candidates.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    response_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    item_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    excerpt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserUiSettings(Base):
    __tablename__ = "user_ui_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False, unique=True)
    reasoning_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
    graph_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
    dag_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
    execution_graph_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
    decision_trace_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
    flow_cards_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
    theme_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    theme_accent: Mapped[str] = mapped_column(String(32), nullable=False, default="blue")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskDefinition(Base):
    __tablename__ = "task_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    task_type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="agent_task", index=True
    )
    task_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="interval")
    trigger_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    conversation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    rrule: Mapped[str | None] = mapped_column(String(512), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TIMEZONE)
    requires_confirmation: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskRun(Base):
    __tablename__ = "task_runs"
    __table_args__ = (UniqueConstraint("task_id", "scheduled_for", name="uq_task_run_schedule"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    output: Mapped[str] = mapped_column(Text, nullable=True)
    output_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)


class TaskNotification(Base):
    __tablename__ = "task_notifications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    task_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=True)
    read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AlertRule(Base):
    """Project-scoped deterministic condition evaluated from a governed data query."""

    __tablename__ = "alert_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    project_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    data_source_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    metric_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aggregation: Mapped[str] = mapped_column(String(20), nullable=False, default="first")
    operator: Mapped[str] = mapped_column(String(24), nullable=False, default="gt")
    threshold: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    rrule: Mapped[str] = mapped_column(String(512), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_TIMEZONE)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    cooldown_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    last_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_state: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_triggered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_run_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class AlertEvent(Base):
    __tablename__ = "alert_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    rule_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="triggered", index=True)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning", index=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    acknowledged_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class SkillCatalogEntry(Base):
    """Normalized, reviewable metadata synced from a public SkillHub catalog."""

    __tablename__ = "skill_catalog_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    provider: Mapped[str] = mapped_column(
        String(64), nullable=False, default="skillhub", index=True
    )
    external_id: Mapped[str] = mapped_column(String(512), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    github_owner: Mapped[str] = mapped_column(String(255), nullable=False)
    github_repo: Mapped[str] = mapped_column(String(255), nullable=False)
    skill_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    license: Mapped[str | None] = mapped_column(String(128), nullable=True)
    github_stars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    download_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    security_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    security_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="unknown", index=True
    )
    ai_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    review_status: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    rank_popular: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    rank_recent: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    source_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    synced_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class UserSkillInstallation(Base):
    """Account/workspace installation state separated from the shared catalog."""

    __tablename__ = "user_skill_installations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "workspace_id",
            "catalog_skill_id",
            name="uq_user_skill_installation_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    catalog_skill_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("skill_catalog_entries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    installed_skill_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="installed", index=True)
    install_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="instruction_only"
    )
    source_revision: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class EnterpriseSkill(Base):
    """由企业资料蒸馏并在租户工作区内发布的指令型 Skill。"""

    __tablename__ = "enterprise_skills"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "source_digest",
            name="uq_enterprise_skill_scope_source_digest",
        ),
        UniqueConstraint("runtime_id", name="uq_enterprise_skill_runtime_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    runtime_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    value_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions: Mapped[str] = mapped_column(Text, nullable=False)
    source_digest: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_files: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    use_cases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    classification: Mapped[str] = mapped_column(
        String(20), nullable=False, default="internal", index=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="published", index=True)
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    published_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ResourcePermission(Base):
    """Explicit resource ACL layered on top of ownership and tenant isolation."""

    __tablename__ = "resource_permissions"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "workspace_id",
            "subject_user_id",
            "resource_type",
            "resource_id",
            name="uq_resource_permission_subject",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    subject_user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    permission: Mapped[str] = mapped_column(String(20), nullable=False, default="view", index=True)
    granted_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ConversationState(Base):
    """Per-session structured conversation state for multi-turn reference resolution."""

    __tablename__ = "conversation_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_sessions.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    active_topic: Mapped[str] = mapped_column(String(255), nullable=True)
    active_intent: Mapped[str] = mapped_column(String(64), nullable=True)
    active_domain: Mapped[str] = mapped_column(String(64), nullable=True)
    active_entities: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    active_constraints: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    active_mode: Mapped[str] = mapped_column(String(64), nullable=True)
    active_data_source_id: Mapped[str] = mapped_column(String(36), nullable=True)
    active_document_ids: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    active_attachment_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    last_user_goal: Mapped[str] = mapped_column(Text, nullable=True)
    last_assistant_summary: Mapped[str] = mapped_column(Text, nullable=True)
    last_plan: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    last_results: Mapped[dict] = mapped_column(JSON, nullable=False, default=list)
    pending_clarification: Mapped[dict] = mapped_column(JSON, nullable=True)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    state_extension: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="conversation_state")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    action: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # postgres/mysql/clickhouse
    host: Mapped[str] = mapped_column(String(255), nullable=False)
    port: Mapped[int] = mapped_column(Integer, nullable=False)
    database: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str] = mapped_column(String(255), nullable=False)
    password_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataSourceSchema(Base):
    __tablename__ = "data_source_schemas"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    schema_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    semantic_mappings: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    embedding: Mapped[str] = mapped_column(Text, nullable=True)
    # DataAgent V2 enhanced fields
    auto_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    relationship_hints: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_analyzed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConnectorCredential(Base):
    __tablename__ = "connector_credentials"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "workspace_id",
            "provider",
            name="uq_connector_credential_scope_provider",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="default")
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    credential_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataQueryLog(Base):
    __tablename__ = "data_query_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    data_source_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str] = mapped_column(Text, nullable=True)
    execution_time: Mapped[int] = mapped_column(Integer, default=0)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    feedback_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# SQL 资产与查询草案是在线问数的治理事实，不复用无作用域的历史 QueryPattern。
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
    asset_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    statement_type: Mapped[str] = mapped_column(String(64), nullable=False)
    executable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="draft", index=True)
    dialect: Mapped[str] = mapped_column(String(32), nullable=False)
    tables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    columns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    lineage: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    knowledge_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
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


# ═══════════════════════════════════════════════════════════════════════════
# DataAgent V2 — Knowledge Asset Tables
# ═══════════════════════════════════════════════════════════════════════════


class MetricDefinition(Base):
    """Governed metric catalog — authoritative source for business metric formulas."""

    __tablename__ = "metric_definitions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    formula: Mapped[str] = mapped_column(Text, nullable=False)
    underlying_columns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    agg_function: Mapped[str | None] = mapped_column(String(50), nullable=True)
    business_definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False, default="public")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    lineage: Mapped[list[MetricLineage]] = relationship(
        back_populates="metric",
        foreign_keys="MetricLineage.metric_id",
        cascade="all, delete-orphan",
    )


class SchemaMetadata(Base):
    """Per-column business semantics — bridges DB schema and business vocabulary."""

    __tablename__ = "schema_metadata"
    __table_args__ = (
        UniqueConstraint(
            "data_source_id", "table_name", "column_name", name="uq_schema_meta_ds_table_col"
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    semantic_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    value_map: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_primary_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_foreign_key: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_time_column: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    time_grain: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_metric_column: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_dimension_column: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_sensitive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    masking_rule: Mapped[str | None] = mapped_column(String(50), nullable=True)
    lifecycle_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    nullable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    default_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_values: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    annotation_source: Mapped[str] = mapped_column(String(32), nullable=False, default="inferred")
    annotation_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    annotation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="suggested", index=True
    )
    suggested_changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class SchemaTableMetadata(Base):
    """表级业务语义，独立于物理数据库是否提供 COMMENT。"""

    __tablename__ = "schema_table_metadata"
    __table_args__ = (
        UniqueConstraint("data_source_id", "table_name", name="uq_schema_table_meta_ds_table"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    annotation_source: Mapped[str] = mapped_column(String(32), nullable=False, default="inferred")
    annotation_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    annotation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="suggested", index=True
    )
    suggested_changes: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    source_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    schema_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TableRelationship(Base):
    """Pre-modeled table join graph — FK-based with usage-based validation."""

    __tablename__ = "table_relationships"
    __table_args__ = (
        UniqueConstraint(
            "data_source_id",
            "left_table",
            "left_column",
            "right_table",
            "right_column",
            name="uq_table_rel_ds_lr",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    left_table: Mapped[str] = mapped_column(String(255), nullable=False)
    left_column: Mapped[str] = mapped_column(String(255), nullable=False)
    right_table: Mapped[str] = mapped_column(String(255), nullable=False)
    right_column: Mapped[str] = mapped_column(String(255), nullable=False)
    join_type: Mapped[str] = mapped_column(String(20), nullable=False, default="LEFT")
    cardinality: Mapped[str | None] = mapped_column(String(10), nullable=True)
    amplification_risk: Mapped[str | None] = mapped_column(String(10), nullable=True)
    is_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    usage_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalyticalSkill(Base):
    """Reusable analytical pattern templates — cohort, funnel, RFM, etc."""

    __tablename__ = "analytical_skills"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    skill_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    required_intent_types: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list
    )
    required_metric_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    required_dimension_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    plan_template: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    sql_template: Mapped[str | None] = mapped_column(Text, nullable=True)
    visualization_hint: Mapped[str | None] = mapped_column(String(50), nullable=True)
    parameters_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    examples: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class QueryPattern(Base):
    """Successful query pattern memory — hash-based fast path for repeated queries."""

    __tablename__ = "query_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    pattern_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    query_template: Mapped[str] = mapped_column(Text, nullable=False)
    intent_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entities: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    metrics: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    successful_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    avg_latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MetricLineage(Base):
    """Dependency graph between metrics — e.g. "ARPU" depends on "Revenue" and "Active Users"."""

    __tablename__ = "metric_lineage"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    metric_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("metric_definitions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    depends_on_metric_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("metric_definitions.id", ondelete="SET NULL"), nullable=True
    )
    depends_on_column: Mapped[str | None] = mapped_column(String(255), nullable=True)
    transformation: Mapped[str | None] = mapped_column(Text, nullable=True)
    lineage_type: Mapped[str] = mapped_column(String(20), nullable=False, default="derived")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    metric: Mapped[MetricDefinition] = relationship(
        back_populates="lineage", foreign_keys=[metric_id]
    )


# ═══════════════════════════════════════════════════════════════════════════


class Attachment(Base):
    """Per-session uploaded attachment (document, image, etc.) with content dedup."""

    __tablename__ = "attachments"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=True)
    file_extension: Mapped[str] = mapped_column(String(20), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=True, index=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_summary: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    image_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    image_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_base64: Mapped[str | None] = mapped_column(Text, nullable=True)
    media_mime: Mapped[str | None] = mapped_column(String(100), nullable=True)
    media_kind: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    storage_backend: Mapped[str] = mapped_column(String(20), nullable=False, default="database")
    object_key: Mapped[str | None] = mapped_column(String(1024), nullable=True, unique=True)
    object_etag: Mapped[str | None] = mapped_column(String(128), nullable=True)
    message_id: Mapped[str] = mapped_column(String(50), nullable=True)
    duplicate_of: Mapped[str] = mapped_column(String(36), nullable=True)
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="session")
    ingest_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="temporary", index=True
    )
    promoted_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    asset_metadata: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    session: Mapped[ChatSession] = relationship(back_populates="attachments")
    user: Mapped[User] = relationship()

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} filename={self.filename} session={self.session_id}>"


class CognitiveEvent(Base):
    """DataAgent V2 pipeline step audit trail."""

    __tablename__ = "cognitive_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    query_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    step: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="start")
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class LegalHold(Base):
    """阻止保留清理和租户删除的数据保全指令。"""

    __tablename__ = "legal_holds"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", index=True)
    created_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    released_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DataDeletionJob(Base):
    """可审计、可暂停、可重试的租户/工作区删除传播任务。"""

    __tablename__ = "data_deletion_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    tenant_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    requested_by: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    phase: Mapped[str] = mapped_column(String(32), nullable=False, default="grace_period")
    progress: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    execute_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RevokedToken(Base):
    """JWT jti 撤销记录；只保存哈希，避免 token 内容落库。"""

    __tablename__ = "revoked_tokens"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    reason: Mapped[str] = mapped_column(String(128), nullable=False, default="logout")
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revoked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
