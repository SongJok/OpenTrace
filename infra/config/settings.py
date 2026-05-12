"""
OpenTrace — Centralized Settings
All configuration is loaded once from environment/dotenv via pydantic-settings.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse, urlunparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


# ---------------------------------------------------------------------------
# Sub-setting blocks
# ---------------------------------------------------------------------------

class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/opentrace_v2"
    token_db_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/opentrace_v2"
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 1800

    @field_validator("database_url", "token_db_url", mode="before")
    @classmethod
    def _fix_driver(cls, v: str) -> str:
        """Auto-replace psycopg2 DSN with asyncpg driver and normalize docker host alias."""
        if not isinstance(v, str):
            return v
        if v.startswith("postgresql://"):
            v = v.replace("postgresql://", "postgresql+asyncpg://", 1)
        if "host.docker.internal" in v:
            v = v.replace("host.docker.internal", "postgres", 1)
        return v


class RedisSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/10"
    redis_session_db: int = 10
    redis_cache_db: int = 11
    redis_memory_db: int = 12
    redis_queue_db: int = 13
    redis_rate_limit_db: int = 14
    redis_pubsub_db: int = 15


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Query LLM
    default_llm_query_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_query_model: str = "qwen3.6-plus"
    default_llm_query_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_query_api_key: str = ""

    # Compress LLM
    default_llm_compress_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_compress_model: str = "qwen3.5-27b"
    default_llm_compress_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_compress_api_key: str = ""

    # Planning LLM
    default_llm_planing_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_planing_model: str = "qwen3.5-flash"
    default_llm_planing_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_planing_api_key: str = ""

    # SeniorShort LLM (14B) — knowledge Q&A, cheap critic
    default_llm_seniorshort_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_seniorshort_model: str = "qwen3-14b"
    default_llm_seniorshort_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_seniorshort_api_key: str = ""

    # MiddleShort LLM (8B) — simple/FAQ answers
    default_llm_middleshort_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_middleshort_model: str = "qwen3-8b"
    default_llm_middleshort_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_middleshort_api_key: str = ""

    # JuniorShort LLM (1.7B) — L1 router/classification
    default_llm_juniorshort_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_juniorshort_model: str = "qwen3-1.7b"
    default_llm_juniorshort_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_juniorshort_api_key: str = ""

    # MinShort LLM (0.6B) — reserved for future use
    default_llm_minshort_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_minshort_model: str = "qwen3-0.6b"
    default_llm_minshort_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_minshort_api_key: str = ""

    # Vision LLM — image/chart/diagram interpretation
    default_llm_vision_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_vision_model: str = "qwen3.6-vl-plus"
    default_llm_vision_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_vision_api_key: str = ""


class EmbeddingSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    embedding_provider: str = "dashscope"
    embedding_model_name: str = "text-embedding-v3"
    embedding_dims: int = 1024
    embedding_timeout_seconds: int = 30
    embedding_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    embedding_api_key: str = ""
    embedding_api_paths: str = "/embeddings,/v1/embeddings"
    embedding_trust_env: bool = True
    embedding_skip_proxy_first: bool = True


class RerankSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    rerank_provider: str = "heuristic"
    rerank_model_name: str = "BAAI/bge-reranker-v2-m3"
    rerank_api_url: str = ""
    rerank_api_paths: str = "/rerank,/v1/rerank"
    rerank_api_key: str = ""
    rerank_timeout_seconds: int = 10
    rerank_trust_env: bool = True
    rerank_skip_proxy_first: bool = True


class JWTSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jwt_secret: str = "opentrace-jwt-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080


class SMTPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    smtp_host: str = "smtp.163.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""


class OTelSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "opentrace"
    otel_traces_sampler: str = "always_on"
    trace_enabled: bool = True


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "opentrace"
    app_env: Literal["development", "staging", "production"] = "development"
    app_secret_key: str = "opentrace-secret-key-change-in-production-32bytes"
    app_host: str = "0.0.0.0"
    app_port: int = 14100
    debug: bool = False

    gateway_host: str = "0.0.0.0"
    gateway_port: int = 14100
    frontend_port: int = 14108

    vite_api_url: str = "http://localhost:14100"
    vite_ws_url: str = "ws://localhost:14100"

    use_pgvector: bool = True
    max_agent_steps: int = 8
    agent_timeout: int = 120

    serper_api_key: str = ""

    # Weather
    weather_api_key: str = ""
    weather_stack_api_key: str = ""

    # Kernel V4 stable baseline
    kernel_orchestrator_version: str = "v4"
    kernel_agent_enabled: bool = True
    kernel_agent_data_enabled: bool = True
    kernel_agent_tool_enabled: bool = True
    kernel_agent_web_enabled: bool = True
    kernel_agent_rag_enabled: bool = True
    kernel_agent_timeout_sec: int = 30
    kernel_agent_max_parallel: int = 5
    kernel_agent_max_retry: int = 1
    kernel_agent_runtime_supervisor_enabled: bool = True
    kernel_answer_draft_confidence_threshold: float = 0.75
    kernel_answer_draft_max_chars: int = 220
    kernel_adaptive_mode_enabled: bool = True
    kernel_adaptive_profile_json: str = ""
    kernel_plan_memory_enabled: bool = True
    kernel_plan_memory_window: int = 50
    kernel_memory_context_enabled: bool = True
    kernel_enriched_identity_enabled: bool = True
    kernel_agent_dag_scheduling_enabled: bool = False
    kernel_agent_speculative_execution_enabled: bool = False
    kernel_agent_bus_enabled: bool = False
    kernel_agent_bus_require_worker: bool = False
    kernel_agent_bus_namespace: str = "opentrace:agent"
    kernel_agent_bus_mode: str = "pubsub"  # pubsub | stream
    kernel_agent_bus_group: str = "agent-workers"
    kernel_agent_bus_consumer: str = "worker-1"
    kernel_agent_bus_reclaim_idle_ms: int = 30000
    kernel_agent_bus_reclaim_count: int = 20
    kernel_agent_bus_max_retry: int = 2
    kernel_agent_bus_dlq_stream: str = "opentrace:agent:stream:dlq"

    # Cognition lexicon
    cognition_lexicon_json: str = ""

    # Text2SQL / Databases
    data_secret_key: str = "opentrace-data-secret-change-me"
    docker_host_alias: str = "host.docker.internal"
    text2sql_enabled: bool = True
    text2sql_max_retry: int = 2
    text2sql_default_limit: int = 100
    text2sql_join_inference_enabled: bool = True
    text2sql_max_join_depth: int = 3
    rag_min_evidence_score: float = 0.65
    rag_auto_fallback_to_web: bool = True
    rag_rerank_enabled: bool = True
    llmwiki_enabled: bool = True
    llmwiki_model: str = "qwen3.5-27b"
    llmwiki_top_k: int = 3
    kernel_fusion_enabled: bool = False
    kernel_critic_enabled: bool = False
    kernel_critic_max_retry: int = 2

    # V5 Routing Tier
    kernel_v5_routing_enabled: bool = True
    kernel_l0_rule_router_enabled: bool = True
    kernel_l1_tiny_router_enabled: bool = True
    kernel_semantic_cache_enabled: bool = True
    kernel_semantic_cache_threshold: float = 0.92
    kernel_semantic_cache_ttl_seconds: int = 3600
    kernel_semantic_cache_max_entries: int = 10000
    kernel_l1_router_model: str = "juniorshort"
    kernel_l1_fast_answer_model: str = "middleshort"
    kernel_l1_knowledge_model: str = "seniorshort"

    # ── Multi-turn conversation enhancement ──────────────────────────
    # Feature ⑤ ClarificationGate
    kernel_clarification_gate_enabled: bool = True
    kernel_clarification_confidence_threshold: float = 0.6

    # Feature ④ Error Correction & Incremental Re-planning
    kernel_correction_detection_enabled: bool = True
    kernel_refine_replan_enabled: bool = True

    # Feature ② Dialogue State Tracking
    kernel_dst_enabled: bool = True
    kernel_dst_query_length_threshold: int = 30

    # Feature ⑥ Conversation State (structured multi-turn)
    kernel_conversation_state_enabled: bool = True

    # Feature ① Context Compression & Summarization
    kernel_context_composer_enabled: bool = True
    kernel_compress_trigger_tokens: int = 3000
    kernel_compress_keep_recent_turns: int = 5

    # Token budget (used by kernel/token_counter.py)
    context_window_max_tokens: int = 8192
    context_max_history_tokens: int = 4096
    context_keep_recent_turns_min: int = 2

    # Feature ③ Memory Value Feedback Loop
    kernel_memory_value_scoring_enabled: bool = True
    kernel_memory_feedback_like_bonus: float = 0.3
    kernel_memory_feedback_dislike_penalty: float = -0.5
    kernel_memory_auto_decay_threshold: int = 3

    # Feature ⑥ Conversation Branching
    kernel_conversation_branching_enabled: bool = True

    # ── Attachment upload ─────────────────────────────────────────────
    attachment_upload_enabled: bool = True
    attachment_max_size_mb: int = 20
    attachment_storage_path: str = "/tmp/opentrace_attachments"
    attachment_max_chars: int = 4000
    multimodal_attachment_enabled: bool = True

    # ── Feature ⑦ CriticSelfCorrection REVISE loop ──────────────────────
    kernel_revise_loop_enabled: bool = True
    kernel_revise_max_iterations: int = 3
    kernel_revise_confidence_improvement_threshold: float = 0.05

    # ── Feature ⑧ Dynamic User Profiling ────────────────────────────────
    kernel_user_profiling_enabled: bool = True
    kernel_user_profiling_max_tags: int = 5

    # ── Rule versioning & grayscale release ─────────────────────────────
    kernel_rule_grayscale_enabled: bool = True
    kernel_rule_grayscale_default_percentage: int = 100

    # ── NER-based PII masking ──────────────────────────────────────────
    kernel_ner_masking_enabled: bool = True
    kernel_ner_masking_entity_types: str = "EMAIL,PHONE_CN,PHONE_INTL,CREDIT_CARD,ID_CN,IP_ADDRESS,PERSON_CN,LOCATION_CN,ORG_CN"

    # ── Canary testing & auto-rollback ────────────────────────────────
    kernel_canary_auto_rollback_enabled: bool = True
    kernel_canary_error_rate_threshold: float = 0.10
    kernel_canary_latency_multiplier: float = 2.0
    kernel_canary_min_samples: int = 100


class Settings(
    AppSettings,
    DatabaseSettings,
    RedisSettings,
    LLMSettings,
    EmbeddingSettings,
    RerankSettings,
    JWTSettings,
    SMTPSettings,
    OTelSettings,
):
    """Unified settings object — single source of truth."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()


# Convenience alias used across the codebase
settings = get_settings()
