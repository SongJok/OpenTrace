"""
ORM Models — User, ChatSession, TraceLog.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
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
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="user"
    )  # admin | user
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
    parent_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
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


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
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
    memory_type: Mapped[str] = mapped_column(String(20), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="fact")
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    tags_json: Mapped[str] = mapped_column(Text, nullable=True)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    score: Mapped[float] = mapped_column(Float, default=0.5)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class UserUiSettings(Base):
    __tablename__ = "user_ui_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False, unique=True)
    reasoning_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
    graph_default_expanded: Mapped[bool] = mapped_column(Boolean, default=True)
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
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False, default="interval")
    trigger_config_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TaskRun(Base):
    __tablename__ = "task_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    task_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    user_id: Mapped[str] = mapped_column(String(36), index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    output: Mapped[str] = mapped_column(Text, nullable=True)
    error: Mapped[str] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=True)


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
    last_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
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
        back_populates="metric", foreign_keys="MetricLineage.metric_id", cascade="all, delete-orphan"
    )


class SchemaMetadata(Base):
    """Per-column business semantics — bridges DB schema and business vocabulary."""

    __tablename__ = "schema_metadata"
    __table_args__ = (
        UniqueConstraint("data_source_id", "table_name", "column_name", name="uq_schema_meta_ds_table_col"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    data_source_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    table_name: Mapped[str] = mapped_column(String(255), nullable=False)
    column_name: Mapped[str] = mapped_column(String(255), nullable=False)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    business_description: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TableRelationship(Base):
    """Pre-modeled table join graph — FK-based with usage-based validation."""

    __tablename__ = "table_relationships"
    __table_args__ = (
        UniqueConstraint(
            "data_source_id", "left_table", "left_column", "right_table", "right_column",
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
    required_intent_types: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
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
        String(36), ForeignKey("metric_definitions.id", ondelete="CASCADE"), nullable=False, index=True
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
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=True)
    file_extension: Mapped[str] = mapped_column(String(20), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=True, index=True)
    content_text: Mapped[str] = mapped_column(Text, nullable=True)
    content_summary: Mapped[str] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    image_base64: Mapped[str] = mapped_column(Text, nullable=True)
    image_mime: Mapped[str] = mapped_column(String(100), nullable=True)
    message_id: Mapped[str] = mapped_column(String(50), nullable=True)
    duplicate_of: Mapped[str] = mapped_column(String(36), nullable=True)
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
