"""
OpenTrace — Centralized Settings
All configuration is loaded once from environment/dotenv via pydantic-settings.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Literal, Self

from pydantic import AliasChoices, Field, field_validator, model_validator
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

    # Query LLM — Qwen is the first-party default for this deployment.  Other
    # providers/models remain configurable through the environment and the
    # Responses ``model`` field without changing the product default.
    default_llm_query_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_query_model: str = "qwen3.7-max"
    default_llm_query_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_query_api_key: str = ""
    default_llm_fast_model: str = Field(
        default="qwen3-8b",
        validation_alias=AliasChoices(
            "DEFAULT_LLM_FAST_MODEL", "DEFAULT_LLM_FAST_OPENAI_MODEL"
        ),
    )
    default_llm_deep_model: str = Field(
        default="qwen3.7-max",
        validation_alias=AliasChoices(
            "DEFAULT_LLM_DEEP_MODEL", "DEFAULT_LLM_DEEP_OPENAI_MODEL"
        ),
    )

    # Transitional Python aliases. Deployments keep accepting the old env
    # names above, while runtime code no longer describes Qwen as OpenAI.
    @property
    def default_llm_fast_openai_model(self) -> str:
        return self.default_llm_fast_model

    @property
    def default_llm_deep_openai_model(self) -> str:
        return self.default_llm_deep_model

    # Compress LLM
    default_llm_compress_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_compress_model: str = "qwen3.6-plus"
    default_llm_compress_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_compress_api_key: str = ""

    # Planning LLM
    default_llm_planing_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_planing_model: str = "qwen3.6-plus"
    default_llm_planing_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    default_llm_planing_api_key: str = ""

    # SeniorShort LLM (qwen3.6-plus) — knowledge Q&A, cheap critic
    default_llm_seniorshort_provider: str = "阿里巴巴Qwen(DashScope)"
    default_llm_seniorshort_model: str = "qwen3.6-plus"
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

    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 10080


class SMTPSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    smtp_host: str = "smtp.163.com"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_pass: str = ""
    smtp_from: str = ""
    # If unset, TLS mode is inferred from the conventional ports:
    # port 465 uses implicit TLS and port 587 uses STARTTLS.
    smtp_use_tls: bool | None = None
    smtp_start_tls: bool | None = None
    smtp_timeout_seconds: float = 15.0


class RegistrationSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    registration_enabled: bool = True
    registration_allowed_email_domain: str = "example.com"
    admin_email: str = "admin@example.com"
    password_prefix: str = ""
    # 本地开发：注册时若带 password 则直接激活（无需管理员审核）
    dev_registration_auto_activate: bool = True
    # 启动后种子账号（仅 app_env=development 时由 seed 脚本创建）
    dev_seed_user_enabled: bool = True
    dev_seed_user_email: str = "dev@example.com"
    dev_seed_user_password: str = "opentrace123"


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
    app_secret_key: str = ""
    app_host: str = "0.0.0.0"
    app_port: int = 14100
    debug: bool = False

    gateway_host: str = "0.0.0.0"
    gateway_port: int = 14100
    frontend_port: int = 14108

    vite_api_url: str = "http://localhost:14100"
    vite_ws_url: str = "ws://localhost:14100"

    # Gateway trust boundary. Non-default tenant headers must be signed by a
    # trusted reverse proxy and are bound to the authenticated user.
    trusted_tenant_header_secret: str = ""
    trusted_tenant_header_max_age_seconds: int = 300
    cors_allowed_origins: str = "http://localhost:14108,http://127.0.0.1:14108"

    use_pgvector: bool = True
    max_agent_steps: int = 8
    agent_timeout: int = 120

    serper_api_key: str = ""
    web_fetch_enabled: bool = False
    web_fetch_allowed_domains: str = ""
    web_fetch_timeout_seconds: float = 10.0
    web_fetch_max_redirects: int = 3
    web_fetch_max_response_bytes: int = 1_000_000
    connector_allowed_redirect_origins: str = (
        "http://localhost:14108,http://127.0.0.1:14108"
    )
    connector_oauth_state_ttl_seconds: int = 600

    # Weather
    weather_api_key: str = ""
    weather_stack_api_key: str = ""

    # Legacy 标签：/health 在 V4 启用时展示；V4 关闭时由 resolve_orchestrator_label 报告 vnext
    kernel_agent_enabled: bool = True
    kernel_agent_data_enabled: bool = True
    kernel_agent_tool_enabled: bool = True
    kernel_agent_web_enabled: bool = True
    kernel_agent_rag_enabled: bool = True
    kernel_agent_vision_enabled: bool = True
    # True: vision execute fails fast without image_urls/image_data (recommended for production).
    kernel_vision_require_images: bool = True
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
    # Every normal user-facing question must reach the primary LLM.  Rules,
    # caches and tool results may inform orchestration but may not become the
    # final answer by themselves.  Authentication, quota and explicit safety
    # rejections are intentionally handled before model execution.
    # Keep the strict contract configurable; the gateway still converts
    # definitive provider outages into a visible degradation response.
    kernel_all_questions_require_model: bool = True
    kernel_enriched_identity_enabled: bool = True
    kernel_identity_llm_enabled: bool = True  # True=LLM动态生成身份回答, False=回退固定答案
    kernel_agent_dag_scheduling_enabled: bool = True
    kernel_agent_speculative_execution_enabled: bool = True
    # Phase 2: UnifiedOrchestrator — one LLM call replaces 6+ scattered calls
    kernel_orchestrator_unified_enabled: bool = True
    # Phase 3: Fusion/Critic V2
    kernel_fusion_v2_enabled: bool = True
    kernel_critic_v2_enabled: bool = True
    # Cognitive Runtime — Phase 1: Rewrite + Understanding engines
    kernel_runtime_rewrite_enabled: bool = True
    kernel_runtime_understanding_enabled: bool = True
    # Cognitive Runtime — Phase 2: CognitivePlanner (upgraded from UnifiedOrchestrator)
    kernel_runtime_cognitive_planner_enabled: bool = True
    # Cognitive Runtime — Phase 3: Capability Graph + Agent executor mode
    kernel_runtime_capability_graph_enabled: bool = True
    kernel_agent_capability_executor_mode: bool = True
    # Cognitive Runtime — Phase 4: Evidence → Fusion V2 → Critic V2 → ArtifactComposer
    kernel_runtime_evidence_fusion_critic_enabled: bool = True
    # Cognitive Runtime — Phase 5: Workspace + Artifact composer
    kernel_runtime_artifact_composer_enabled: bool = True
    kernel_runtime_workspace_enabled: bool = True
    # Cognitive Runtime — V2 Pipeline (CognitivePlannerV2 → StrategyBuilder → ExecutionProjection)
    kernel_cognitive_planner_v2_enabled: bool = True
    kernel_governance_evidence_gate_enabled: bool = True
    kernel_governance_risk_gate_enabled: bool = True
    kernel_multi_question_runtime_v2_enabled: bool = True
    # Multi-goal: chain sub-question execution nodes via depends_on (priority order from GoalGraph)
    kernel_multi_goal_sequential_enabled: bool = True
    # Route data_query goals via services.data_intelligence_runtime (DataAgent V2 path)
    kernel_data_intelligence_routing_enabled: bool = True
    # When True, data_intelligence runtime delegates to full CognitiveExecutive after data agent
    kernel_data_intelligence_route_executive: bool = False
    kernel_refine_replan_enabled: bool = True
    kernel_refine_reexec_enabled: bool = True
    # Context Compression Runtime (prevents prompt inflation)
    kernel_context_compressor_enabled: bool = True
    # Evidence Lifecycle (state machine + ranking + resolution)
    kernel_evidence_lifecycle_enabled: bool = True
    # Capability Intelligence — Runtime self-cognition (rich profiles + feedback loop)
    kernel_capability_intelligence_enabled: bool = True
    # When False, learning_hook records feedback only; strategy_memory auto-write is shadow (no promotion)
    kernel_agent_learning_auto_apply: bool = False
    # Data V2: re-run cognitive DAG after verification fail (error_classifier + limited replans)
    data_agent_v2_verification_replan_enabled: bool = True
    data_agent_v2_verification_replan_max: int = 2
    # RAG: RRF merge across document / llmwiki / memory lanes before evidence intelligence
    rag_rrf_fusion_enabled: bool = True
    rag_rrf_k: int = 60
    # Capability Intelligence Phase 2 — Runtime self-cognition + orchestration learning
    kernel_capability_intelligence_phase2_enabled: bool = True
    # Phase 2 sub-features (independently toggled when master Phase 2 flag is ON)
    kernel_capability_knowledge_graph_enabled: bool = True
    kernel_capability_reasoner_enabled: bool = True
    kernel_capability_execution_memory_enabled: bool = True
    kernel_capability_strategy_memory_enabled: bool = True
    kernel_capability_evolution_enabled: bool = True
    # Evolution analysis interval (number of turns between full analysis passes)
    kernel_capability_evolution_interval: int = 10
    # Memory Truth Maintenance (confidence decay + contradiction detection + supersession)
    kernel_memory_truth_maintenance_enabled: bool = True
    # Deterministic Replay (prompt snapshots + runtime snapshots + execution replay)
    kernel_runtime_replay_enabled: bool = True
    # When True, invalid RuntimePhase transitions block execute phase
    kernel_runtime_phase_transition_strict: bool = True
    # Memory Fabric read path before legacy MemoryRouter buckets
    kernel_memory_fabric_retrieval_enabled: bool = True
    # When True, registry dispatch gate violations block handler invocation
    kernel_registry_dispatch_strict: bool = True
    # Agent Runtime V3 — manifest SSOT, UnifiedEvidence on EvidenceBus, GoalContribution metadata
    kernel_agent_runtime_v3_enabled: bool = True
    # When True, agent contributions must satisfy unified evidence + contract checks
    kernel_agent_runtime_v3_strict: bool = False
    # When True, successful turns require at least one UnifiedEvidence item
    kernel_unified_evidence_strict: bool = False
    # P3: hypothesis / contradiction / reflection metadata on turns
    kernel_agent_runtime_p3_enabled: bool = True
    # Goal-driven DAG: sub-goals map 1:1 to execution nodes (skip V2 gap decomposition)
    kernel_goal_driven_dag_enabled: bool = True
    # Goal Intelligence — split/merge/conflict before dispatch
    kernel_goal_supervisor_enabled: bool = True
    # Executive reflection → replan after critic/evidence (distinct from data_agent reflection)
    kernel_cognitive_iteration_enabled: bool = True
    kernel_cognitive_iteration_max: int = 2
    # StrategyMemory patterns surfaced to StrategicPlanner / selector
    kernel_strategy_memory_planner_enabled: bool = True
    # P1 — Claim graph, web coverage, capability score ranking, predictive world
    kernel_claim_graph_enabled: bool = True
    kernel_web_coverage_evaluator_enabled: bool = True
    kernel_web_coverage_max_rounds: int = 2
    kernel_capability_score_ranking_enabled: bool = True
    kernel_predictive_world_enabled: bool = True
    kernel_autonomous_goal_discovery_enabled: bool = True
    kernel_autonomous_goal_commit_enabled: bool = False
    kernel_self_optimizing_runtime_enabled: bool = True
    kernel_self_optimizing_runtime_apply: bool = False
    kernel_capability_evolution_enabled: bool = True
    kernel_capability_evolution_interval: int = 10
    # Persist cognitive runtime state to Redis per phase (requires Redis)
    kernel_cognitive_state_persist_enabled: bool = False
    # Persist full CognitiveStateGraph JSON to Redis (bus write path); defaults on when cognitive_state_persist in prod profile
    kernel_cognitive_state_graph_persist_enabled: bool = False
    kernel_cognitive_state_graph_ttl_seconds: int = 3600
    # Staging: extra strict phase transitions when app_env=staging
    kernel_staging_phase_transition_strict: bool = True
    # When True, policy mutation denials (plan/evidence/memory) abort the turn (prod opt-in)
    kernel_policy_mutation_fail_closed: bool = False
    kernel_world_state_persist_enabled: bool = False
    # Cross-process world model (P0 noop; see docs/architecture/world_model_cross_process.md)
    kernel_world_model_cross_process_enabled: bool = False
    kernel_world_model_cross_process_backend: str = "noop"  # noop | redis
    # Prefer web_intelligence agent over legacy web when registered
    kernel_web_intelligence_preferred: bool = True
    # Export semantic health alerts in turn metadata
    kernel_semantic_alerts_enabled: bool = True
    # Block execute when capability contract / topology validation fails
    kernel_capability_contract_strict: bool = True
    # Block fusion when evidence behavioral contract fails
    kernel_evidence_contract_strict: bool = True
    # Prefer fabric-only retrieval (skip legacy router when fabric returns hits)
    kernel_memory_fabric_primary_only: bool = True
    # Shadow memory relation graph to Redis (memory DB)
    kernel_memory_graph_redis_enabled: bool = True
    kernel_agent_bus_enabled: bool = True
    kernel_agent_bus_require_worker: bool = True
    kernel_agent_bus_namespace: str = "opentrace:agent"
    kernel_agent_bus_mode: str = "pubsub"  # pubsub | stream
    kernel_agent_bus_group: str = "agent-workers"
    kernel_agent_bus_consumer: str = "worker-1"
    kernel_agent_bus_reclaim_idle_ms: int = 30000
    kernel_agent_bus_reclaim_count: int = 20
    kernel_agent_bus_max_retry: int = 2
    kernel_agent_bus_dlq_stream: str = "opentrace:agent:stream:dlq"
    response_worker_poll_seconds: float = 2.0
    response_worker_batch_size: int = 20
    alert_scheduler_poll_seconds: int = 10
    alert_scheduler_retry_seconds: int = 60
    # When True, tenant daily turn/cost quotas use Redis counters (multi-replica safe)
    enterprise_quota_redis_enabled: bool = False
    enterprise_usage_redis_enabled: bool = False
    enterprise_tenant_rls_enabled: bool = False
    enterprise_billing_persist_enabled: bool = False
    enterprise_billing_prompt_per_million: float = 0.15
    enterprise_billing_completion_per_million: float = 0.60

    # Cognition lexicon
    cognition_lexicon_json: str = ""

    # Text2SQL / Databases
    data_secret_key: str = ""
    docker_host_alias: str = "host.docker.internal"
    text2sql_enabled: bool = True
    text2sql_max_retry: int = 2
    text2sql_default_limit: int = 100
    text2sql_max_result_rows: int = 500
    text2sql_statement_timeout_ms: int = 15000
    text2sql_join_inference_enabled: bool = True
    text2sql_max_join_depth: int = 3

    # Shared marketplace management is admin-only. Dynamic Python execution is
    # explicitly opt-in for local development until an isolated runner exists.
    skills_git_install_enabled: bool = False
    skills_local_create_enabled: bool = False
    skills_inprocess_execution_enabled: bool = False
    skills_subprocess_execution_enabled: bool = False
    skills_execution_timeout_seconds: int = 10
    skillhub_catalog_url: str = "https://skills.palebluedot.live"
    skillhub_sync_enabled: bool = True
    skillhub_sync_interval_seconds: int = 21600
    skillhub_sync_retry_seconds: int = 60
    skillhub_catalog_size: int = 30
    skillhub_min_security_score: int = 80
    # Server-side credential only. Never expose this token through frontend
    # configuration or accept it from a Skill installation request.
    skillhub_github_token: str = ""
    skillhub_github_timeout_seconds: float = 20.0
    skillhub_github_raw_fallback_enabled: bool = True
    rag_min_evidence_score: float = 0.65
    rag_auto_fallback_to_web: bool = True
    rag_rerank_enabled: bool = True
    rag_claim_anchor_enabled: bool = True
    rag_evidence_cluster_enabled: bool = True
    # Governed Knowledge Orchestration — knowledge is the primary RAG lane.
    knowledge_orchestration_enabled: bool = True
    knowledge_query_enabled: bool = True
    knowledge_auto_compile_enabled: bool = True
    # Deterministic compiler output remains publishable for compatibility;
    # production deployments can require review before promotion.
    knowledge_auto_publish: bool = True
    knowledge_max_relation_hops: int = 2
    knowledge_query_candidate_budget: int = 60
    knowledge_stale_after_days: int = 30
    llmwiki_enabled: bool = True
    llmwiki_model: str = "qwen3.5-27b"
    llmwiki_top_k: int = 3
    kernel_fusion_enabled: bool = True
    kernel_critic_enabled: bool = True
    kernel_critic_max_retry: int = 2

    # V5 Routing Tier
    # Skip full CognitiveSupervisor + executive graph for weather/time/tool intents
    kernel_tool_fast_path_enabled: bool = True
    # Retired V5 keyword routing tombstones; kept false for rolling config compatibility.
    kernel_v5_routing_enabled: bool = False
    kernel_l0_rule_router_enabled: bool = False
    kernel_l1_tiny_router_enabled: bool = False
    kernel_semantic_cache_enabled: bool = False
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
    # kernel_refine_replan_enabled — defined in Phase 2 block above

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

    # ── DataAgent V2 — Cognitive Data Core ────────────────────────────
    data_agent_v2_enabled: bool = True
    data_agent_v2_fallback_to_v1: bool = False
    # Knowledge Layer
    data_agent_v2_knowledge_retriever_enabled: bool = True
    data_agent_v2_use_metric_definitions: bool = True
    data_agent_v2_use_schema_metadata: bool = True
    data_agent_v2_use_table_relationships: bool = True
    data_agent_v2_use_analytical_skills: bool = True
    # Reasoning Layer Sub-Agents
    data_agent_v2_intent_enabled: bool = True
    data_agent_v2_entity_enabled: bool = True
    data_agent_v2_metric_enabled: bool = True
    data_agent_v2_time_enabled: bool = True
    data_agent_v2_join_enabled: bool = True
    data_agent_v2_semantic_enabled: bool = True
    data_agent_business_semantic_enabled: bool = True
    data_agent_v2_planner_enabled: bool = True
    data_agent_v2_compiler_enabled: bool = True
    data_agent_v2_sql_compiler_enabled: bool = True
    data_agent_v2_verifier_enabled: bool = True
    data_agent_v2_reflection_enabled: bool = True
    data_agent_v2_critic_enabled: bool = True
    # DAG & Supervisor
    data_agent_v2_dag_parallel_enabled: bool = True
    data_agent_v2_supervisor_max_retries: int = 2
    data_agent_v2_confidence_threshold: float = 0.40  # P0: circuit breaker
    data_agent_v2_repair_strategies_path: str = ""  # P1: externalized repair strategies JSON
    data_agent_v2_cognitive_events_enabled: bool = True  # P2: audit trail
    # Learning Layer (Phase 3)
    data_agent_v2_learning_enabled: bool = True
    data_agent_v2_auto_learning_enabled: bool = True
    data_agent_v2_pattern_memory_enabled: bool = True
    data_agent_v2_auto_metric_refinement_enabled: bool = True
    data_agent_v2_auto_schema_enrichment_enabled: bool = True
    # Advanced Analysis (Phase 4)
    data_agent_v2_advanced_analytics_mode: str = "auto"  # off | manual | auto
    data_agent_v2_statistical_enabled: bool = True
    data_agent_v2_insight_enabled: bool = True
    data_agent_v2_visualization_enabled: bool = True
    data_agent_v2_skill_execution_enabled: bool = True
    data_agent_v2_clarification_enabled: bool = True
    data_agent_v2_dag_parallel_timeout_sec: int = 30

    # ── Canary testing & auto-rollback ────────────────────────────────
    kernel_canary_auto_rollback_enabled: bool = True
    kernel_canary_error_rate_threshold: float = 0.10
    kernel_canary_latency_multiplier: float = 2.0
    kernel_canary_min_samples: int = 100

    @property
    def cors_origin_list(self) -> list[str]:
        return [item for item in self.cors_allowed_origins.split(",") if item]

    @property
    def web_fetch_domain_list(self) -> list[str]:
        return [
            item.strip().lower().rstrip(".")
            for item in self.web_fetch_allowed_domains.split(",")
            if item.strip()
        ]

    @property
    def connector_redirect_origin_list(self) -> list[str]:
        return [
            item.strip().lower().rstrip("/")
            for item in self.connector_allowed_redirect_origins.split(",")
            if item.strip()
        ]


class Settings(
    AppSettings,
    DatabaseSettings,
    RedisSettings,
    LLMSettings,
    EmbeddingSettings,
    RerankSettings,
    JWTSettings,
    SMTPSettings,
    RegistrationSettings,
    OTelSettings,
):
    """Unified settings object — single source of truth."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def _retire_v5_keyword_routing(self) -> Self:
        self.kernel_v5_routing_enabled = False
        self.kernel_l0_rule_router_enabled = False
        self.kernel_l1_tiny_router_enabled = False
        self.kernel_semantic_cache_enabled = False
        return self

    @field_validator("gateway_port", mode="after")
    @classmethod
    def _gateway_port_aligns_with_app(cls, v: int, info) -> int:
        """避免 .env 中 GATEWAY_PORT 与 APP_PORT 漂移（见 docs/CONFIG_TRUTH.md）。"""
        try:
            data = info.data if hasattr(info, "data") else {}
            app_port = int(data.get("app_port", 14100))
            if v != app_port and data.get("app_env") == "development":
                import warnings

                warnings.warn(
                    f"GATEWAY_PORT ({v}) != APP_PORT ({app_port}); "
                    "Compose/健康检查以 APP_PORT 为准",
                    stacklevel=2,
                )
        except Exception:
            pass
        return v

    @model_validator(mode="after")
    def _require_managed_env_port_alignment(self) -> Self:
        """staging/production 端口配置必须一致，避免健康检查与前端指向漂移。"""
        if self.app_env in {"staging", "production"} and self.gateway_port != self.app_port:
            raise ValueError(
                f"{self.app_env} requires GATEWAY_PORT ({self.gateway_port}) "
                f"to equal APP_PORT ({self.app_port})"
            )
        return self

    @model_validator(mode="after")
    def _apply_staging_profile(self) -> Self:
        """staging 环境强化开关（字段校验顺序无关，见 docs/ENV_PROFILES.md）。"""
        if self.app_env != "staging":
            return self
        if not self.kernel_memory_fabric_primary_only:
            self.kernel_memory_fabric_primary_only = True
        if not self.kernel_cognitive_state_persist_enabled:
            self.kernel_cognitive_state_persist_enabled = True
        if (
            self.kernel_staging_phase_transition_strict
            and not self.kernel_runtime_phase_transition_strict
        ):
            self.kernel_runtime_phase_transition_strict = True
        if not self.kernel_world_state_persist_enabled:
            self.kernel_world_state_persist_enabled = True
        if not self.kernel_policy_mutation_fail_closed:
            self.kernel_policy_mutation_fail_closed = True
        if not self.kernel_agent_runtime_v3_strict:
            self.kernel_agent_runtime_v3_strict = True
        if not self.kernel_unified_evidence_strict:
            self.kernel_unified_evidence_strict = True
        self.kernel_agent_learning_auto_apply = False
        self.skills_git_install_enabled = False
        self.skills_local_create_enabled = False
        self.skills_inprocess_execution_enabled = False
        self.skills_subprocess_execution_enabled = False
        return self

    @model_validator(mode="after")
    def _apply_production_profile(self) -> Self:
        """Production: align with docs/ENV_PROFILES.md (fabric, world, strict evidence)."""
        if self.app_env != "production":
            return self
        if not self.kernel_memory_fabric_primary_only:
            self.kernel_memory_fabric_primary_only = True
        if not self.kernel_world_state_persist_enabled:
            self.kernel_world_state_persist_enabled = True
        if not self.kernel_cognitive_state_persist_enabled:
            self.kernel_cognitive_state_persist_enabled = True
        if not self.kernel_policy_mutation_fail_closed:
            self.kernel_policy_mutation_fail_closed = True
        if not self.kernel_agent_runtime_v3_strict:
            self.kernel_agent_runtime_v3_strict = True
        if not self.kernel_unified_evidence_strict:
            self.kernel_unified_evidence_strict = True
        self.kernel_agent_learning_auto_apply = False
        self.skills_git_install_enabled = False
        self.skills_local_create_enabled = False
        self.skills_inprocess_execution_enabled = False
        self.skills_subprocess_execution_enabled = False
        return self

    @field_validator("cors_allowed_origins", "connector_allowed_redirect_origins")
    @classmethod
    def _validate_cors_origins(cls, value: str) -> str:
        origins = [item.strip() for item in str(value or "").split(",") if item.strip()]
        if "*" in origins:
            raise ValueError("origin allowlists must not contain '*'")
        return ",".join(origins)

    @model_validator(mode="after")
    def _require_runtime_secrets_for_managed_envs(self) -> Self:
        """staging/production 必须显式配置运行时密钥，避免空 key 进入签名与加密路径。"""
        if self.app_env not in {"staging", "production"}:
            return self
        missing = []
        placeholder_values = {"", "change-me", "change-me-in-production"}
        required = {
            "APP_SECRET_KEY": self.app_secret_key,
            "JWT_SECRET": self.jwt_secret,
            "DATA_SECRET_KEY": self.data_secret_key,
        }
        if self.enterprise_tenant_rls_enabled:
            required["TRUSTED_TENANT_HEADER_SECRET"] = self.trusted_tenant_header_secret
        for env_name, value in required.items():
            if str(value or "").strip() in placeholder_values:
                missing.append(env_name)
        if missing:
            joined = ", ".join(missing)
            raise ValueError(
                f"{self.app_env} requires explicit non-placeholder secrets: {joined}"
            )
        if self.web_fetch_enabled and not self.web_fetch_domain_list:
            raise ValueError(
                f"{self.app_env} requires WEB_FETCH_ALLOWED_DOMAINS when web fetch is enabled"
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings singleton."""
    return Settings()


# Convenience alias used across the codebase
settings = get_settings()
