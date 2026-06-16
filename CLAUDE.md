# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

OpenTrace is a cognitive kernel-centric agent system supporting conversational QA (sync/streaming), tool invocation (web/time/weather/code), reasoning chain visualization, and multi-version orchestration:
- **vNext (Cognitive Runtime V2)** (默认执行路径): `CognitiveSupervisor` → `RuntimeGateway` 统一编排，六域架构：**Cognitive**（规划/分解）、**Strategy**（能力路由/预算）、**Runtime**（DAG 执行/证据/融合/批评）、**Protocol**（域间稳定契约）、**Governance**（控制面，证据/风险门控）、**Goal**（一等目标生命周期，8 状态状态机）。含 Evidence Bus、Fusion/Critic、ArtifactComposer、TruthMaintenance、CognitiveHealthSnapshot 等完整认知链路
- **V5 Routing Tier**: L0 Rule Router + L1 TinyRouter + Semantic Cache + Complexity Engine (零 LLM 正则匹配 + LLMRole.ROUTER/FAST 分级路由)，作为 vNext 前处理层
- **Capability Intelligence** (`kernel/capability_intelligence/`): 运行时自认知层，从 "tool calling" 升级到 "capability cognition"，含知识图谱、执行记忆、策略记忆、失败记忆等
- **V4** (旧版回退, `kernel_orchestrator_v4_enabled=False`): Plan + Dispatcher + Agent Cluster + Fusion + Critic，通过 `legacy/` 兼容 shim 访问

The system uses Docker for unified deployment.

### vNext main path (architecture governance — do not bypass)

```
CognitiveKernel.process / stream
  → CognitiveSupervisor.prepare_run (GoalGraph, RuntimePolicyEngine, strategy_projection)
  → RuntimeGateway.run / stream (runtime lookup + dispatch only)
  → kernel.runtime.registry.dispatch_runtime
       ├─ cognitive_executive  → CognitiveExecutive
       ├─ data_intelligence    → services/data_intelligence_runtime (DataAgent V2 in-repo)
       └─ multi_goal           → multi_question_runtime
  → CognitiveSupervisor.run_outcomes (Artifact, GoalEvidenceBinding, governance, semantic metrics)
```

**Module boundaries:** `RuntimeGateway` must not call `evaluate_turn` or build artifacts. Goal planning and multi-question routing live in `kernel/cognitive_supervisor`. V4 is only `legacy/v4/` (+ thin `kernel/orchestrator_v4.py` re-export); default `kernel_orchestrator_v4_enabled=False`.

**Language / Runtime:** Python 3.11+, FastAPI, React/Vite frontend
**Package manager:** pip (`pip install -e ".[dev]"` 或 `pip install -r requirements.txt`)
**Config priority:** env var > `.env` > `infra/config/settings.py` defaults. 修改 `.env` 后需重启服务。
**Key reference docs:** `docs/FEATURE_FLAG_REGISTRY.md`（Feature Flag 注册表）, `docs/CONFIG_TRUTH.md`（端口/URL 真相表）, `docs/RELEASE_GATE.md`（PR 合并门禁）, `docs/ENV_PROFILES.md`（dev/staging/prod 推荐配置）

## Common Commands

### Running the Service

- Start all services (with migration checks): `bash start.sh`
- Stop services: `bash stop.sh`
- Force restart (recommended): `bash restart.sh`
- Start with observability: `bash start.sh --with-observability`
- Start with verification: `bash start.sh --verify`
- View API logs: `bash scripts/docker_logs.sh api`
- View agent-worker logs: `bash scripts/docker_logs.sh agent-worker`
- Full reset (including volumes): `bash stop.sh --volumes && bash start.sh`

**Important — Docker code deployment:** The Dockerfile uses `COPY . .` (not volume mounts), so source code is baked into the image at build time. Both `start.sh` and `restart.sh` run `docker compose up -d --build` which rebuilds images. However, Docker's layer cache may skip rebuilding the `COPY . .` step. When source changes don't seem to take effect in the running container, force a full rebuild:

```bash
docker compose build --no-cache api agent-worker && bash restart.sh
```

### Local Development (without Docker for API)

当需要快速迭代 Python 代码时，可以在宿主机运行 API，仅用 Docker 跑 PostgreSQL/Redis：

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 覆盖为宿主机地址（容器内主机名 postgres/redis 在宿主机无法解析）
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

前端始终在宿主机运行：`cd frontend && npm run dev`（端口 14108，代理 API 到 14100）。

### Verification Scripts

- Run all verification (local): `bash scripts/verify_all.sh`
- Run all verification (Docker): `bash scripts/verify_all_docker.sh`
- Verify agent cluster (V4 + RAG + bus): `bash scripts/verify_agent_cluster.sh`
- Verify agent bus end-to-end: `bash scripts/verify_agent_bus_e2e.sh`
- Verify migration idempotency: `bash scripts/verify_migration_idempotent.sh`
- Verify error envelope: `bash scripts/verify_error_envelope.sh`
- Verify E2E flow (login → chat → documents): `bash scripts/verify_e2e.sh`
- Run vNext all contract tests: `bash scripts/run_vnext_final_tests.sh`
- Run enterprise contract tests: `bash scripts/run_enterprise_contract_tests.sh`
- Check import boundaries: `bash scripts/check_import_boundaries.sh`（使用 `import-linter`，合并前必须通过）
- Check silent failures (kernel): `bash scripts/check_kernel_silent_failures.sh`
- Check silent failures (gateway): `bash scripts/check_gateway_silent_failures.sh`
- Verify kernel loop: `bash scripts/verify_kernel_loop.sh`

### Testing

- Run unit/contract tests: `pytest` (default test paths in `tests/`)
- Run a specific test: `pytest tests/path/to/test.py::test_function`
- Key contract test modules (按领域分组):
  - **编排与路由**: `test_orchestrator_v4_contract`, `test_v5_routing_contract`, `test_force_mode_routing`, `test_cognitive_runtime_contract`, `test_runtime_cognitive_executive`, `test_cognitive_supervisor_contract`, `test_vnext_architecture_contract`, `test_vnext_full_stack_contract`, `test_kernel_agent_loop`
  - **Data Agent V2**: `test_data_agent_v2_agent_contract`, `test_data_agent_v2_supervisor_contract`, `test_data_agent_v2_deterministic_agents_unit`, `test_data_cognition_pipeline`, `test_statistical_agent_unit`, `test_entity_filter_regression`
  - **RAG / 检索**: `test_rag_agent_contract`, `test_agent_bus_e2e_contract`
  - **认知控制**: `test_cognitive_controls_contract`, `test_intent_lock_full_pipeline`, `test_multi_turn_intent_inheritance`, `test_identity_guard`, `test_clarification_gate`, `test_clarification_supervisor_integration`
  - **Text2SQL**: `test_text2sql_validator_contract`, `test_text2sql_regression`, `test_sql_ranker`, `test_sql_reflector`
  - **多问题**: `test_multi_question_runtime_contract`
  - **记忆/语义**: `test_memory_evolve`, `test_semantic_api`, `test_semantic_layer`, `test_cognition_self_model_contract`
  - **Capability Intelligence**: `test_capability_intelligence`
  - **数据源**: `test_databases_api_contract`
  - 共 ~100 个测试文件

### Maintenance

- Apply baseline schema: `bash scripts/apply_provided_schema_to_docker.sh`
- Migrate local PostgreSQL to Docker: `bash scripts/migrate_local_pg_to_docker.sh`
- Clean session data: `bash scripts/clean_session.sh`
- Seed test user: `python scripts/seed_user.py`
- Memory evolution cycle: `python scripts/memory_evolve.py`
- Data retention cleanup: `python scripts/cleanup_retention.py`
- Replay execution trace: `python scripts/opentrace_replay.py <trace_id>`
- Pre‑flight release checks: `bash scripts/preflight_release.sh`
- Check migration history: `docker compose exec -T api alembic history --verbose`
- Upgrade migrations: `docker compose exec -T api alembic upgrade head`
- Create a new migration: `docker compose exec -T api alembic revision --autogenerate -m "description"`（然后验证幂等性：`bash scripts/verify_migration_idempotent.sh`）

### Database Migrations

Migrations live in `alembic/versions/`. Alembic is configured in `alembic.ini` and `alembic/env.py`.
All migrations are expected to be idempotent — verify with `bash scripts/verify_migration_idempotent.sh`.
The baseline schema is also available as `scripts/sql/provided_schema.sql` for reference.

## Docker Services

The `docker-compose.yml` defines the following core services:

- `postgres` – PostgreSQL with pgvector (port 5432)
- `redis` – Redis (port 6380 on host, 6379 in container)
- `api` – FastAPI gateway (port 14100)
- `agent-worker` – Agent worker consuming from Redis bus
- `prometheus` – Metrics scraping (port 9090)
- `jaeger` – Distributed tracing (port 16686)

All services are started together via `start.sh`. Use `docker compose ps` to see status.

## Frontend Development

The frontend is a React/Vite application in `frontend/`. For local development:

- Install dependencies: `cd frontend && npm install`
- Run dev server: `npm run dev` (serves on `http://localhost:14108`)
- Build for production: `npm run build`
- Run frontend tests: `npm run test` (uses Vitest)

The dev server proxies API requests to `http://localhost:14100`.

## Architecture

### High‑Level Layers

1. **Frontend** (React/Vite) – User interface at `http://localhost:14108`
2. **Gateway** (FastAPI) – API entry point at `http://localhost:14100`, handles auth, routing, SSE, health checks.
   - `gateway/api_gateway/` – REST API routes (chat, health, documents, auth).
   - `gateway/cognitive_gateway/` – Cognitive-aware gateway endpoints.
3. **Cognitive Kernel** (`kernel/`) – Core orchestration brain:
   - `cognitive_kernel.py`: unified `run`/`stream` entry, routes to `CognitiveSupervisor` → `RuntimeGateway` (vNext, default) or V4 orchestrator (legacy fallback).
   - `orchestrator_v4.py`: main orchestrator implementing **Plan + Dispatcher + Agent Cluster**.
   - `plan_agent.py` / `dag_plan.py` / `dag_scheduler.py`: decompose queries into DAG subtasks with parallel scheduling.
   - `dispatcher.py`: concurrent scheduling, timeout, degradation.
   - `context_builder.py` / `context_pipeline.py`: query context assembly pipeline.
   - `context/query_rewriter.py` (197 loc): multi-turn query rewriting (real implementation).
   - `context/context_compressor.py` (61 loc), `context/context_ranker.py` (65 loc): context compression & ranking (stubs).
   - `kernel/orchestrator.py` (103 loc): base orchestrator class (distinct from orchestrator_v4.py).
   - `kernel/json_parser.py` (38 loc): robust JSON parsing utilities.
   - `intent_engine/`: user intent recognition and routing.
   - `meta_cognition/` / `epistemology/`: self-assessment and knowledge confidence.
   - `fusion_engine/` and `critic_engine/`: merge results and critique.
   - `adaptive_profiles.py`: dynamic quality/speed profile switching.
   - `complexity_engine.py`: heuristic query complexity assessment (~100 loc). Real implementation; routes queries to L0/L1/v4 by scoring length, entities, clauses, and reasoning keywords.
   - `cognition/` / `data_cognition/`: entity recognition and canonical name resolution. 新文件:
     - `planner_facade.py` (180 loc): 三层规划 facade — `GoalPlanner` (目标分解), `ExecutionPlanner` (DAG 构建, 委托给 CognitivePlannerV2+StrategyBuilder+ExecutionProjection), `StrategicPlanner` (能力选择与路由提示), `RefinementPlanner` (失败后增量重规划)
     - `multi_question.py` (142 loc): CJK 感知的多问题检测与分解 — `is_multi_question()` (中文提示词检测), `classify_sub_question_domain()`, `split_by_syntax()` + `split_by_llm()` fallback
     - `multi_execution_planner.py` (202 loc): 多问题执行图构建器 — `build_multi_execution_graph()`, capability governance 集成, force_mode 能力映射
     - `cognitive_world_model.py` (49 loc): 统一 grounding facade，包装 `WorldModel` + `EntityRegistry`
     - `world_model.py` (267 loc): 语义 grounding — 中文/英文时间短语解析, 实体匹配, 冲突消解（time_range > region > metric > unknown）
     - `self_model.py` (179 loc): 系统能力评估, `introspect()` 返回 `CapabilityAssessment`（含 Capability Intelligence profiler 集成）
     - `types.py` (72 loc): `TaskDomain` 枚举 (7 种), `CapabilityAssessment`, `SelfState`, `GroundedEntity`
     - `entity_registry.py` (51 loc), `task_model.py` (44 loc), `sub_question.py` (13 loc)
   - `clarification_gate.py` (297 loc): detects vague queries and generates counter-questions. Used by Data Agent V2. Feature flag: `KERNEL_CLARIFICATION_GATE_ENABLED`.
   - `conversation_state.py` (385 loc): structured multi-turn conversation state tracking. Feature flag: `KERNEL_CONVERSATION_STATE_ENABLED`.
   - `cognitive_controls.py` (306 loc): deterministic cognitive controls — `IntentLock` (intent locking with task_type/complexity/allowed-disallowed capabilities), `CognitiveBudget` (limits on planning depth/capabilities/replans/memory/context), `classify_intent()` (pattern-based L0 intent classification: greeting/identity/capability_help/translation/summarization/document_qa/data_query/web_search/weather/time), `apply_intent_lock_to_context()`, `relevance_score()`/`passes_relevance_anchor()`. No feature flag gate.
   - `refine_planner.py`: bounded local replanning (341 loc, real implementation). Handles DAG node failures via FailureType (SCHEMA_MISMATCH/TIMEOUT/EMPTY_RESULT/HALLUCINATION/LOW_CRITIC) -> RepairStrategy (RETRY/SIMPLIFY/SUBSTITUTE/SPLIT/PREPEND/SKIP/ABORT). Max replan depth 2 layers. Flags: `KERNEL_CORRECTION_DETECTION_ENABLED`, `KERNEL_REFINE_REPLAN_ENABLED`.
   - `plan_memory.py`: cache and reuse successful execution plans (38 loc). Real implementation with thread-safe deque, score filtering, and query_type matching. Flag: `KERNEL_PLAN_MEMORY_ENABLED`.
   - `result_reference.py` / `result_ref_builder.py` / `reference_resolver.py`: cross-turn result referencing (stubs, ~32 loc each).
   - `turn_context.py`, `dialogue_state_tracker.py`: dialogue state tracking (16-17 loc stubs). Flag: `KERNEL_DST_ENABLED`.
   - `identity/` — System identity & persona enforcement:
     - `system_identity.py`: `SYSTEM_IDENTITY` prompt template, `CANONICAL_IDENTITY_RESPONSE` (fallback), `is_identity_user_query()`, `enforce_identity_output()` (post-process filter), `build_identity_llm_messages()` (context-aware identity prompt builder).
     - L0 identity queries ("你是谁") route through `orchestrator_v4._handle_identity_query()` → `LLMRole.IDENTITY` (MinShort 0.6B) → response cached in WorkingMemory with turn-sequence freshness check (expires after 5 turns).
     - Feature flag: `kernel_identity_llm_enabled` (True=LLM动态生成, False=回退固定答案).
   - `kernel/policy/`: runtime policy engine (bandit.py 165 loc, engine.py 228 loc, rl_engine.py 188 loc) — multi-armed bandit capability selection, RL-based policy optimization.
   - `kernel/prompt_engine/`: prompt construction (cognitive_prompt.py 386 loc, engine.py 41 loc).
   - `kernel/reasoning/`: symbolic reasoning engine (engine.py 198 loc, cognitive_kernel.py 65 loc).
   - `kernel/protocol/` — 域间稳定契约（503 行, 7 文件）:
     - `runtime_contract.py` (167 loc): 核心契约类型 — `Goal`, `GoalGraph`, `RuntimeTask`, `RuntimeArtifact`, `Constraints`, `CapabilityRef`, `Budget`, `EvidencePolicy`, `ExecutionPolicy`, `RuntimeContextRef`, `Provenance`, `ArtifactState`
     - `runtime_protocol.py` (34 loc): `RuntimePhase` 枚举, `RuntimeEnvelope`
     - `cognition_protocol.py` (36 loc): `CognitionPhase` 枚举, `CognitionEnvelope`, `PlanningArtifact`
     - `agent_protocol.py` (22 loc): `AgentMessageKind`, `AgentBusMessage`
     - `events.py` (67 loc): `CognitiveEventTypeV2`, `SpanStage`, `TraceContext` (trace_id/span_id/parent_span_id)
     - `mcp.py` (76 loc): Multi-Agent Cognitive Protocol — `Evidence`, `Hypothesis`, `Action`, `ActionPlan`, `Critique`, `AgentTrace`, `FailureTag`
     - `governance.py` (56 loc): `Budget`, `BudgetTracker`, `GovernanceProfile`, `QualityGate`, `QualityGateResult`
   - `kernel/web_engine/`: web search engine (search_client.py 35 loc, query_rewriter.py 41 loc, ranker.py 31 loc).
   - `kernel/token_counter.py` (192 loc): token counting with budget management.
   - `kernel/types.py` (100 loc): shared kernel type definitions.
   - `kernel/history_retriever.py` (117 loc): multi-turn history retrieval.
   - `kernel/preference_layers.py` (52 loc): user preference layer management.
   - **V5 Routing Tier**: `query_router_v2.py` (L0RuleRouter, ~150 loc), `complexity_engine.py` (~100 loc), `tiny_router.py` (~130 loc), `semantic_cache.py` (~220 loc), `context_assembler.py` (~180 loc). Real implementations. L0 uses zero-LLM regex matching; L1 uses LLMRole.ROUTER+FAST; semantic cache uses embedding similarity; context assembler uses token budgeting. `context_composer.py` remains a stub.
	   - **Cognitive Runtime V2** (`kernel/runtime/`, ~9900 lines, 45 files, all real implementations) — 下一代统一编排管线。核心组件:
	     - 顶层基础设施: `context.py` (RuntimeContext), `objects.py` (RuntimeObject/Evidence/ExecutionPlan/ExecutionNode/ExecutionBudget), `event_store.py` (RuntimeEventStore 审计日志), `capability.py` (CapabilityRegistry 统一目录), `policy.py` (UnifiedPolicyEngine), `constraint_layer.py` (5 维确定性守卫: budget/policy/risk/capability/historical), `execution_reasoning.py` (推理链追踪)
	     - Pipeline: `rewrite_engine.py` → `understanding_engine.py` → `cognitive_executive.py` (CognitiveExecutive) → `orchestrator.py` (UnifiedOrchestrator) → `capability_graph_builder.py` → `executor.py` (ExecutionRuntime DAG 执行) → `evidence_bus.py` (pub/sub 证据总线) → `fusion.py` (FusionEngineV2) → `critic.py` (CriticEngineV2) → `artifact_composer.py` + `artifacts.py` → `workspace.py` + `memory_fabric.py`
	     - `cognitive/` 子目录: `cognitive_planner_v2.py` (508 loc), `strategy_builder.py` (408 loc), `execution_projection.py` (286 loc), `decomposition_policy.py` (119 loc), `cognitive_graph.py` (326 loc)
	     - `evidence/` 子目录: `lifecycle.py` (165 loc), `ranking.py` (156 loc), `resolution.py` (250 loc), `state_machine.py` (122 loc)
	     - `memory/` 子目录: `truth_maintenance.py` (228 loc), `contradiction_resolution.py` (220 loc), `fact_supersession.py` (133 loc), `confidence_decay.py` (131 loc)
	     - `context_runtime/` 子目录: `context_compressor.py` (215 loc), `context_ranker.py` (145 loc), `evidence_selector.py` (105 loc), `memory_selector.py` (80 loc), `semantic_distiller.py` (195 loc) — 全部真实实现
	     - `replay/` 子目录: `prompt_snapshot.py`, `runtime_snapshot.py`, `execution_replay.py`, `deterministic_trace.py` — 每阶段 prompt/runtime 快照，支持确定性回放和审计
	     - Feature flags: `kernel_runtime_rewrite_enabled`, `kernel_runtime_understanding_enabled`, `kernel_runtime_cognitive_planner_enabled`, `kernel_runtime_capability_graph_enabled`, `kernel_runtime_evidence_fusion_critic_enabled`, `kernel_runtime_artifact_composer_enabled`, `kernel_runtime_workspace_enabled`, `kernel_runtime_replay_enabled` (全部默认 True)
	   - **Capability Intelligence** (`kernel/capability_intelligence/`, ~2500 lines, 12 files) — 运行时自认知层，将系统从 "tool calling" 升级到 "capability cognition":
	     - Phase 1: `profiler.py` (583 loc) — CapabilityProfiler 构建/丰富/查询能力画像; `adapter.py` — 将画像格式化为 LLM prompt; `feedback.py` — 从执行结果学习
	     - Phase 2: `knowledge_graph.py` (273 loc) — 能力间关系图; `reasoner.py` (170 loc) — 基于 KG + 执行历史的推理; `execution_memory.py` (195 loc) — 结构化时间窗口执行统计; `strategy_memory.py` (222 loc) — 策略模式成功追踪; `evolution.py` (252 loc) — 持续改进引擎
	     - `failure_memory.py` (250 loc): 失败记录/统计/模式识别，始终可用（无 feature flag 门控）
	     - Feature flags: `kernel_capability_intelligence_enabled` (Phase 1, default True), `kernel_capability_intelligence_phase2_enabled` (Phase 2, default True)
   - **Cognitive Supervisor** (`kernel/cognitive_supervisor/`, 260 行, 3 文件) — 位于 CognitiveKernel 和 RuntimeGateway 之间的中心协调层:
     - `supervisor.py` (148 loc): `CognitiveSupervisor.prepare_run()` — GoalGraph 物化、意图锁定 (IntentLock 传播)、governance 预检 (RuntimeGovernor + RuntimePolicyEngine)、多问题路径检测、strategy/budget 投影 metadata。返回 `SupervisorPreparedRun` (runtime_task, ctx, route_hint, governance_meta, semantic_observability)
     - `prepare_dispatch.py` (100 loc): `build_runtime_context_from_kernel_request()` + `runtime_task_from_request()` shared helpers
     - 单例: `get_cognitive_supervisor()`
   - **Goal** (`kernel/goal/`, 354 行, 7 文件) — 一等目标生命周期:
     - `state_machine.py` (72 loc): `GoalLifecycleState` 8 状态枚举 — CREATED → PROJECTED → EXECUTING → EVIDENCE_COLLECTED → FUSED → COMPLETED → ARCHIVED (+ FAILED from any active state), `transition_goal_state()` 验证合法转换
     - `goal_lifecycle.py` (17 loc): `bind_goal_graph_to_context()` — 初始化图状态，将根目标过渡到 PROJECTED
     - `goal_projection.py` (28 loc): `project_goal_graph_to_world_state()` — 映射到 runtime world state
     - `multi_goal_scheduler.py` (117 loc): `schedule_sub_goals_from_graph()` — 按优先级排序子目标，附带元数据并链接
     - `goal_runtime_hooks.py` (70 loc): 在 CognitiveExecutive 各阶段追踪目标状态，与 `cognitive_state/store.py` 集成
     - `goal_memory_binding.py` (41 loc): 将完成的目标轮次绑定到 Memory Fabric 关系图
   - **Governance** (`kernel/governance/`, 324 行, 10 文件) — 企业级 AgentOS 控制面:
     - `governance_center.py` (88 loc): `GovernanceCenter` 统一入口 — 构建全部 9 个 sub-governor, `evaluate_turn()` 一次调用执行 evidence/risk/audit/cognitive health 检查，返回 `TurnGovernanceBundle`
     - 9 个 sub-governor: `RuntimeGovernor` (预算耗尽/缺少 task_id/goal), `CapabilityGovernor` (allow/deny 列表), `EvidenceGovernor` (最少证据数/置信度), `RiskGovernor` (幻觉风险分级), `MemoryGovernor` (token 预算), `PolicyGovernor` (执行策略校验), `PromptGovernor` (快照注册), `AuditGovernor` (SemanticObservabilitySnapshot)
     - Feature flags: `kernel_governance_evidence_gate_enabled` (True), `kernel_governance_risk_gate_enabled` (True)
   - **Strategy** (`kernel/strategy/`, 55 行, 2 文件) — 薄 facade，为 runtime cognitive 模块提供稳定导入面:
     - `capability_chain.py` (46 loc): `CapabilityChainLink` dataclass + `resolve_capability_chain()` — 能力类型 → 策略 + ExecutionPolicy + 工具提示映射（含 `deny_web` 策略）
   - **Capability Runtime** (`kernel/capability_runtime/`, 53 行, 2 文件) — 能力运行时元数据:
     - `metadata.py` (49 loc): `CapabilityRuntimeMetadata` dataclass (version, risk_tier, cost_estimate, avg_latency, success_rate, dependencies, environments), `enrich_capability_ref()` 附加元数据到 `CapabilityRef.params`
4. **Agent Cluster** (`agents/`) – Parallel execution units:
   - `data_agent.py`: V1 structured data queries (Text2SQL). When `DATA_AGENT_V2_ENABLED=true` (default), most data queries route to Data Agent V2 instead.
   - `data_agent_v2/`: **Data Agent V2** — Cognitive Data Core (~7500 lines, 25+ files). V2 is a three-layer architecture:
     - **Knowledge Layer**: `knowledge_retriever.py`, `knowledge_updater.py`, `pattern_extractor.py`, `metric_refiner.py` — retrieves schema metadata, metric definitions, table relationships, and analytical skills.
     - **Reasoning Layer** — sub-agents for decomposing a data question: `intent_agent.py`, `entity_agent.py`, `metric_agent.py`, `time_reasoning_agent.py`, `join_agent.py`, `semantic_agent.py`, `planner_agent.py`, `sql_compiler_agent.py`, `verification_agent.py`, `reflection_agent.py`, `data_critic.py`, `error_classifier.py`.
     - **Supervisor**: `supervisor.py` — orchestrates the sub-agent pipeline with DAG parallel scheduling (`dag_builder.py`), circuit-breaker confidence threshold (default 0.40), and max retries (default 2). Externalized repair strategies in `repair_strategies.json`.
     - Advanced (Phase 4, mostly stubs): `insight_agent.py`, `statistical_agent.py`, `visualization_agent.py`, `skills_engine.py`, `feedback_collector.py`.
   - `web_agent.py`: web search (Serper API).
   - `rag_agent.py`: document + memory retrieval (pgvector, dynamic score threshold).
   - `tool_agent.py`: generic tool invocation (time/weather/code).
   - `skills_agent.py`: specialized skill invocation.
   - `rule_engine_agent.py`: rule-based lightweight agent (~90 loc). Real implementation with keyword matching + LLMRole.CHEAP_CRITIC for rule explanation.
   - `vision_agent.py`: image/chart interpretation (~80 loc). Real implementation using LLMRole.VISION for multimodal analysis. Flag: `kernel_agent_vision_enabled`.
   - `worker.py`: consumes from Redis bus (stream/pubsub modes).
   - `registry.py`: agent registration and discovery.
5. **Model Gateway** (`model/`) — Abstracts LLM calls with role‑based routing. Roles form a capability hierarchy:

   | Role | Typical Model | Purpose |
   |------|--------------|---------|
   | `QUERY` | qwen3.7-max | Primary reasoning & answer generation |
   | `PLANNING` | qwen3.6-plus | Task decomposition & plan generation |
   | `COMPRESS` | qwen3.6-plus | Context compression & memory summarization |
   | `ROUTER` | qwen3-1.7b (JuniorShort) | L1 intent classification |
   | `FAST` | qwen3-8b (MiddleShort) | Simple/FAQ direct answers |
   | `CHEAP_CRITIC` | qwen3-14b (SeniorShort) | Lightweight output critique |
   | `KNOWLEDGE` | qwen3-14b (SeniorShort) | Knowledge Q&A |
   | `IDENTITY` | qwen3-0.6b (MinShort) | Personalized identity responses (L0) |
   | `VISION` | qwen3.6-vl-plus | Image/chart interpretation |

   - `model/model_gateway/gateway.py`: role configs, circuit breaker, offline fallback, `merge_system_identity`.
   - `model/llm_adapter/`: provider adapters (DashScope, OpenAI-compatible).
6. **Memory** (`memory/`) – Multi‑layer memory. 关键模块:
	   - `memory/working_memory/` — 工作记忆 (372 loc): Redis 支持的 ring-buffer 对话窗口 + KV scratchpad, 24h TTL, identity 缓存 (5 轮过期)
	   - `memory/memory_router/` — 统一检索路由 (203 loc): MemoryRouter 联合检索 (vector/episodic/keyword/graph) + EvolutionMemoryRouter 增强版, process-wide singleton
	   - `memory/episodic_memory/` — 情景记忆 (70 loc): Redis 事件追加日志, 7 天 TTL
	   - `memory/semantic_memory/` — 语义记忆 (73 loc): InMemorySemanticStore 内存向量存储
	   - `memory/procedural_memory/` — 程序记忆 (60 loc)
	   - `memory/temporal_memory/` — 时序索引 (72 loc): 指数衰减权重 `score × 2^(-age/half_life)`
	   - `memory/evolution/` — 记忆演进: `evolution.py` (283 loc), `governance.py` (260 loc, 信心衰减/矛盾检测/来源追踪), `router.py` (247 loc, EvolutionMemoryRouter 9 大特性)
   - `memory/fabric/` — 记忆关系图 (93 行, 3 文件): `MemoryFabricRouter` 管理 memory_id↔goal_id↔capability_type↔evidence_id↔artifact_id 关系图, salience 指数衰减 (factor 0.95), `bind_turn_memory()` 便捷函数将回合记忆绑定到目标图, 单例 `get_memory_fabric_router()`
7. **Governance** (`governance/`, 顶层独立包) — 独立企业级控制面包，被 vNext 和 V4 共用:
   - 8 个 sub-governor: runtime/capability/evidence/risk/audit/memory/policy/prompt + `runtime_policy_engine.py` + `adaptive_risk_engine.py` + `execution_guardrails.py`
   - `semantic_metrics.py`: `CognitiveHealthSnapshot` dataclass (8 维认知健康指标: reasoning_drift, goal_stability, capability_entropy, memory_pollution_risk, evidence_integrity, planner_volatility, runtime_recovery_score, cognitive_saturation) + `compute_cognitive_health()` 启发式计算函数
   - 被 `kernel/cognitive_supervisor/` 和 `kernel/governance/` 导入使用
   - 与 `kernel/governance/` (vNext 内嵌 governance, 含 GovernanceCenter + 9 sub-governor) 是两层关系：顶层 `governance/` 提供独立可复用的 governor 实现，`kernel/governance/` 在 vNext 管线中通过 GovernanceCenter 统一编排它们
8. **Execution Plane** (`execution/`) – DAG engine (`dag_engine/` with cognitive nodes), tool router (`tool_router/router.py`), workflow engine (`workflow_engine/workflow.py`), and SQL execution sandbox.
9. **Plugins** (`plugins/`) – Plugin system for extending agent capabilities: `document_plugin.py` (RAG retrieval + upload), `web_plugin.py` (web search via Serper), `tool_plugin.py`, `knowledge_plugin.py`, `memory_plugin.py`, plus `chart/`, `code/`, `data/`, `file/` sub-plugins. `selector.py` handles plugin selection/dispatch.
10. **Tools** (`tools/`) – Tool registry (`registry/`), built-in tools (`builtin_tools/`), and provider adapters (`adapters/`).
11. **Safety** (`safety/`) – Guardrails (`guardrails/`), policy engine (`policy_engine/`), data masking (`masking/`), audit logging (`audit/`), explainability (`xai/`), and canary deployment (`canary/`).
12. **Skills** (`skills/`) – Skill runtime, marketplace store, and installed skills management.
13. **Connectors** (`connectors/`) – External service connectors: registry, SDK, and built-in connectors (e.g., GitHub).
14. **Sandbox Runtime** (`sandbox_runtime/`) – Code execution sandbox with multiple providers (local AST, gVisor, Firecracker).
15. **Infrastructure** (`infra/`) – Config (`config/settings.py`), storage, Redis, message bus, observability, error handling, guards.
16. **Legacy** (`legacy/`) – V4 兼容 shim (`legacy/v4/__init__.py`): 重导出 `CognitiveOrchestratorV4`, `OrchestratorV4Request`, `OrchestratorV4Response`, `VALID_FORCE_MODES` from `kernel/orchestrator_v4.py`。v6.0 前保持兼容，届时物理移动文件。
17. **Services** (`services/`) – 仓库内 service 运行时:
    - `file_parser.py`: `parse_attachment_content()` (stub), `get_image_raw_data()` (base64 编码图片，MIME 检测 png/jpg/gif/webp)
    - `data_intelligence_runtime/`: `run_data_intelligence_turn()` — 通过 RuntimeGateway 将 DataAgent (V1/V2) 集成到 cognitive runtime，返回 `CognitiveExecutiveResult` 兼容输出

### Data & Caching

- **PostgreSQL** – Business persistence: users, sessions, documents, memories, tasks, audit, data assets.
- **Redis** – Checkpoint, cache, session, rate‑limit, pub/sub, stream (agent bus).

### Key Configuration

- Orchestrator: vNext (Cognitive Runtime V2) 默认启用; V4 已禁用 (`kernel_orchestrator_v4_enabled=False`), 通过 `legacy/` 兼容 shim 访问
- Agent toggles: `KERNEL_AGENT_ENABLED=true`, `KERNEL_AGENT_DATA_ENABLED=true`, etc.
- Environment variables are defined in `.env.example` — copy to `.env` before starting.
- Key LLM config vars: `DEFAULT_LLM_QUERY_MODEL`, `DEFAULT_LLM_PLANING_MODEL`, `DEFAULT_LLM_COMPRESS_MODEL` (each with `_PROVIDER`, `_BASE_URL`, `_API_KEY` suffixes).
- Embedding: `EMBEDDING_PROVIDER` (default `hash`), `EMBEDDING_DIMS`, `EMBEDDING_BASE_URL`.
- Web search: `SERPER_API_KEY` required for `web_agent.py`.
- Draft answering: `KERNEL_ANSWER_DRAFT_CONFIDENCE_THRESHOLD` (default 0.75), `KERNEL_ANSWER_DRAFT_MAX_CHARS` (default 220).
- RAG: `RAG_MIN_EVIDENCE_SCORE` (default 0.65), controls evidence sufficiency threshold. Legacy code still references `RAG_MIN_SCORE` env var (0.35 fallback) but that var is not defined in settings.py.
- Frontend: `VITE_API_URL` and `VITE_WS_URL` in `.env` must point to the API gateway.

### Feature Flags (selected)

All flags are defined in `infra/config/settings.py` and configurable via `.env`. Key flags beyond the basic agent toggles:

- `KERNEL_IDENTITY_LLM_ENABLED` (default `True`) — Use LLM for dynamic identity responses instead of fixed canned text. **Real implementation.**
- `KERNEL_CLARIFICATION_GATE_ENABLED` (default `True`) — Detect vague queries and generate counter-questions. **Real implementation** in `kernel/clarification_gate.py` (297 loc).
- `KERNEL_CONVERSATION_STATE_ENABLED` (default `True`) — Structured multi-turn conversation state. **Real implementation** in `kernel/conversation_state.py` (385 loc).
- `KERNEL_CONTEXT_COMPOSER_ENABLED` (default `True`) — Context compression & summarization pipeline. `kernel/context/query_rewriter.py` (196 loc) is real; `context_compressor.py` and `context_ranker.py` are stubs.
- `KERNEL_ADAPTIVE_MODE_ENABLED` (default `True`) — Dynamic quality/speed profile switching based on query complexity. `complexity_engine.py` is a real heuristic implementation (~100 loc).
- `KERNEL_V5_ROUTING_ENABLED` (default `True`) — V5 routing tier (L0 Rule Router + L1 TinyRouter + semantic cache). Core components are real implementations.
- `KERNEL_SEMANTIC_CACHE_ENABLED` (default `True`) — Semantic (vector-based) answer cache. Real implementation (~220 loc) with embedding similarity, LRU eviction, and TTL. Skips identity queries to ensure canonical handling.
- `KERNEL_PLAN_MEMORY_ENABLED` (default `True`) — Cache and reuse successful execution plans. Real implementation (38 loc).
- `KERNEL_MEMORY_CONTEXT_ENABLED` (default `True`) — Memory context injection into LLM prompts.
- `KERNEL_CORRECTION_DETECTION_ENABLED` / `KERNEL_REFINE_REPLAN_ENABLED` (default `True`) — Error correction & incremental re-planning. Real implementation (341 loc) with `FailureType`/`RepairStrategy` enums and bounded 2-layer replanning.
- `KERNEL_DST_ENABLED` (default `True`) — Dialogue state tracking. Stub (16 loc).
- `KERNEL_USER_PROFILING_ENABLED` (default `True`) — User preference-based style hints.

**Governance 门控** (全部默认 `True`):
- `kernel_governance_evidence_gate_enabled` — EvidenceGovernor 每轮证据数量/置信度检查
- `kernel_governance_risk_gate_enabled` — RiskGovernor 幻觉风险评估（>=0.8 高风险, >=0.5 中风险）

**Cognitive Runtime V2 开关** (全部默认 `True`):
- `kernel_runtime_rewrite_enabled` — RewriteEngine query 改写
- `kernel_runtime_understanding_enabled` — UnderstandingEngine 语义理解
- `kernel_runtime_cognitive_planner_enabled` — CognitivePlannerV2 认知规划
- `kernel_cognitive_planner_v2_enabled` — CognitivePlannerV2 独立开关
- `kernel_runtime_capability_graph_enabled` — CapabilityGraph 能力图构建
- `kernel_agent_capability_executor_mode` — Capability Executor 模式
- `kernel_runtime_evidence_fusion_critic_enabled` — Evidence/Fusion/Critic 证据/融合/批评管线
- `kernel_runtime_artifact_composer_enabled` — ArtifactComposer 产物合成
- `kernel_runtime_workspace_enabled` — Workspace 工作区
- `kernel_runtime_replay_enabled` — Prompt/Runtime 快照和确定性回放
- `kernel_multi_question_runtime_v2_enabled` — 多问题运行时 V2
- `kernel_context_compressor_enabled` — 上下文压缩器
- `kernel_evidence_lifecycle_enabled` — 证据生命周期管理
- `kernel_memory_truth_maintenance_enabled` — 记忆真值维护

**Capability Intelligence 开关** (全部默认 `True`):
- `kernel_capability_intelligence_enabled` — Phase 1: CapabilityProfiler + Adapter + Feedback
- `kernel_capability_intelligence_phase2_enabled` — Phase 2 总开关
- `kernel_capability_knowledge_graph_enabled` — 能力知识图谱
- `kernel_capability_reasoner_enabled` — 能力推理器
- `kernel_capability_execution_memory_enabled` — 执行记忆
- `kernel_capability_strategy_memory_enabled` — 策略记忆
- `kernel_capability_evolution_enabled` — 持续演进引擎
- `kernel_capability_evolution_interval` (default `10`) — 演进分析间隔（轮次）

**编排器选型:**
- `kernel_orchestrator_v4_enabled` (default `False`) — V4 旧版编排器默认禁用

## Development Notes

- The main chat entry point is `gateway/api_gateway/routers/chat.py` – handles sync/streaming, permissions, data‑source context.
- vNext (Cognitive Runtime V2 + CognitiveSupervisor + RuntimeGateway) is the default execution path; V4 is the legacy fallback (`kernel_orchestrator_v4_enabled=False`).
- Agent Bus supports two modes: `pubsub` and `stream` (consumer‑group + ack + pending reclaim).
- All SQL queries are read‑only and bound to a `data_source_id` with post‑processing validation.
- Health endpoints:
  - `GET /api/v1/health` – basic liveness
  - `GET /api/v1/health/deps` – dependency health (database, Redis, agent worker, bus, orchestrator)
  - `GET /api/v1/health/runtime` – runtime info (orchestrator version, annotation switches, lexicon size)
- Default local development account: `songts@tuwan.com` / `123456`
- Code quality: `black .` (line-length=100), `ruff check .` (line-length=100, rules E/F/I/N/UP, ignores E501), `mypy .` (py3.11, strict=false, ignore_missing_imports), `import-linter`（导入边界检查，见 `scripts/check_import_boundaries.sh`）。所有配置在 `pyproject.toml`。
- Tests: `pytest` (asyncio_mode=auto, pythonpath=["."] so `import kernel` works without editable install).
- Pre‑commit hooks can be installed via `pre‑commit install`.

## Further Reading

- `README.md` – Quick start and high‑level overview
- `scripts/work_script.md` – Detailed script usage
- `.env.example` – Full environment variable catalog (~150 vars) including all feature flags
- `docs/FEATURE_FLAG_REGISTRY.md` – 内核 Feature Flag 注册表（所有开关的默认值与含义）
- `docs/CONFIG_TRUTH.md` – 端口、URL、RAG 阈值配置真相表
- `docs/RELEASE_GATE.md` – PR/发布合并门禁检查清单
- `docs/ENV_PROFILES.md` – dev / staging / production 推荐开关配置
- `docs/adr/` – 架构决策记录（vNext / Governance / Memory）
- `docs/runbooks/` – 排障 runbook（回合追踪、证据门禁等）
- `docs/catalog/` – 各模块详细说明（cognitive_kernel, agent_runtime, data_agent, rag_retrieval, memory_system 等）

## 语言规范
请严格遵守以下规则：
1. 所有对话、解释、建议必须使用**简体中文**。
2. 代码注释必须使用中文