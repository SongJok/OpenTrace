# OpenTrace 项目全量代码梳理（Cursor 版 · Enterprise Cognitive OS）

> **事实来源**：仅以当前仓库源码、`infra/config/settings.py`、`.env.example`、`docker-compose.yml`、`importlinter.ini`、启动/验证脚本与 `tests/` 契约为准。  
> **格式基线**：在 `docs/service/service_claude.md` 目录深度上扩展；本文增加 **企业控制面**、**每 Agent 内部管线**、**全链路走向图**（含 Tier0 / Tool 快路径经 RuntimeGateway）、**流式/SSE 企业字段**、**前端 turn_meta 契约**、**Capability 执行路由**、**Agent Topology Manifest**、**Redis 配额原子预留** 与 **发布门禁** 的完整索引。  
> **最后更新**：2026-06-14（全量覆写：P0–P2 认知平台 · evolution 去重 · autonomous goal commit · `service_cursor` 重构；测试 **1246**）  
> **需求矩阵**：`docs/ARCHITECTURE_REQUIREMENTS_MATRIX.md`（#1–#30）。  
> **架构定义**：**Runtime-First Cognitive Architecture** — Agent 为 Capability Provider；Goal / Evidence / Memory / World 经 **RuntimeContribution** + **CognitiveStateGraph** 统一演化（**bus 单写** + Redis 可选）。  
> **测试规模**：`PYTHONPATH=. pytest tests/ --collect-only` → **1246** 个用例；合并门禁见 §38；`lint-imports --config importlinter.ini`；`python -m alembic heads` 应单 head（当前 **`20260613_documents_tenant`**）。  
> **Turn Envelope SSOT**：`docs/architecture/turn_envelope_field_mapping.md` + `frontend/src/utils/streamEnvelope.ts`。  
> **生产主路径**：`CognitiveKernel` → **`RuntimeGateway`**（Tier0 / Tool 快路径）→ `CognitiveSupervisor.prepare_run`（`enrich_turn_before_dispatch` 可选）→ `RuntimeTurnDispatcher` → `registry` → `cognitive_executive` | `data_intelligence` | `multi_goal` → `run_outcomes` → `turn_outcomes` / `enterprise_outcomes` / `finalize_turn`（计费 + **`finalize_semantic_and_evolution`** + **world finalize** + `learning_hook`）。

---

## 目录

1. [项目定位与产品边界](#1-项目定位与产品边界)
2. [当前代码状态摘要](#2-当前代码状态摘要)
3. [技术栈与依赖](#3-技术栈与依赖)
4. [整体架构与六域模型](#4-整体架构与六域模型)
5. [vNext 主路径（强制遵守）](#5-vnext-主路径强制遵守)
6. [端到端流程走向总图](#6-端到端流程走向总图)
7. [目录结构与模块地图](#7-目录结构与模块地图)
8. [前端应用](#8-前端应用)
9. [API 网关与路由清单](#9-api-网关与路由清单)
10. [聊天主链路（同步 / SSE / 企业预检 / Tier0）](#10-聊天主链路同步--sse--企业预检--tier0)
11. [认知内核与认知控制](#11-认知内核与认知控制)
12. [V5 路由层与快路径（经 RuntimeGateway）](#12-v5-路由层与快路径经-runtimegateway)
13. [V4 编排器（遗留、默认禁用）](#13-v4-编排器遗留默认禁用)
14. [RuntimeGateway、Supervisor 与 TurnDispatcher](#14-runtimegatewaysupervisor-与-turndispatcher)
15. [Cognitive Runtime V2（Executive 管线）](#15-cognitive-runtime-v2executive-管线)
16. [Goal 生命周期、多目标与 turn_outcomes](#16-goal-生命周期多目标与-turn_outcomes)
17. [认知规划门面与多问题运行时](#17-认知规划门面与多问题运行时)
18. [Runtime Registry、Tier-1 与 Data Intelligence](#18-runtime-registrytier-1-与-data-intelligence)
19. [Agent 集群总览与 Worker](#19-agent-集群总览与-worker)
20. [各 Agent 内部管线（逐 Agent）](#20-各-agent-内部管线逐-agent)
21. [DataAgent V2 子 Agent 与 DAG](#21-dataagent-v2-子-agent-与-dag)
22. [数据源、语义层与 Text2SQL](#22-数据源语义层与-text2sql)
23. [RAG、证据图与 RAG V3 智能层](#23-rag证据图与-rag-v3-智能层)
24. [记忆系统与 Memory Fabric](#24-记忆系统与-memory-fabric)
25. [Capability OS、Control Plane 与执行路由](#25-capability-oscontrol-plane-与执行路由)
26. [World Model、Redis 与 Shared World State](#26-world-modelredis-与-shared-world-state)
27. [企业多租户、配额、计费与审计](#27-企业多租户配额计费与审计)
28. [Policy Runtime 与变异点治理](#28-policy-runtime-与变异点治理)
29. [工具、技能、插件与连接器](#29-工具技能插件与连接器)
30. [规则引擎与灰度](#30-规则引擎与灰度)
31. [执行平面、DAG 与 Agent Bus](#31-执行平面dag-与-agent-bus)
32. [模型网关、Token 计量与 Embedding / Rerank](#32-模型网关token-计量与-embedding--rerank)
33. [治理体系（canonical kernel.governance）](#33-治理体系canonical-kernelgovernance)
34. [安全、审计、沙箱与可解释性](#34-安全审计沙箱与可解释性)
35. [基础设施、配置、Flag 治理与环境 Profile](#35-基础设施配置flag-治理与环境-profile)
36. [数据库模型与迁移](#36-数据库模型与迁移)
37. [部署、脚本与本地开发](#37-部署脚本与本地开发)
38. [测试体系与发布门禁](#38-测试体系与发布门禁)
39. [架构治理文档矩阵](#39-架构治理文档矩阵)
40. [开发规范与代码阅读顺序](#40-开发规范与代码阅读顺序)
41. [已知风险、架构债与演进](#41-已知风险架构债与演进)
42. [SSE 与流式事件契约](#42-sse-与流式事件契约)
43. [Kernel / Runtime / Goal / Enterprise 模块索引](#43-kernel--runtime--goal--enterprise-模块索引)
44. [工程变更日志](#44-工程变更日志)
45. [附录：与 service_claude 的差异](#45-附录与-service_claude-的差异)
46. [Runtime-First 统一运行时（Contribution / StateGraph）](#46-runtime-first-统一运行时contribution--stategraph)
47. [计费、账本与 Alembic 企业表](#47-计费账本与-alembic-企业表)
48. [Turn Envelope 字段映射详表](#48-turn-envelope-字段映射详表)
49. [需求矩阵、成熟度与近期落地索引](#49-需求矩阵成熟度与近期落地索引)
50. [P0/P1/P2 认知平台能力专章](#50-p0p1p2-认知平台能力专章)

**附录索引**：A [CognitiveKernel 分支](#附录-acognitivekernelrun-内部分支细化) · B [Executive × Policy](#附录-bcognitiveexecutive-阶段与-policy-钩子对照) · C [import 边界](#附录-cimport-边界与单实现治理运维速查) · D [DataAgent V2 文件清单](#附录-ddataagent-v2-文件清单agentsdata_agent_v2) · E [Redis Key](#附录-eredis--持久化-key-约定节选) · F [环境变量](#附录-f关键环境变量索引envexample-对照) · G [Runtime 解析规则](#附录-gruntimeturndispatcherresolve_runtime_name-决策树) · H [Agent Runtime V3](#附录-hagent-runtime-v3-与-tier-拓扑) · I [RuntimeGateway 快路径](#附录-iruntimegateway-快路径-api) · J [Manifest / DAG 校验](#附录-j-manifest-与-bootstrapdag-校验) · [§48 Turn Envelope 详表](#48-turn-envelope-字段映射详表)

---

## 1. 项目定位与产品边界

OpenTrace 是以 **Cognitive Kernel** 为唯一聊天中枢的 **AgentOS / Enterprise Cognitive OS** 后端：把对话、RAG、工具、联网、数据分析、记忆、任务、审计、技能市场、连接器、附件、多租户与运行时观测组织成可 Docker 部署的一体化服务，并配套 React 管理端。

| 能力域 | 代码锚点 | 对外表现 |
|--------|----------|----------|
| 统一认知入口 | `kernel/cognitive_kernel.py` | 所有 `/api/v1/chat` 经 `CognitiveKernel.run/stream`（复杂路径仅 `RuntimeGateway`） |
| 快路径统一入口 | `kernel/runtime_gateway.py` | Tier0 数据/SQL、Tool 天气时间经 Gateway，metadata 与 manifest 一致 |
| 意图与预算 | `kernel/cognitive_controls.py` | Intent Lock、CognitiveBudget、零 LLM 分类 |
| 分层路由 | V5：`query_router_v2`、`semantic_cache`、`tiny_router` | L0 / L0.5 / L1，降本降延迟 |
| **vNext 编排** | `RuntimeGateway` + `CognitiveSupervisor` + `RuntimeTurnDispatcher` | Goal、治理、证据、Artifact、Replay |
| **企业控制面** | `control_plane/`、`tenant/`、`gateway/chat_preflight.py` | 预检、配额、合规、PII、租户头 |
| **Goal-centric Runtime** | `kernel/goal/*` | 状态机、回合收尾、Evidence/Memory 绑定、Portfolio |
| **Policy Runtime** | `kernel/governance/policy_runtime.py` | plan / evidence / memory / replay 变异点 |
| **World State** | `kernel/cognition/runtime_grounding.py`、`world/` | 七切片 + Goal 切片 + Redis 可选持久化 |
| 数据智能 | `agents/data_agent_v2/` + `services/data_intelligence_runtime` | Text2SQL；澄清门控；`turn_metadata`；`evidence_objects`（V3 strict） |
| 检索增强 | `agents/rag_agent.py` + `services/rag_evidence_intelligence.py` | HyDE、混合检索、证据图、矛盾检测 |
| 联网智能 | `agents/web_intelligence_agent.py`（CognitiveAgent） | 搜索 → rank → evidence graph；manifest `web_search` |
| 多 Agent | `agents/*` + `execution` 平面 | Redis Agent Bus（stream / pubsub） |
| 记忆 | `memory/*` + `memory/fabric/` | 六层记忆 + TMS bridge + Redis graph shadow |
| 治理 | **`kernel/governance/`**（唯一 Governor 实现） | 证据/风险/审计/语义健康/合规审计 store |
| 可观测 | OTel、Prometheus、`enterprise_telemetry`、`turn_metering` | `/health/*`、**`/health/cognitive-os`**、企业指标 |
| **拓扑契约** | `kernel/agent_runtime/agent_topology_manifest.yaml` | bootstrap / worker / bus / capability contract SSOT |
| **前端协议** | `frontend/src/utils/streamEnvelope.ts` | `final_answer` → `TurnMetaEnvelope` → `turn_meta` UI |
| **P0 认知平台** | `goal_supervisor`、`cognitive_iteration`、`strategy_pattern` | 多 KPI 拆目标、Reflection→Replan、策略记忆进 Planner |
| **P1 决策智能** | `claim_graph`、`coverage_evaluator`、`capability_score`、`predictive_world` | 声明图、Web 补搜、能力排序、预测 World 切片 |
| **P2 自优化** | `self_optimizing_runtime`、`evolution_hook`、`autonomous_goal_discovery` | 语义健康 hint、能力演化、自主目标 proposal |

**非目标（当前仓库）**：

- 前端默认**不在** `docker-compose.yml` 核心栈内，需 `frontend` 本地 `npm run dev`。
- 跨进程/多副本 **World Model** 强一致仍为架构债（单进程 + Redis `world_state:{session_id}`）。
- Postgres **RLS POLICY** 全表启用需独立 migration 工程。
- 真实发票级计费仍为 token 估价 + 内存/Redis 聚合（`tenant/usage_metering.py`）。
- 本文档**不**写入 `.env` 中真实密钥。

---

## 2. 当前代码状态摘要

| 维度 | 状态（2026-06-14） |
|------|---------------------|
| API | FastAPI，`APP_PORT` / 健康检查默认 **14100**（`GATEWAY_PORT` 可与 Compose 映射不同，以 `APP_PORT` 为准） |
| 前端 | React 18 + Vite + TS，默认 **14108** |
| 主聊天 | `POST /api/v1/chat`（同步 + SSE） |
| 编排 | **vNext**；`kernel_orchestrator_v4_enabled=false` |
| 健康 `orchestrator` | `orchestrator_label.py`：V4 关 → **`vnext`** |
| Tier0 SSOT | `kernel/runtime/tier0_paths.py`；Gateway `tier0_paths.py` 仅 re-export + `DataQueryRequest` 注入 |
| Tool 快路径 | `kernel/fast_tool_path.py`；入口 `RuntimeGateway.try_tool_fast_path` / `stream_tool_fast_path` |
| Agent Bus | `KERNEL_AGENT_BUS_ENABLED`、stream 模式 |
| DataAgent | V2 默认 `data_agent_v2_enabled=true`；`turn_metadata` + `build_data_success_evidence_objects` |
| Web 执行路由 | `kernel_web_intelligence_preferred=true` 时 `web` → `web_intelligence`；`CapabilityAdapter` + manifest |
| Agent Runtime V3 | `kernel_agent_runtime_v3_enabled`；**staging** 强制 `kernel_agent_runtime_v3_strict` + `kernel_unified_evidence_strict` |
| P0–P2 认知平台 | GoalSupervisor · ClaimGraph · Evolution · SelfOptimizing | §50、`ARCHITECTURE_REQUIREMENTS_MATRIX` #18–#30 |
| 配额 Redis | `enterprise_quota_redis_enabled` → `reserve_turn_quota` Lua；`finalize_turn` 优先 `consume_turn_quota_async` |
| 测试 | **1246** collected |
| Turn bootstrap | `kernel/turn_bootstrap.py` | Gateway + Kernel `run`/`stream` + `resume_turn`；`dispatch_query` SSOT |
| Turn enrichment | `kernel/turn_enrichment.py` | 多轮/偏好/Context Fabric；`runtime_agent_params_from_context` 含 tenant |
| 文档租户 | `documents.tenant_id` + `workspace_id` | Alembic `20260613_documents_tenant`；RAG 等值过滤 |
| Nightly CI | `.github/workflows/nightly-multi-turn.yml` | multi_turn 场景 + 可选 RAG E2E |
| v6 预备 | `test_v6_v4_import_gate_contract.py` | 非 allowlist 不得 `import kernel.orchestrator_v4` |
| 多轮解析 | `kernel/multi_turn_resolution.py` | DST + ReferenceResolver；`run`/`stream` 在 intent 前 |
| World 回合 | `world_turn_begin.py` / `world_turn_finalize.py` | hydrate（Redis/cross-process）+ finalize 投影 |
| 偏好注入 | `kernel/preference_injection.py` | chat 预组装 + Kernel 回合 metadata |
| RAG/Web 证据 | `enrich_evidence_intelligence` | 统一 rank/graph/**claim_anchor** |
| Data 学习 | Supervisor auto_mode + `learning_hook` | 成功/熔断均写 failure_memory 或 strategy 信号 |
| Manifest 校验 | `validate_manifest_integrity()` + `validate_bootstrap_parity()` |
| Data V2 熔断 | `data_v2_failure_memory` → `failure_memory`（`low_confidence_circuit_breaker`） |
| Vision | `kernel_vision_require_images=true` 无图即 `error` |
| CognitiveStateGraph | **生产**（`bus.apply_runtime_contribution_to_bus` 单写；Redis `cog_state_graph:*` 可选） |
| CI | `ci-fast.yml` 含 `lint-imports`；`weekly_release_checklist.sh` 8 步 |
| Manifest | **3.1.0**（`validate_manifest_integrity`；worker 含 `rules` 但不 bus） |
| Web 单轨 | `kernel_web_intelligence_preferred` → 仅 `web_intelligence` bootstrap |
| RuntimeContribution | `runtime_contribution.py` + dispatch + Executive + `stream_metadata` |
| Turn Envelope | `docs/architecture/turn_envelope_field_mapping.md` |
| Alembic head | `20260611_billing_invoice`（经 `20260610_merge_cognitive_enterprise_heads`） |
| Import 边界 | `kernel/**` 不得 `from governance.*` |

### vNext / Enterprise 相关默认（摘录）

```text
kernel_goal_driven_dag_enabled=true
kernel_runtime_phase_transition_strict=true
kernel_registry_dispatch_strict=true
kernel_evidence_contract_strict=true
kernel_memory_fabric_primary_only=true
kernel_web_intelligence_preferred=true
kernel_world_state_persist_enabled=false   # staging/production 可强化
data_agent_v2_enabled=true
data_agent_v2_clarification_enabled=true
kernel_orchestrator_v4_enabled=false
enterprise_quota_redis_enabled=false       # staging 推荐 true
```

---

## 3. 技术栈与依赖

### 3.1 后端

Python **3.11+**、FastAPI、SQLAlchemy 2.0 asyncio、asyncpg、Alembic、pgvector、Redis 7、OpenAI-compatible LLM（多 `LLMRole`）、sqlglot、pydantic-settings、black/ruff/mypy、OpenTelemetry、prometheus-client、import-linter。

### 3.2 前端

React 18、TypeScript、Vite、Zustand、react-router-dom、react-markdown、Recharts、Vitest（契约测试 `*.contract.test.ts`）。

### 3.3 Docker Compose 核心服务

`api`（:14100）、`agent-worker`、`postgres`（pgvector）、`redis`（宿主常 6380）、可选 `prometheus` / `jaeger`。

---

## 4. 整体架构与六域模型

| 域 | 职责 | 主要目录 |
|----|------|----------|
| **Cognitive** | 规划、理解、多问题、World Model | `kernel/cognition/` |
| **Strategy** | 能力链、预算、路由提示 | `kernel/strategy/`、`capability_runtime/` |
| **Runtime** | Executive、证据、融合、批评、Artifact、**tier0_paths** | `kernel/runtime/` |
| **Protocol** | 稳定契约 | `kernel/protocol/` |
| **Governance** | 控制面、Policy Runtime、合规审计 | **`kernel/governance/`** |
| **Goal** | 一等目标生命周期 | `kernel/goal/` |
| **Enterprise** | 租户、配额、计费、遥测 | `tenant/`、`control_plane/`、`observability/` |
| **Agent Runtime** | Manifest、Tier-2、Bus、贡献度、UnifiedEvidence | `kernel/agent_runtime/` |

```text
Frontend :14108
    │ HTTP / SSE + X-Tenant-Id / X-Org-Id / X-Workspace-Id
    ▼
gateway/api_gateway/main.py
    │ chat_preflight · tenant RLS session vars · reset_turn_tokens
    ▼
CognitiveKernel
    │ classify_intent · V5 · memory_injection · ContextFabric
    │ tool_fast_path → RuntimeGateway.try_tool_fast_path（早退）
    ▼
RuntimeGateway
    │ try_tier0_chat（chat 路由在 HTTP 层调用，见 §10）
    │ CognitiveSupervisor.prepare_run + control_plane_gate
    ▼
RuntimeTurnDispatcher → registry (Tier-1)
    ├─ cognitive_executive
    ├─ data_intelligence
    └─ multi_goal
    ▼
run_outcomes + turn_outcomes + enterprise_outcomes + finalize_turn（async quota）
```

---

## 5. vNext 主路径（强制遵守）

```text
CognitiveKernel.process / stream
  → [可选] RuntimeGateway.try_tool_fast_path（weather/time/force tool）
  → CognitiveSupervisor.prepare_run
      → control_plane_gate（可选拒绝 control_plane_denied）
      → RuntimePolicyEngine + RuntimeGovernor
      → Goal bind / projection / fabric seed / world hydrate
      → dispatch_enrichment（AdaptiveRisk、grounding、fabric_graph_live）
  → RuntimeGateway.run / stream
  → RuntimeTurnDispatcher.run_turn / stream_turn
  → runtime.registry.dispatch_runtime (+ registry_governance)
  → handler
  → executive_result_to_kernel_response / multi_question_to_kernel_response
  → enrich_turn_enterprise_metadata（配额消耗、审计、遥测、world persist）
  → post_turn_enterprise_accounting（finalize_turn：usage + quota async）
```

| 禁止 | 校验 |
|------|------|
| Gateway 内跑 Executive / Planner | importlinter、supervisor 契约 |
| vNext 路径 import `legacy.v4` 实现体 | `check_import_boundaries.sh` |
| `kernel/**` 直接 `from governance.*` | `test_kernel_import_boundaries` |
| Gateway 内单独拼 Artifact 终态 | `run_outcomes` 拥有 |
| Tier0 业务逻辑仅存在于 gateway（无 kernel SSOT） | `test_runtime_gateway_tier0_contract` |

```bash
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
bash scripts/check_import_boundaries.sh
```

---

## 6. 端到端流程走向总图

### 6.1 同步聊天（复杂路径）

```text
POST /api/v1/chat (stream=false)
  │
  ├─ build_tenant_metadata(http_request, user_id)
  ├─ run_chat_preflight(query, tenant_md)  → PII + EnterpriseControlPlane.evaluate_turn
  ├─ reset_turn_tokens()
  ├─ _ensure_session(..., tenant_metadata)
  ├─ set_session_tenant_context(db, TenantContext)
  │
  ├─ [HTTP] RuntimeGateway.try_tier0_chat(Tier0ChatContext)
  │     ├─ run_sql_retrieval_tier0（kernel/runtime/tier0_paths.py）
  │     └─ run_database_direct_tier0（注入 data_query_fn + DataQueryRequest factory）
  │     └─ handled → ChatResponse / SSE tier0 事件（不经全量 Supervisor）
  │
  ├─ CognitiveKernel.run(KernelRequest)
  │     ├─ classify_intent / IntentLock
  │     ├─ RuntimeGateway.try_tool_fast_path → KernelResponse（早退）
  │     ├─ V5: L0 → semantic_cache → L1
  │     └─ RuntimeGateway.run → dispatcher → handler（§15/§18）
  │
  ├─ run_outcomes · turn_outcomes · enrich_turn_enterprise_metadata
  ├─ post_turn_enterprise_accounting（async quota 若有 event loop）
  │
  └─ ChatResponse + metadata
```

### 6.2 流式聊天（SSE）

```text
POST /api/v1/chat (stream=true)
  → 预检与会话租户
  → try_tier0_chat → stream_tier0_events（delta 分片 + final_answer）
  → 否则 CognitiveKernel.stream → RuntimeGateway.stream
  → 事件: delta | reasoning_step | dag_* | final_answer | error
  → final_answer → normalizeFinalAnswerEnvelope（前端）→ turn_meta
  → Trace / ConversationState / CognitiveEventBus
```

### 6.3 能力执行（Executive 内子任务）

```text
ExecutionPlan.subtasks[]
  → kernel/runtime/executor.py · capability_registry.resolve_execution_agent
  → [V3] agent_runtime_executor.execute_task → UnifiedEvidence → EvidenceBus
  → record_capability_outcomes → ctx.metadata["capabilities_used"]
```

### 6.4 Data 路径分叉

```text
force_database + data_source_id
  → try_tier0_chat（tier0_data_query）或 gateway/data.py data_query
否则
  → preferred_runtime=data_intelligence 或 Executive 内 data 子任务
DataAgent → DataAgentV2Supervisor（澄清门控可短路 DAG）
```

### 6.5 Supervisor 拒绝早退

`control_plane_denied` | `runtime_policy_denied` | `runtime_governance_denied` → 短路 KernelResponse / SSE error。

### 6.6 Registry 治理拒绝

`registry_dispatch_denied` + `registry_dispatch_gate` metadata。

### 6.7 RuntimeContribution 与 CognitiveStateGraph（能力执行后）

```text
agent_results[]（Executive execute / data_intelligence / Worker Bus）
  → dispatch_pipeline.attach_goal_participation_metadata(ctx=…)
       → evidence_runtime.merge_turn_evidence
       → merge_runtime_contributions → metadata.runtime_contribution_turn
       → apply_runtime_contribution_to_bus(ctx)  # CognitiveStateGraph 链
       → enrich_evidence_with_graph（services/evidence_graph）
       → record_turn_failure_signals → failure_memory
       → enrich_world_projection_for_turn（若 ctx 存在）
  → record_capability_outcomes → CapabilityFeedbackLoop + Capability OS SLA
  → executive 回合末：sync_goal_lifecycle_from_metadata + persist_goal_progress
  → run_outcomes：goal_progress / cognitive_state_graph 进入 KernelResponse.metadata
```

**统一贡献字段**（`RuntimeContribution`）：`evidence[]`、`goal_updates[]`、`memory_updates[]`、`world_updates[]`、`risks[]`、`metrics[]`。Tier-1 经 `agent_runtime_executor` 同时写 `AgentContribution`（Worker 兼容）与 trace 内 `runtime_contribution`。

**图演化顺序**（`CognitiveStateGraph`）：`GoalNode → EvidenceNode → MemoryNode → WorldNode`（`apply_contribution_to_graph`）。

**Redis 持久化**（可选）：`flush_cognitive_state_graph` / `load_cognitive_state_graph`（key `cog_state_graph:{session_id}:{request_id}`）；由 `bus._schedule_graph_redis_flush` 在贡献写入后 best-effort 调度。`hydrate_state_from_store` 可在 resume 时恢复图。

**Data V2 熔断侧链**（与 Executive 无关，Data 专用）：

```text
Supervisor 低置信 + data_agent_v2_fallback_to_v1
  → record_data_v2_circuit_breaker（failure_memory: low_confidence_circuit_breaker）
  → raise LowConfidenceError
  → DataAgent 包装器仅捕获 LowConfidenceError → DataAgentV1.execute
```

### 6.8 Turn bootstrap / enrichment / finalize（横切 SSOT）

```text
Gateway chat.py（复杂路径，Tier0 之前）
  ├─ build_tenant_metadata → kernel_metadata 合并 tenant_id / org_id / workspace_id
  ├─ bootstrap_turn_intent(kernel_request)
  │     ├─ apply_multi_turn_resolution（可与 Kernel 内重复；metadata 去重）
  │     ├─ hydrate_world_model_for_turn（world_turn_begin）
  │     └─ classify_intent → intent_lock 写入 metadata
  ├─ dispatch_query = kernel_request.query（tier0 / trace / advance_turn / user memory SSOT）
  │
CognitiveKernel.run/stream
  ├─ bootstrap_turn_intent（若 Gateway 未写 intent_lock）
  ├─ enrich_turn_before_dispatch（Supervisor.prepare_run 内，可 skip 标志）
  │     ├─ multi_turn · preference · memory fabric · assembled_context
  │     └─ runtime_agent_params_from_context → tenant_id / workspace_id → RAG/Data params
  │
resume_turn（kernel/runtime/resume_turn.py）
  └─ bootstrap_turn_intent + enrich_turn_before_dispatch（与 chat 对齐）

post_turn_enterprise_accounting（finalize_turn.py）
  ├─ billing · quota async · usage_metering · learning_hook
  └─ finalize_world_model_for_turn（world_turn_finalize）
```

契约：`test_turn_bootstrap_contract.py`、`test_turn_enrichment_contract.py`、`test_p2_p3_completion_contract.py`、`test_finalize_turn_contract.py`。

---

## 7. 目录结构与模块地图

```text
opentrace/
├── gateway/api_gateway/
│   ├── main.py · routers/chat.py · tier0_paths.py（re-export）
│   ├── chat_preflight.py · tenant_middleware.py
│   └── routers/enterprise_admin.py · conversations.py（messages + metadata）
├── kernel/
│   ├── cognitive_kernel.py · runtime_gateway.py · fast_tool_path.py
│   ├── runtime/tier0_paths.py          # Tier0 SSOT
│   ├── cognitive_supervisor/
│   ├── runtime/                          # executive · finalize_turn · registry
│   ├── goal/ · governance/ · cognition/
│   ├── agent_runtime/                    # manifest · executor · unified_evidence
│   └── capability_runtime/ · capability_intelligence/
├── control_plane/ · tenant/quota_redis_store.py
├── services/data_intelligence_runtime/ · evidence_graph/ · rag_evidence_intelligence.py
├── agents/ · agents/data_agent_v2/turn_metadata.py
├── memory/fabric/ · world/
├── frontend/src/utils/streamEnvelope.ts
├── legacy/v4/ · tests/ · scripts/ · docs/
```

---

## 8. 前端应用

- 入口：`frontend/src/main.tsx` → `App.tsx`
- API：`frontend/src/api/client.ts`（`streamSseResponse`、`onFinalAnswer(envelope: TurnMetaEnvelope)`）

| 页面 / 组件 | 能力 |
|-------------|------|
| ChatPage | SSE、`ChatInput` 应用 `applyFinalAnswerEnvelope` |
| ChatMessage | `TurnMetaPanel`（control_plane、capabilities、clarification、governance_warnings） |
| DagTimeline / ExecutionGraphPanel | DAG 节点状态、依赖、duration |
| Databases / Documents / Skills / Rules / Memory / Audit | 管理面 |

### 8.1 流式与历史消息契约

| 环节 | 行为 |
|------|------|
| SSE `final_answer` | `normalizeFinalAnswerEnvelope(data)` → store `setLastAssistantTurnMeta` |
| `GET /conversations/{id}/messages` | `MessageOut.metadata` 自 `execution_graph.governance` 等拼装 |
| `asDoneMessage` | assistant 消息 `turn_meta` 回填（`store/chat.ts`） |

契约：`frontend/src/utils/__tests__/streamEnvelope.contract.test.ts`。

---

## 9. API 网关与路由清单

- 应用：`gateway/api_gateway/main.py`
- 启动：`register_builtin_agents()`、`ensure_runtime_schema()`、memory 订阅

### 9.1 Router（前缀 `/api/v1`）

`health`、`prometheus`、`auth`、`chat`、`conversations`、`cognitive`、`documents`、`memories`、`tasks`、`audit`、`connectors`、`skills`、`data`、`databases`、`feedback`、`sandbox`、`admin`、**`enterprise_admin`**、`rules`、`metrics` 等。

### 9.2 Enterprise Admin

租户列表、control-plane health、capability marketplace、compliance audit、usage、`POST .../quota`。

### 9.3 健康检查

`GET /health`、`GET /health/deps`、**`GET /health/cognitive-os`**（flags、Tier-1 runtimes、orchestrator 标签）。

---

## 10. 聊天主链路（同步 / SSE / 企业预检 / Tier0）

### 10.1 企业预检（`chat_preflight.py`）

PII 检测 → `EnterpriseControlPlane.evaluate_turn` → `policy_denied` 抛 `AppException`。

### 10.2 Tier0（`kernel/runtime/tier0_paths.py` + `RuntimeGateway.try_tier0_chat`）

| 路由 | 触发 | 产出 |
|------|------|------|
| `sql_retrieval` | `is_sql_retrieval_intent` + TraceLog 历史 SQL | `execution_graph` + `build_fast_path_governance_envelope` |
| `tier0_data_query` | `force_database` + `data_source_id` | `data_query` 注入；`agent_type` 来自 manifest `data_query` |

合规：`_record_tier0_compliance_audit`（best-effort）。

### 10.3 多租户与 Token 计量

见 §27、`turn_metering.py`：`reset_turn_tokens` → ModelGateway 累加 → `merge_turn_tokens_into_metadata`。

### 10.4 会话上下文组装（Gateway → Kernel）

```text
ConversationStateManager.get_or_create(session_id)
  → RuntimeContext(conversation_history, conversation_state, user_preferences, …)
  → runtime_ctx.to_metadata_dict()
  → kernel_metadata 合并 tenant_md：tenant_id / org_id / workspace_id / data_residency
  → kernel_metadata.setdefault("tenant_id"|"workspace_id", "default")
  → kernel_metadata["history"] = conversation_history（chat.py 显式双写）
  → KernelRequest(history=conversation_history, metadata=kernel_metadata)
  → bootstrap_turn_intent(kernel_request) → runtime_ctx.metadata 回写
  → dispatch_query = kernel_request.query（后续 tier0、trace、记忆写入统一用此 query）
```

`CognitiveKernel` 多轮解析使用 **`request.history or request.metadata.get("history")`**（`run` 与 `stream` 一致）。`turn_bootstrap` 与 `turn_enrichment` 分工：bootstrap 负责 intent_lock + world hydrate；enrichment 负责偏好/记忆/Context Fabric 组装（Supervisor 路径）。

### 10.5 回合横切钩子（intent 前后）

| 阶段 | 模块 | 产出 metadata |
|------|------|----------------|
| Gateway 偏好 | `preference_injection.apply_preference_injection_for_turn` | `user_preference_context_block` |
| intent 前 | `resolve_multi_turn_query` | `multi_turn_resolution` |
| intent 后 | `hydrate_world_model_for_turn` | `world_hydrate`、`world_cross_process` |
| 回合末 | `finalize_world_model_for_turn` | `world_grounding`、`shared_world_state` |

---

## 11. 认知内核与认知控制

### 11.1 CognitiveKernel（`kernel/cognitive_kernel.py`）

唯一 `run/stream` 入口；复杂路径 **仅** `get_runtime_gateway().run/stream`。V4 仅在 `kernel_orchestrator_v4_enabled=true` 时经 shim 进入 `legacy/v4`。

流式常量：`_STREAM_CHUNK_SIZE`、`_STREAM_DELAY`；身份缓存与 `WorkingMemory` Redis 恢复；多问题检测 `kernel/cognition/multi_question.py`。

### 11.2 Intent Lock（`kernel/cognitive_controls.py`）

`classify_intent()` → `IntentLock`（`task_type`、`complexity_level`、`relevance_threshold`）、`CognitiveBudget`、`apply_intent_lock_to_context()`。`direct_answer_for_intent` 可零 Executive 直答。L0/L1 复杂度可触发 Supervisor **slim** 路径（`runtime_task_from_request_light`）。

### 11.3 横切模块

| 模块 | 职责 |
|------|------|
| `clarification_gate.py` | 通用 + `DataClarificationGate`（Data V2 澄清） |
| `context_fabric.py` / `context_fabric_graph.py` / `context_fabric_session.py` | 会话级上下文图演化 |
| `memory_injection.py` | Fabric 优先注入（受 `kernel_memory_fabric_primary_only`） |
| `semantic_cache.py` | L0.5 向量缓存 |
| `refine_planner.py` | 计划修正 |
| `multi_turn_resolution.py` | **主路径**多轮门面：DST + ReferenceResolver → `resolved_query` |
| `dialogue_state_tracker.py` | 多轮 domain/指代状态（被 multi_turn_resolution 调用） |
| `reference_resolver.py` | 纠正/追问 query 展开 |
| `preference_injection.py` | 回合前偏好块注入 metadata |
| `turn_bootstrap.py` | Gateway + Kernel + resume：multi_turn + world hydrate + intent_lock |
| `turn_enrichment.py` | Supervisor/Kernel：`enrich_turn_before_dispatch`、agent params 租户字段 |
| `world_turn_begin.py` / `world_turn_finalize.py` | 回合前 hydrate / 回合后 grounding 持久化 |
| `history_retriever.py` | 历史 SQL/对话检索（Tier0 SQL 检索依赖 TraceLog + 本模块逻辑） |
| `self_model.py` | 系统身份与能力自述（CapabilityAdapter 格式化） |

---

## 12. V5 路由层与快路径（经 RuntimeGateway）

| 层 | 模块 | 入口 |
|----|------|------|
| L0 | `query_router_v2.py` | Kernel 内 |
| L0.5 | `semantic_cache.py` | Kernel 内 |
| L1 | `tiny_router.py` | Kernel 内 |
| Tool | `fast_tool_path.py` | **`RuntimeGateway.try_tool_fast_path` / `stream_tool_fast_path`** |

`should_use_tool_fast_path` 支持 `IntentLock` 对象或 `dict`（metadata）。

---

## 13. V4 编排器（遗留、默认禁用）

`legacy/v4/orchestrator.py`；`kernel_orchestrator_v4_enabled=false`。

---

## 14. RuntimeGateway、Supervisor 与 TurnDispatcher

### 14.1 RuntimeGateway（`kernel/runtime_gateway.py`）

| 方法 | 职责 |
|------|------|
| `run` / `stream` | prepare_run → dispatcher |
| `try_tier0_chat` | SQL 检索 + force DB（`Tier0ChatContext`） |
| `try_tool_fast_path` / `stream_tool_fast_path` | ToolAgent + governance envelope |

### 14.2 CognitiveSupervisor.prepare_run（`cognitive_supervisor/supervisor.py`）

```text
evaluate_request_control_plane（最早；拒绝 → control_plane_denied）
  → runtime_task_from_request[_light]（L0/L1 slim）
  → RuntimePolicyEngine.evaluate_planning_phase（拒绝 → runtime_policy_denied）
  → RuntimeGovernor.evaluate_task（拒绝 → runtime_governance_denied）
  → build_runtime_context_from_kernel_request
  → _hydrate_world_state_if_enabled
  → bind_goal_graph_to_context · goal_projection
  → _apply_runtime_policy · _inject_strategy_projection · _seed_context_fabric
  → enrich_world_projection_for_turn（`world_decision_runtime.py`：current / projected / 库存·预算 % counterfactual）
  → apply_dispatch_enrichment（AdaptiveRisk、grounding、fabric evolve phase=dispatch）
  → route_hint（默认 cognitive_executive）
```

`control_plane_gate.py`：与 `EnterpriseControlPlane` 对齐；拒绝写入 `prepared.governance_meta`。

### 14.3 dispatch_enrichment（`dispatch_enrichment.py`）

`project_goal_graph_to_execution_hints` → `AdaptiveRiskEngine` → `runtime_grounding` → cognitive_state bind/hydrate → `context_fabric.evolve_runtime(phase=dispatch)`。

### 14.4 RuntimeTurnDispatcher（`runtime_turn_dispatcher.py`）

- `run_turn`：`resolve_runtime_name` → `dispatch_runtime` → `executive_result_to_kernel_response`
- `stream_turn`：`reasoning_step(ROUTE)` → `event_cb` 转发 Executive/DAG 步骤 → 分片 `delta` → `final_answer`（`build_stream_final_metadata`）
- 治理拒绝 → `{type: error}` 或 `KernelResponse` route=`runtime_governance_denied`

### 14.5 run_outcomes（`run_outcomes.py`）

`build_runtime_artifact`、`evaluate_executive_turn_governance`、`executive_result_to_kernel_response`（入口前 `sync_goal_lifecycle_from_metadata`）、`replay_contract`、goal_graph 合并。

**从 ctx 透传到 KernelResponse.metadata**（2026-06-11 起）：`goal_progress`、`runtime_contribution_turn`、`cognitive_state_graph`、`failure_memory`、`evidence_runtime`、`world_projection`、更新后的 `goal_graph`（含 lifecycle metadata）。契约：`tests/test_run_outcomes_contract.py`。)

### 14.6 enterprise_outcomes（`enterprise_outcomes.py`）

`enrich_turn_enterprise_metadata`：`evaluate_turn`、异步 `record_compliance_event`、配额消耗、`usage_metering`、`build_shared_world_state`、可选 `save_session_world_state`、`enterprise_telemetry` + Prometheus。

### 14.7 finalize_turn（`kernel/runtime/finalize_turn.py`）

`post_turn_enterprise_accounting`：`usage_metering`、quota、`learning_hook`、**`finalize_semantic_and_evolution`**（`record_kernel_turn_health` + `evolution_hook` 去重）、**`finalize_world_model_for_turn`**（含 `CrossProcessWorldFacade.fetch_merged`）。

（原摘要）`post_turn_enterprise_accounting`：`usage_metering` + **有 event loop 时 `consume_turn_quota_async`**，否则同步 `consume_turn_quota`。

---

## 15. Cognitive Runtime V2（Executive 管线）

入口：`kernel/runtime/cognitive_executive.py` — `CognitiveExecutive.execute()`。

```text
init / understand（UnderstandingEngine + CapabilityAdapter 能力目录）
  → plan（PlannerFacade · PolicyRuntime.on_planning · phase governance）
  → build capability graph · validate_planned_capabilities（dispatch_pipeline）
  → execute（ExecutionRuntime / kernel/runtime/executor.py · DAG 节点 · event_cb 流式推理步）
       → resolve_execution_agent · record_capability_outcomes · capabilities_used
  → evidence bus（publish · resolve · ranking · lifecycle）
  → fusion（SequenceFusion / FusionEngine）
  → critic（Policy post_fusion）
  → memory write（Policy on_memory_write）
  → GoalRuntimeHooks · optional world_state persist
  → sync_goal_lifecycle_from_metadata + persist_goal_progress（goal_progress.py）
  → [9.5] capability feedback · evolution_engine（`capability_evolution` metadata）
  → [9.7] `cognitive_iteration`（Reflection→Replan）
  → `strategy_pattern.record_turn_pattern`
→ CognitiveExecutiveResult（answer · metadata · critic_result）
```

**Phase 严格模式**：`kernel_runtime_phase_transition_strict`；违规写入 `phase_transition_violations`。

子模块索引：`runtime/cognitive/`（`cognitive_planner_v2`、`strategy_builder`、`execution_projection`）、`understanding_engine.py`、`rewrite_engine.py`、`artifact_composer.py`、`evidence_bus.py`、`fusion.py`、`critic.py`。

---

## 16. Goal 生命周期、多目标与 turn_outcomes

### 16.1 状态机（`goal/state_machine.py`）

`CREATED → PROJECTED → ACTIVE → EXECUTING → EVIDENCE_COLLECTED → FUSED → COMPLETED | FAILED → ARCHIVED`（含 `BLOCKED`、`REPLANNING`）。

### 16.2 turn_outcomes（`goal/turn_outcomes.py`）

`apply_turn_goal_and_memory_outcomes`：`finalize_turn_goal_lifecycle` → `evolve_goals_after_execution` → `bind_goal_turn_to_memory_fabric`；data 路由合并 `enrich_data_turn_outcomes`。

### 16.3 Goal Portfolio（`goal_portfolio.py`）

Program → Task 层级；`enterprise_outcomes` 写入 `goal_portfolio` metadata。

### 16.4 多目标调度（`multi_goal_scheduler.py` / `multi_goal_resources.py`）

Portfolio 级资源与并行子目标（契约：`test_multi_goal_runtime_contract.py`）。

---

## 17. 认知规划门面与多问题运行时

`planner_facade.py`、`multi_question_runtime.py`；registry `multi_goal` 可回退 Executive。

---

## 18. Runtime Registry、Tier-1 与 Data Intelligence

| runtime | handler |
|---------|---------|
| `cognitive_executive` | `CognitiveExecutive().execute` |
| `data_intelligence` | `run_data_intelligence_turn` |
| `multi_goal` | `run_multi_question` |

`run_data_intelligence_turn`：TaskMessage → DataAgent → `[V3] agent_runtime_executor` → `attach_data_intelligence_to_metadata`。

---

## 19. Agent 集群总览与 Worker

### 19.1 Manifest 与注册（`agent_topology_manifest.yaml` + `agents/bootstrap.py`）

Manifest **version 3.1.0**；`sync_manifest_to_runtime()` 后按 `bootstrap_agent_types` 实例化；**worker ⊆ bootstrap**（`rules` 仅 API 进程，不进 bus worker）：

| agent_type | 类 | capability_type | bootstrap | worker | bus | 备注 |
|------------|-----|-----------------|-----------|--------|-----|------|
| `data` | `DataAgent` | `data_query` | ✓ | ✓ | ✓ | V2 supervisor 内嵌 |
| `rag` | `RagAgent` | `document_retrieval` | ✓ | ✓ | ✓ | |
| `web` | `WebAgent` | `web_search` | ✗ | ✗ | ✗ | legacy；`superseded_by: web_intelligence` |
| `web_intelligence` | `WebIntelligenceAgent` | `web_search` | ✓ | ✓ | ✓ | **生产单轨** |
| `tool` | `ToolAgent` | `tool` | ✓ | ✓ | ✓ | Tier0 / fast path |
| `vision` | `VisionAgent` | `vision_analysis` | ✓ | ✓ | ✓ | `image_urls` / `image_data` |
| `skills` | `SkillsAgent` | `skill_execution` | ✓ | ✓ | ✓ | 市场技能，非 V2 skills_engine |
| `rules` | `RuleEngineAgent` | `policy_rules` | ✓ | ✓ | ✗ | API+Worker 注册；**不**订阅 Bus（`bus_eligible=false`） |

别名解析：`resolve_capability_alias("web"|"web.search")` → `web_intelligence`（当 preferred）；`vision_analysis` / `skill_execution` / `policy_rules` 见 `capability_registry` fallbacks（契约：`test_capability_web_manifest_contract.py`、`test_agent_runtime_v3_contract.py`）。

### 19.2 Worker（`agents/worker.py`）

`register_builtin_agents(force=True)` 实例化与 manifest `bootstrap_agent_types` 一致；**消费队列**仅 `_bus_consumer_agent_types()` = 已注册 agent ∩ `manifest.bus_eligible_agent_types()`（故 `rules` 不跑 stream 消费者）。Redis Agent Bus：DLQ、xclaim reclaim、heartbeat。`kernel_agent_runtime_v3_enabled` 时走 `agent_runtime_executor`。

### 19.3 基类（`agents/base.py`）

`TaskMessage`（`task_id`、`agent_type`、`query`、`params`、`session_id`、`user_id`）  
`AgentResult`（`status`、`content`、`confidence`、`metadata`、`evidence`、`evidence_objects`、`agent_trace`）  
`execute_as_capability()`：默认将 `execute()` 包装为 `Evidence` 列表。

### 19.4 CognitiveAgent 契约（`agents/cognitive_agent.py`）

```text
execute()
  → perception → reasoning → planning → execute_core（子类）
  → reflection → learning
  → agent_trace 六阶段 · metadata.cognitive_agent=true
```

实现类：**`WebIntelligenceAgent`**（`agents/web_intelligence_agent.py`）。

### 19.5 Registry（`agents/registry.py`）

扩展/插件 Agent 名解析（与 bootstrap 内置集合并使用）。

---

## 20. 各 Agent 内部管线（逐 Agent）

### 20.1 RagAgent（`agents/rag_agent.py`）

```text
execute(task)
  → _normalize_query / _rewrite_query（中文问句清洗）
  → params：tenant_id / workspace_id（runtime_agent_params_from_context，Gateway metadata 必带）
  → 并行：DocumentPlugin 向量检索（documents 表等值 tenant/workspace + owner_id）· LLMwiki · UserMemory
  → Rerank（get_reranker）· DocumentEvidenceGate（min_score、anchor、answerable）
  → 不足则 web fallback（可选）
  → _make_evidence · ResultRef（doc_chunk、citation）
  → enrich_evidence_intelligence（services/rag_evidence_intelligence.py，source_kind=document）
       → rank_evidence · detect_contradictions · evidence_graph · synthesis_preview
       → run_lightweight_claim_check（query–chunk 锚定，rag_claim_anchor_enabled）
  → AgentResult(metadata.rag_evidence_intelligence=…，含 claim_verification)
```

**不生成最终自然语言答案**（由 Fusion/Kernel 生成）；输出 chunks、citations、quality 块。

### 20.2 WebAgent（`agents/web_agent.py`）

经 `ToolRouter` / `web_search` 工具；较薄封装；当 `web_intelligence` 未优先时由 `resolve_execution_agent` 解析到 `web`。

### 20.3 WebIntelligenceAgent（`agents/web_intelligence_agent.py`）

```text
CognitiveAgent.execute
  → execute_core:
       ToolRouter.execute_by_name("web_search", query)
       → 解析 JSON/items
       → enrich_evidence_intelligence(items, query, source_kind=web)
            → 与 RAG 同构：evidence_graph · chunk_graph · fact_verification · claim_verification
       → content=Top5 标题/摘要
       → [P1] `evaluate_coverage` + 补搜（`kernel_web_coverage_evaluator_enabled`）
       → metadata: `web_coverage` · evidence_graph · rag_evidence_intelligence · web_intelligence=true
```

### 20.4 ToolAgent（`agents/tool_agent.py`）

规范化工具名与参数 → `tools/registry` / `execution/tool_router`；天气、时间等由 Kernel 层 `should_use_tool_fast_path` + **RuntimeGateway** 拦截执行。

### 20.5 DataAgent（`agents/data_agent.py`）

```text
execute(task)
  → data_agent_v2_enabled=false → DataAgentV1（kernel/data_cognition 管线）
  → data_agent_v2_enabled=true → DataAgentV2Supervisor.execute
  → except LowConfidenceError + data_agent_v2_fallback_to_v1 → DataAgentV1
  → except other + fallback off → AgentResult error（非全异常回退 V1）
```

熔断前 Supervisor 已写 `failure_memory`（`kernel/agent_runtime/data_v2_failure_memory.py`）。

**DataAgentV1 管线**：

```text
SemanticParser → QueryPlanner → SQLBuilder → SQLValidator → SQLRanker/Reflector
  → QueryExecutor（DBRouter）
  → build_explanation · attach_data_intelligence_to_metadata
  → AgentResult + evidence(sql)
```

### 20.6 VisionAgent（`agents/vision_agent.py`）

```text
execute(task)
  → params: image_urls | image_data
  → 无图且 kernel_vision_require_images=true（默认）
       → status=error · error=vision_input_required:image_urls_or_image_data
  → 无图且 lenient → success + metadata.degraded
  → ModelGateway LLMRole.VISION 多模态 messages
  → _make_evidence_object · AgentResult
  → [V3] agent_runtime_executor → RuntimeContribution.evidence
```

### 20.7 SkillsAgent（`agents/skills_agent.py`）

```text
execute(task)
  → 解析 skill_name / skill_id（params 或会话已安装技能）
  → skills 运行时 manifest（与 data_agent_v2/skills_engine 区分：本 Agent 为 Tier-1 市场技能入口）
  → 执行技能定义步骤 → AgentResult
```

### 20.8 RuleEngineAgent（`agents/rule_engine_agent.py`）

```text
execute(task)
  → _RULE_PATTERNS 关键词匹配（usage_policy / data_privacy / access_control / …）
  → params.rule_category 直指定类别
  → 无匹配 → 低置信空内容；有匹配 → LLMRole.CHEAP_CRITIC 规则解读（可选）
  → AgentResult(metadata.matched_rules=…)
```

**说明**：`rules` **bootstrap=true、worker=true、bus_eligible=false** — Worker 进程可注册实例供 in-process 调用，但 **不** 订阅 Redis Bus 任务流。

---

## 21. DataAgent V2 子 Agent 与 DAG

### 21.1 Supervisor 走向（`supervisor.py`）

```text
_init_context → _load_datasource_metadata
  → [data_agent_v2_clarification_enabled] _check_clarification
       → DataClarificationGate.detect / generate_question
       → _build_clarification_result（turn_outcome=clarification，不跑 SQL）
  → KnowledgeRetriever（可选）→ 快路径 pattern/SQL
  → build_cognitive_dag → DagScheduler 并行 L0…L4
  → SQL 执行
  → verification_report.status==fail → turn_metadata error_diagnosis + blocked
  → reflection / error_classifier 重试
  → Phase4 insight/stat/viz（开关）→ metadata_extra.advanced_analytics
  → _build_final_result
  → [学习] data_agent_v2_auto_learning_enabled → _run_learning_pipeline
       → FeedbackCollector / PatternExtractor / KnowledgeUpdater → data_learning_signals
  → [成功] record_agent_learning_signal → metadata.runtime_learning
  → [熔断] confidence < threshold → failure_memory → LowConfidenceError
       → build_data_success_evidence_objects（V3 strict UnifiedEvidence）
       → attach_data_intelligence_to_metadata
```

DAG 构建后：`validate_dag_spec` + **`validate_dag_against_manifest`**（tier2 agent_type 与 manifest、`data_semantic` 依赖）。契约：`test_data_agent_v2_dag_manifest_contract.py`。

### 21.2 turn_metadata（`turn_metadata.py`）

| 函数 | 用途 |
|------|------|
| `clarification_turn_metadata` | `needs_clarification`、`pipeline_stage=clarification_gate` |
| `verification_turn_metadata` | `verification_status`、`turn_outcome=blocked\|verified` |
| `build_error_diagnosis_metadata` | ErrorClassifier + recovery_suggestions |
| `build_data_success_evidence_objects` | `Evidence` 列表 → V3 executor |

### 21.3 Tier-2 节点（manifest + `tier2_registry`）

`data_intent`、`data_entity`、`data_business_semantic`（`business_semantic_agent.py`）、`data_metric`、`data_time`、`data_join`、`data_semantic`、`data_planner`、`data_compiler`、`data_verification`、`data_knowledge` 等。

### 21.4 DAG 拓扑（`dag_builder.py`）

```text
L0 并行：Intent · Entity · Metric · Time · Join
    ↓
L1：Semantic
    ↓
L2：Planner → L3 SQLCompiler → L4 Verification
    ↓
SQL 执行 → 反思/重试（error_classifier + reflection_agent）
    ↓
Insight / Statistical / Visualization（开关）
    ↓
_build_final_result → evidence_objects + attach_data_intelligence_to_metadata
```

执行引擎：内核 `DagScheduler` / `execution/dag_engine` + `data_agent_v2_dag_parallel_enabled`。`validate_dag_spec` 校验依赖闭包。

### 21.5 子 Agent 内部要点（逐节点）

| Agent | 输入 | 输出写入 `CognitiveContext` |
|-------|------|-----------------------------|
| IntentAgent | query、schema 摘要 | `intent`（intent_type、metrics、filters） |
| EntityAgent | query、表元数据 | `entities`、`schema_links` |
| MetricAgent | intent、语义指标库 | `metrics` / `metric_mappings` |
| TimeReasoningAgent | query、默认时区 | `time_range` |
| JoinAgent | 实体、FK 图 | `join_paths` / `join_hints` |
| SemanticAgent | L0 合并结果 | 语义计划片段 |
| PlannerAgent | semantic + knowledge | `logical_plan` |
| SQLCompilerAgent | logical_plan | `compiled_sql` |
| VerificationAgent | SQL、方言规则 | `verification_report` |
| KnowledgeRetrieverAgent | query | `knowledge_hits`、`pattern_hit` |

各 `*_agent.py` 通过 `tier2_registry.get_agent(node_key)` 被 DAG 调用；失败经 `error_classifier` 决定是否重试 DAG 层。

契约：`test_data_agent_v2_turn_outcomes_contract.py`、`test_data_agent_v2_clarification_contract.py`、`test_data_agent_v2_dag_builder_contract.py`。

---

## 22. 数据源、语义层与 Text2SQL

`gateway/.../databases.py`、`data.py`；`kernel/data_cognition/*`；`execution/data/db_router.py`。

---

## 23. RAG、证据图、Claim Graph 与智能层

| 模块 | 职责 |
|------|------|
| `services/evidence_graph/engine.py` | `rank_evidence`、`detect_contradictions`、`build_evidence_graph_from_items`、`synthesize_evidence_summary` |
| `services/rag_evidence_intelligence.py` | `enrich_rag_evidence`（rank/graph/verification）；**`enrich_evidence_intelligence`**（+ `source_kind` + claim anchor） |
| `run_lightweight_claim_check` | 无 LLM：query–chunk `relevance_score`（`kernel/cognitive_controls`）；`rag_claim_anchor_enabled`（settings，默认 true） |
| `services/evidence_graph/claim_graph.py` | `run_claim_pipeline`（`kernel_claim_graph_enabled`） |
| `services/rag_retrieval_clusters.py` | `cluster_evidence_chunks` |
| `agents/rag_agent.py` | 检索管线末调用 `enrich_evidence_intelligence(..., source_kind=document)` |
| `agents/web_intelligence_agent.py` | 同上 `source_kind=web`；metadata 键与 RAG 对齐 |

**输出 metadata**：`rag_evidence_intelligence`（含 `chunk_graph`、`contradictions`、`evidence_graph`、`fact_verification`、`claim_verification`）。

契约：`tests/test_rag_evidence_intelligence_contract.py`、`tests/test_rag_agent_contract.py`。

---

## 24. 记忆系统与 Memory Fabric

六层 + `memory/fabric/`（retrieval、graph、redis、tms_bridge、compression）。`kernel_memory_fabric_primary_only`。

---

## 25. Capability OS、Control Plane 与执行路由

`CapabilityRegistry.resolve_execution_agent`；`dispatch_pipeline`；`EnterpriseControlPlane.evaluate_turn` / `evaluate_turn_async`。

`CapabilityAdapter.find_best_capability`：`web` → manifest `web_search`（`test_capability_web_manifest_contract.py`）。

---

## 26. World Model、Redis 与 Shared World State

`runtime_grounding`；`world_state_redis`；`world_projection`（V3）。

---

## 27. 企业多租户、配额、计费与审计

| 模块 | 职责 |
|------|------|
| `tenant/quota_manager.py` | 日 turn/cost；`consume_async` + Redis authoritative |
| `tenant/quota_redis_store.py` | **`reserve_turn_quota` Lua**；`opentrace:quota:turns|cost|limits:{key}:{YYYYMMDD}` |
| `tenant/usage_redis_store.py` | 日 token/cost 聚合（`enterprise_usage_redis_enabled`） |
| `control_plane/control_plane.py` | `consume_turn_quota_async` |
| `kernel/runtime/finalize_turn.py` | 回合结束扣费（async 优先） |
| `compliance_audit_store.py` | Tier0/tool tier0 审计 |
| `tenant/billing_runtime.py` | `resolve_turn_cost`、`apply_billing_to_metadata`、`record_turn_billing` |
| `tenant/billing_store.py` | `billing_ledger` / `billing_invoices` 异步持久化 |
| `tenant/tenant_rls.py` | `set_session_tenant`；`enterprise_tenant_rls_enabled` |
| `BillingManager.persist_snapshot_as_invoice` | 内存 snapshot → 发票草稿行 |

**staging profile**（`settings._apply_staging_profile`）：`kernel_agent_runtime_v3_strict`、`kernel_unified_evidence_strict`、memory/world persist、policy fail-closed 等（见 `docs/ENV_PROFILES.md`）。

契约：`test_quota_redis_atomic_contract.py`、`test_enterprise_control_plane_contract.py`。

---

## 28. Policy Runtime 与变异点治理

`policy_runtime.py`；`GovernanceCenter`；`test_policy_runtime_contract.py`。

---

## 29. 工具、技能、插件与连接器

`execution/tool_router`；`plugins/*`；`skills/`；`connectors/`。

---

## 30. 规则引擎与灰度

`rule_engine_agent.py`；`force_mode` 跳过 V5 / 锁定 runtime。

---

## 31. 执行平面、DAG 与 Agent Bus

`kernel/runtime/executor.py`；`execution/dag_engine/`；`infra/message_bus/agent_bus.py`。

---

## 32. 模型网关、Token 计量与 Embedding / Rerank

`model/model_gateway/gateway.py` + `turn_metering`；embedding/rerank 供 RAG。

---

## 33. 治理体系（canonical kernel.governance）

`evidence_governor`、`risk_governor`、`memory_governor`、`semantic_metrics_pipeline`、`semantic_helpers`（`record_executive_turn_health` / `record_kernel_turn_health`）、`self_optimizing_runtime`（metadata hints）。顶层 `governance/` 为兼容 re-export。

---

## 34. 安全、审计、沙箱与可解释性

JWT、zero_trust、tool permission token、PII 预检、`sandbox` 路由、SQL 只读。

---

## 35. 基础设施、配置、Flag 治理与环境 Profile

`settings.py`、`flag_governance.py`、`docs/ENV_PROFILES.md`、`docs/CONFIG_TRUTH.md`。

Redis DB 索引：session/cache/memory/queue/rate-limit/pubsub。

---

## 36. 数据库模型与迁移

`infra/storage/models.py`：`User`、`ChatSession`（`tenant_id` / `org_id` / `workspace_id`）、`TraceLog`、`Message`、`DataSource`、`Document`（**`tenant_id` + `workspace_id`** 列，索引 `ix_documents_tenant_id`、`ix_documents_tenant_workspace`）、`DocumentChunk`…

| | Alembic head（当前） | **`20260613_documents_tenant`** |
| `20260611_billing_invoice` | 计费账本（经 merge head） |
| `20260610_merge_cognitive_enterprise_heads` | 认知 + 企业分支合并 |

运行时兜底：`ensure_runtime_schema` → `_ensure_documents_tenant_columns`（dev 未跑迁移时仍可查）。

上传：`gateway/.../documents.py` `upload_document` 从 `build_tenant_metadata` 写入 `Document.tenant_id` / `workspace_id`。

---

## 37. 部署、脚本与本地开发

```bash
cp .env.example .env && bash start-dev.sh
curl http://127.0.0.1:14100/api/v1/health/cognitive-os
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
```

`scripts/work/*` 分步启停；`scripts/verify_e2e.sh`；`scripts/weekly_release_checklist.sh`；CI：`ci-fast.yml`、`vnext-contract.yml`、`nightly-multi-turn.yml`。

---

## 38. 测试体系与发布门禁

```bash
pip install -e ".[dev]"
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
bash scripts/check_import_boundaries.sh
lint-imports --config importlinter.ini
PYTHONPATH=. pytest tests/ -q
```

代表性契约（非穷尽）：

- vNext：`test_vnext_architecture_contract`、`test_runtime_gateway_tier0_contract`、`test_tool_fast_path_contract`
- Enterprise：`test_stream_enterprise_metadata_contract`、`test_chat_preflight_contract`、`test_quota_redis_atomic_contract`
- Data：`test_data_agent_v2_turn_outcomes_contract`、`test_data_intelligence_runtime_v3_contract`
- Agent V3：`test_agent_runtime_v3_strict_contract`
- 前端：`streamEnvelope.contract.test.ts`、`DagTimeline*.contract.test.tsx`

全量：**1246** collected。`run_vnext_final_tests.sh` 含 `test_p0_*`、`test_p1_*`、`test_p2_completion_contract`。

Runtime-First / 企业扩展：`test_runtime_contribution_contract`、`test_evidence_runtime_contract`、`test_failure_memory_contribution_contract`、`test_data_v2_circuit_breaker_failure_memory_contract`、`test_cognitive_state_graph_prod_contract`、`test_data_agent_v2_dag_manifest_contract`、`test_run_outcomes_contract`、`test_billing_runtime_contract`、`test_tenant_rls_contract`、`test_alembic_single_head_contract`。

横切 / P2–P3：`test_turn_bootstrap_contract`、`test_turn_enrichment_contract`、`test_p2_p3_completion_contract`、`test_multi_turn_scenarios_contract`、`test_multi_turn_scenarios_fixture`、`test_v6_v4_import_gate_contract`、`test_chat_session_tenant_contract`（kernel_metadata 租户合并）。

CI：`.github/workflows/vnext-contract.yml`；**Nightly** `.github/workflows/nightly-multi-turn.yml`（multi_turn + 可选 RAG E2E）。

---

## 39. 架构治理文档矩阵

`ARCHITECTURE_REQUIREMENTS_MATRIX.md`、`ENTERPRISE_COGNITIVE_OS_GAP_ANALYSIS.md`、`CAPABILITY_MATURITY.md`、`FEATURE_FLAG_REGISTRY.md`、`RELEASE_GATE.md`、`adr/*`、`runbooks/*`、`catalog/*`、**本文**。

---

## 40. 开发规范与代码阅读顺序

1. 聊天必须 **CognitiveKernel**；复杂路径 **RuntimeGateway**。  
2. Tier0 / Tool 快路径逻辑在 **kernel**，Gateway 只注入 IO（如 `DataQueryRequest`）。  
3. Governor **仅** `kernel/governance`。  
4. 新 Agent：更新 **manifest** + bootstrap + 契约测试。  
5. 回合结束：**turn_outcomes** + **finalize_turn** + **enterprise_outcomes**。  
6. staging 打开 V3 strict 前确保 DataAgent 成功路径有 **evidence_objects**。  
7. 前端 SSE 变更必须更新 **streamEnvelope** 与契约测试。

### 推荐阅读

1. `chat_preflight.py` · `chat.py` · `runtime_gateway.py` · `tier0_paths.py`  
2. `cognitive_supervisor/` · `runtime_turn_dispatcher.py` · `cognitive_executive.py`  
3. `data_agent_v2/supervisor.py` · `turn_metadata.py` · `services/data_intelligence_runtime/`  
4. `agent_topology_manifest.yaml` · `agent_runtime/executor.py`  
5. `quota_redis_store.py` · `finalize_turn.py`  
6. `frontend/streamEnvelope.ts` · `store/chat.ts`  

---

## 41. 已知风险、架构债与演进

| 项 | 说明 |
|----|------|
| 历史 Trace metadata | 部分 turn_meta 依赖 `execution_graph.governance` 回填，非全字段持久化 |
| 分布式 World Model | 多副本一致性 ⚠️ |
| RLS POLICY | `20260606_enterprise_tenants_rls` + runbook；生产前 staging Postgres 必测 |
| 计费 | `billing_runtime` + `billing_ledger`；发票 draft，非税务级 |
| sync finalize 扣费 | 无 event loop 时仍同步 consume；worker 进程需注意 |
| slim prepare_run | L0/L1 与完整 Goal 图行为差异 |

**目标态**：Enterprise Cognitive OS — Control Plane + Capability OS + Goal Portfolio + Agent V3 证据链 + 前端治理可视化。

---

## 42. SSE 与流式事件契约

| type | 含义 |
|------|------|
| `delta` | 增量文本 |
| `reasoning_step` | stage、node_id、status |
| `dag_node_start` / `dag_node_complete` | Data / Executive DAG |
| `agent_start` / `agent_complete` | 能力执行 |
| `final_answer` | content、execution_graph、metadata、citations、annotations |
| `error` | 治理/运行时/预检 |

后端：`build_stream_final_metadata` + `enrich_turn_enterprise_metadata`（`control_plane`、`capabilities_used`、`prompt_tokens`、`enterprise_telemetry`）。

前端：`normalizeFinalAnswerEnvelope` → `TurnMetaEnvelope`（含 `governance_warnings` 自 `runtime_degraded`）。

---

## 43. Kernel / Runtime / Goal / Enterprise 模块索引

### kernel/runtime/

`cognitive_executive`、`runtime_turn_dispatcher`、`registry`、`executor`、`finalize_turn`（含 world finalize + learning_hook）、`resume_turn`、`tier0_paths`、`multi_question_runtime`、`evidence/`、`replay/`。

### kernel/（横切）

`turn_bootstrap.py`、`turn_enrichment.py`、`clarification_enrichment.py`、`multi_turn_resolution.py`、`world_turn_begin.py`、`world_turn_finalize.py`。

### kernel/agent_runtime/

`manifest.py`、`executor.py`、`contribution.py`、`unified_evidence.py`、`tier2_registry.py`、`stream_metadata.py`。

### kernel/goal/

`turn_outcomes.py`、`goal_lifecycle.py`、`goal_portfolio.py`、`multi_goal_*`。

### Enterprise

`control_plane/`、`tenant/`、`observability/enterprise_telemetry.py`、`gateway/chat_preflight.py`。

---

## 44. 工程变更日志

### 2026-06-14（service_cursor 全量覆写 · P0–P2 索引）

1. 测试基线 **1246**；Alembic **`20260613_documents_tenant`**。  
2. §50 P0/P1/P2 专章；矩阵 #18–#30。  
3. `finalize_semantic_and_evolution`、`evolution_hook` Executive/finalize 去重。  
4. `world_turn_finalize` → `CrossProcessWorldFacade.fetch_merged`。  
5. `maybe_mount_proposals_on_goal_graph` + `kernel_autonomous_goal_commit_enabled`。  
6. `run_vnext_final_tests.sh` 含 `test_p2_completion_contract`。


### 2026-06-13（Turn SSOT · 文档租户 · Nightly · v6 门禁）

1. **`turn_bootstrap.py`**：Gateway / Kernel / `resume_turn` 共享 intent_lock + world hydrate；**`dispatch_query`** 替代裸 `req.query` 做 tier0/trace/记忆。  
2. **`turn_enrichment.py`**：`enrich_turn_before_dispatch`；`runtime_agent_params_from_context` 含 **tenant_id / workspace_id**。  
3. **Gateway**：`kernel_metadata` 合并 `tenant_md`；RAG 必带租户 params。  
4. **文档**：`documents.tenant_id` + `workspace_id`；`plugins/document_retrieval.py` 等值过滤；Alembic **`20260613_documents_tenant`**。  
5. **`finalize_turn`**：`finalize_world_model_for_turn` 回合末 best-effort。  
6. **CI**：`nightly-multi-turn.yml`；`test_v6_v4_import_gate_contract`；`test_p2_p3_completion_contract`。  
7. **service_cursor** 全量索引更新（§6.8、§10.4、§20.1、§36、§38）。

### 2026-06-11（Runtime-First · 岛 Agent · 计费 · Alembic）

1. **Manifest 3.1.0**：`vision` / `skills` / `rules` Tier-1；`web` bootstrap off；**web_intelligence 单轨**。  
2. **RuntimeContribution** + **CognitiveStateGraph** + **evidence_runtime**；dispatch / Executive / run_outcomes 全链。  
3. **failure_memory** ← `RiskSignal`；**world_decision_runtime**（prepare_run + dispatch）。  
4. **goal_progress** lifecycle + Redis persist 切片。  
5. **billing_runtime** / **billing_store** / `billing_ledger`；Alembic 单 head merge。  
6. **tenant_rls** + `docs/runbooks/tenant-rls-staging.md`。  
7. **service_cursor** 扩写 §6.7、§46–47、逐 Agent 管线。

### 2026-06-10（RuntimeGateway · Data · 前端 · 配额）

1. **Tier0 SSOT** 迁至 `kernel/runtime/tier0_paths.py`；`RuntimeGateway.try_tier0_chat`；chat 单次调用。  
2. **Tool 快路径** 经 `RuntimeGateway.try_tool_fast_path` / `stream_tool_fast_path`。  
3. **Web 能力命名**：manifest + `CapabilityAdapter` + `test_capability_web_manifest_contract`。  
4. **DataAgent V2**：`turn_metadata`（澄清/校验/ErrorClassifier）；成功路径 `build_data_success_evidence_objects`。  
5. **Agent V3 strict**：staging 强制 strict flags；`test_agent_runtime_v3_strict_contract`。  
6. **前端**：`streamEnvelope.ts`、`TurnMetaPanel`、历史 `MessageOut.metadata` + `asDoneMessage.turn_meta`。  
7. **配额 Redis**：`reserve_turn_quota` Lua；`consume_turn_quota_async`；`finalize_turn` async 扣费。  

### 2026-06-08（Enterprise 深化基线）

Control Plane 预检、多租户、Agent V3 manifest、RAG V3、Data Intelligence runtime、合规审计 store、turn_metering、World Redis、Goal Portfolio、vnext-contract CI。

---

## 45. 附录：与 service_claude 的差异

| 主题 | service_claude | service_cursor（本文） |
|------|----------------|---------------------------|
| 快路径 | Kernel 内零散 | **RuntimeGateway 统一 Tier0 + Tool** |
| Data V2 | DAG 表 | **澄清/verification/error_classifier/turn_metadata/evidence_objects** |
| 配额 | 内存 | **Redis Lua 原子预留 + async finalize** |
| 前端 | 推理链 | **TurnMetaEnvelope + 历史 metadata 回填** |
| 测试数 | 较早 | **1246** |
| Turn / 文档租户 | 未单列 | **§6.8、§10.4、documents Alembic** |
| 多轮/World/学习 | 未系统索引 | **§10.5、§44(2026-06-12)** |
| 架构叙事 | Multi-Agent | **Runtime-First Cognitive OS** + RuntimeContribution |
| Web | 双轨 web/web_intel | **web_intelligence 单轨**（manifest 3.1.0） |
| 计费 | 内存估价 | **billing_runtime + ledger 表** |

---



---

## 46. Runtime-First 统一运行时（Contribution / StateGraph）

### 46.1 设计原则

| 原则 | 说明 |
|------|------|
| **Runtime 优先于 Agent** | 新能力先归属 Goal / Evidence / Memory / World / Capability / Governance Runtime，再决定是否新增 Tier-1 Provider |
| **单一贡献契约** | 能力执行产出 `RuntimeContribution`，禁止长期并存互不可合并的 `DataResult`/`SearchResult` 思维（边界层仍用 `AgentResult` 传输） |
| **认知对象统一演化** | `CognitiveStateGraph` 将 Goal→Evidence→Memory→World 连成单链写入 `ctx.metadata` |

### 46.2 模块地图

| 模块 | 路径 | 职责 |
|------|------|------|
| RuntimeContribution | `kernel/agent_runtime/runtime_contribution.py` | 合并、桥接 `AgentContribution`、metadata 序列化 |
| Evidence Runtime | `kernel/runtime/evidence_runtime.py` | `merge_turn_evidence`、`apply_turn_contributions_to_context` |
| CognitiveStateGraph | `kernel/runtime/cognitive_state/cognitive_state_graph.py` | 图节点与 `apply_contribution_to_graph` |
| Cognitive State Bus | `kernel/runtime/cognitive_state/bus.py` | `apply_runtime_contribution_to_bus`、evidence/memory 绑定 |
| Failure from risks | `kernel/agent_runtime/failure_from_contribution.py` | `failure_memory` 写入 |
| World Decision | `kernel/agent_runtime/world_decision_runtime.py` | projected / counterfactual 启发式 |
| Goal Progress | `kernel/goal/goal_progress.py` | lifecycle 同步 + Redis persist 切片 |

### 46.3 接线点（必须走的主链）

1. **Tier-1 执行**：`agent_runtime_executor.execute_task` → trace 含 `runtime_contribution`  
2. **Executive / Data 回合**：`record_capability_outcomes(..., ctx=ctx)` → `attach_goal_participation_metadata`  
3. **Supervisor**：`prepare_run` → `enrich_world_projection_for_turn`  
4. **Executive 结束**：`persist_goal_progress`  
5. **响应组装**：`executive_result_to_kernel_response` → metadata 透出 §14.5 字段  

### 46.4 成熟度（见 `CAPABILITY_MATURITY.md`）

| 能力 | 状态 |
|------|------|
| RuntimeContribution | 生产 |
| CognitiveStateGraph | **生产**（单集群；bus 单写 + Redis 可选；多副本强一致 ⚠️） |
| Data V2 circuit → failure_memory | 生产（`data_v2_failure_memory.py`） |
| World Simulation（counterfactual） | 启发式 / P3 骨架 |
| World Decision Runtime | prepare_run + dispatch 双挂 |

契约：`test_runtime_contribution_contract.py`、`test_evidence_runtime_contract.py`、`test_failure_memory_contribution_contract.py`。

---

## 47. 计费、账本与 Alembic 企业表

### 47.1 回合成本流

```text
ModelGateway 累加 tokens（turn_metering）
  → enterprise_outcomes / finalize_turn：apply_billing_to_metadata
  → resolve_turn_cost（显式 estimated_cost 优先，否则 token 估价）
  → record_turn_billing → BillingManager.record_usage
  → [可选] persist_ledger_entry → billing_ledger
  → control_plane.consume_turn_quota(_async)
  → usage_metering.record_turn
```

**费率**：`enterprise_billing_prompt_per_million` / `enterprise_billing_completion_per_million`（`settings.py`）。

### 47.2 数据库迁移链（单 head）

```text
… → 20260514_cognitive_events
… → 20260606_enterprise_tenant → 20260606_enterprise_tenants_rls
20260610_merge_cognitive_enterprise_heads（合并 cognitive + enterprise 双 head）
  → 20260611_billing_invoice_tables
```

| 表 | 用途 |
|----|------|
| `tenants` | 租户主数据（`20260606_enterprise_tenant_tables`） |
| `billing_ledger` | 按 turn 成本行 |
| `billing_invoices` | 对账/发票草稿 snapshot |

**RLS**：`20260606_enterprise_tenants_rls`（仅 PostgreSQL）；上线前见 **`docs/runbooks/tenant-rls-staging.md`**。

### 47.3 运维检查

```bash
python -m alembic heads          # 必须 1 个 head
python -m alembic upgrade head   # staging Postgres
python -m pytest -q tests/test_alembic_single_head_contract.py tests/test_billing_runtime_contract.py
```

---

## 48. Turn Envelope 字段映射详表

> **权威副本**：`docs/architecture/turn_envelope_field_mapping.md`（后端改字段须先改该文 + `streamEnvelope.ts` + 契约测试）。

### 48.1 前端 `TurnMetaEnvelope` ← 后端载荷

| 前端字段 | 后端来源（优先级） | 说明 |
|----------|-------------------|------|
| `content` | `data.content` → `data.answer` | 用户可见正文 |
| `execution_graph` | `data.execution_graph` | DAG / 执行图 |
| `citations` / `annotations` | 同名顶层 | RAG / 冲突注解 |
| `metadata` | `data.metadata` 浅拷贝 | 全量 turn 元数据 |
| `control_plane` | `data` → `metadata.control_plane` | 企业控制面 |
| `capabilities_used` | `data` → `metadata` | 本 turn 能力列表 |
| `prompt_tokens` / `completion_tokens` | `data` → `metadata` | Token 计量 |
| `enterprise_telemetry` | `data` → `metadata.semantic_observability.enterprise_telemetry` | 企业遥测 |
| `result_refs` | `data` → `metadata` | SQL/表引用 |
| `needs_clarification` | `data` / `metadata` / `turn_outcome===clarification` | 澄清门 |
| `clarification` | `data` → `metadata` | 澄清载荷 |
| `turn_outcome` | `data` → `metadata` | success / error / clarification / degraded |
| `governance_warnings` | **前端派生** | `runtime_degraded[].subsystem` + `control_plane.allowed===false` |

### 48.2 `metadata` 高频子字段（按写入方）

| 子字段 | 写入方 | 用途 |
|--------|--------|------|
| `semantic_observability` | `GovernanceCenter.evaluate_turn` | 降级、合规、telemetry |
| `runtime_degraded` | 各子系统 | → governance_warnings |
| `goal_graph` / `goal_progress` | Goal runtime | 多目标 UI |
| `goal_participation` | `attach_goal_participation` | Agent→Goal 贡献 |
| `cognitive_state_graph` | `persist_graph_on_context` | 认知状态图快照 |
| `cognitive_runtime_state` | `cognitive_state/bus.py` | phase、evidence_ids |
| `runtime_contribution_turn` | `merge_runtime_contributions` | 回合贡献合并 |
| `advanced_analytics` | Data V2 Supervisor Phase4 | mode、degraded、各分析是否执行 |
| `data_intelligence` / `data_intelligence_turn` | DI runtime | 数据智能摘要 |
| `verification_report` | Data V2 verify | SQL 质量门禁 |
| `failure_memory` | run_outcomes / risk | 失败记忆摘要 |
| `billing_attribution` | `finalize_turn` | 计费 |

### 48.3 流式合并（`kernel/agent_runtime/stream_metadata.py`）

`_V3_STREAM_KEYS` 含：`agent_runtime_v3`、`goal_participation`、`cognitive_state_graph`、`cognitive_runtime_state`、`cognitive_runtime_p3`、`world_projection`、`data_intelligence_turn`、`route` 等 — 由 `merge_agent_runtime_v3_into_metadata` 写入 `final_answer.metadata`。

### 48.4 SSE 事件与 Envelope 关系

| SSE `type` | 与 Envelope |
|------------|-------------|
| `delta` | 累积为 `content` |
| `reasoning_step` / `dag_*` / `agent_*` | `execution_graph` / DagTimeline |
| `final_answer` | `normalizeFinalAnswerEnvelope` 入口 |
| `error` | 非 envelope；Chat 错误态 |

---

## 49. 需求矩阵、成熟度与近期落地索引

> **权威**：`docs/ARCHITECTURE_REQUIREMENTS_MATRIX.md`（16+1 项 + CI）。细粒度 partial 债：`docs/architecture/requirements_gap_matrix.md`。

### 49.1 矩阵项状态速览（2026-06-12）

| # | 项 | 状态 | 代码锚点 |
|---|-----|------|----------|
| 1–3,5–6,11–17 | RuntimeGateway / Supervisor / Goal / Capability / Governance / Multi-Goal / Contract / Metrics / V4 off / Data V2 / Arch Gov / Agent V3 | **done** | 见 §5、§14–§19 |
| 4 | State-based Runtime | **partial** | cognitive_state Redis；多副本强一致 ⚠️ |
| 7 | Memory Fabric | **partial** | `memory/fabric/`；跨集群 graph ⚠️ |
| 9 | Context Fabric | **partial** | DST/指代已实装；composer 可深化 |
| 10 | World Model | **partial** | turn begin/end + slice hooks；生产 Redis 待验 |


| 18–21 | P0 认知平台 | **done** | `test_p0_cognitive_platform_contract` |
| 22–26 | P1 决策智能 | **done** | `test_p1_decision_intelligence_contract` |
| 27 | World Simulation 入门 | **partial** | counterfactual |
| 28–30 | P2 演化/语义闭环/跨进程 | **done/partial** | `test_p2_completion_contract` |

### 49.2 规划 Phase A–D 对照

| Phase | 目标 | 一致？ |
|-------|------|--------|
| A 收敛主路径 | V2 默认、凭据 SSOT、web 单轨、evidence | **是** |
| B 证据同构 | Tier-1 evidence_objects、strict profile | **是**（staging 强制 strict） |
| C 企业化 | tenant RLS、计费持久化 | **否**（RLS migration 外部） |
| D 减负 | learning hook、CAPABILITY_MATURITY、V4 删源码 | **部分**（hook + 文档；V4 未删） |

### 49.3 近期代码落地（便于复盘）

| 能力 | 模块 | 契约 |
|------|------|------|
| history SSOT | `RuntimeContext.to_metadata_dict` + `chat.py` | `test_preference_world_data_learning_contract` |
| 多轮 | `multi_turn_resolution` | `test_multi_turn_resolution_contract` |
| World hydrate/finalize | `world_turn_begin` / `world_turn_finalize` | 同上 |
| 偏好 | `preference_injection` | 同上 |
| Data 学习 + 熔断 | `supervisor` + `data_agent` + `learning_hook` | 同上 + `test_data_v2_circuit_breaker_failure_memory_contract` |
| RAG/Web 证据 + claim | `enrich_evidence_intelligence` | `test_rag_evidence_intelligence_contract`、`test_web_intelligence_agent_contract` |
| state_block 多轮 | `context_assembler._build_state_block` | `test_preference_world_data_learning_contract` |

### 49.4 仍待 ROI 项（非阻塞主路径）

- 生产 RAG LLM 事实核验（当前为确定性 claim anchor）
- Postgres 全表 RLS + 真发票计费
- `legacy/v4` 源码删除
- 多副本 CognitiveStateGraph 强一致
- `context_composer` 与 Context Fabric 深度合并

---

## 50. P0/P1/P2 认知平台能力专章

### P0 — 平台骨架

| 能力 | 模块 | 契约 |
|------|------|------|
| Goal Supervisor | `kernel/goal/goal_supervisor.py` | `test_p0_cognitive_platform_contract` |
| Business Semantic | `agents/data_agent_v2/business_semantic_agent.py` | DAG manifest |
| Cognitive Iteration | `kernel/runtime/cognitive_iteration.py` | P0 contract |
| Strategy → Planner | `strategy_pattern.py` + `dispatch_enrichment` | `learning_hook` |

### P1 — 决策智能

| 能力 | 模块 |
|------|------|
| Claim Graph | `services/evidence_graph/claim_graph.py` |
| Evidence Cluster | `services/rag_retrieval_clusters.py` |
| Web Coverage | `agents/web_intelligence/coverage_evaluator.py` |
| Capability Score | `kernel/capability_intelligence/capability_score.py` |
| Predictive World | `kernel/cognition/predictive_world.py` |

### P2 — 演化与自优化

| 能力 | 模块 |
|------|------|
| Self-Optimizing | `kernel/runtime/self_optimizing_runtime.py`（apply 默认 false） |
| Semantic 闭环 | `finalize_semantic_and_evolution` + `semantic_helpers` |
| Capability Evolution | `evolution_hook.py`（Executive 9.5 与 finalize **去重**） |
| Autonomous Goals | `autonomous_goal_discovery.py`；`kernel_autonomous_goal_commit_enabled` 默认 false |

### 配置（`.env.example`）

`KERNEL_CLAIM_GRAPH_ENABLED`、`KERNEL_WEB_COVERAGE_EVALUATOR_ENABLED`、`KERNEL_CAPABILITY_SCORE_RANKING_ENABLED`、`KERNEL_PREDICTIVE_WORLD_ENABLED`、`KERNEL_CAPABILITY_EVOLUTION_ENABLED`、`KERNEL_AUTONOMOUS_GOAL_COMMIT_ENABLED`、`KERNEL_SELF_OPTIMIZING_RUNTIME_*`。

---

## 附录 A：CognitiveKernel.run 内部分支（细化）

```text
classify_intent → direct_answer / identity / WorkingMemory
  → V5 L0 / cache / L1
  → should_use_tool_fast_path → RuntimeGateway.try_tool_fast_path
  → RuntimeGateway.run
```

---

## 附录 B：CognitiveExecutive 阶段与 Policy 钩子对照

PLAN → `on_planning`；PRE_FUSION → `on_evidence_fusion`；MEMORY → `on_memory_write`。`kernel_policy_mutation_fail_closed` 可 abort turn。

---

## 附录 C：import 边界与单实现治理（运维速查）

`check_import_boundaries.sh`；`importlinter.ini`（RuntimeGateway 不得依赖 cognitive_executive/planner_facade 等）。合规审计实现：`kernel/governance/compliance_audit_store.py`。

---

## 附录 D：DataAgent V2 文件清单（`agents/data_agent_v2/`）

`supervisor.py`、`dag_builder.py`、`business_semantic_agent.py`、`types.py`、`turn_metadata.py`、`error_classifier.py`、各 `*_agent.py`、`data_critic.py`、`reflection_agent.py`、`knowledge_*`、`insight/statistical/visualization` 等（见 §21）。

---

## 附录 E：Redis / 持久化 Key 约定（节选）

| Key 模式 | 用途 |
|----------|------|
| `opentrace:quota:turns:{isolation_key}:{YYYYMMDD}` | 日 turn 计数 |
| `opentrace:quota:cost:{isolation_key}:{YYYYMMDD}` | 日 cost |
| `opentrace:quota:limits:{isolation_key}` | HASH daily_turns / daily_cost |
| `opentrace:usage:daily:{tenant_id}:{YYYYMMDD}` | usage metering |
| `world_state:{session_id}` | World grounding |

---

## 附录 F：关键环境变量索引（`.env.example` 对照）

| 变量 | 含义 |
|------|------|
| `KERNEL_ORCHESTRATOR_V4_ENABLED` | false → vNext |
| `DATA_AGENT_V2_ENABLED` / `DATA_AGENT_V2_CLARIFICATION_ENABLED` | V2 与澄清门控 |
| `KERNEL_AGENT_RUNTIME_V3_STRICT` / `KERNEL_UNIFIED_EVIDENCE_STRICT` | staging 可强制 true |
| `ENTERPRISE_QUOTA_REDIS_ENABLED` | 配额 Redis 权威 + Lua 预留 |
| `ENTERPRISE_USAGE_REDIS_ENABLED` | 用量日聚合 |
| `KERNEL_WEB_INTELLIGENCE_PREFERRED` | web → web_intelligence |
| `APP_ENV` | staging 触发 profile 覆盖 |
| `KERNEL_CLAIM_GRAPH_ENABLED` | Claim Graph 管线 |
| `KERNEL_WEB_COVERAGE_EVALUATOR_ENABLED` | Web 覆盖补搜 |
| `KERNEL_CAPABILITY_EVOLUTION_ENABLED` | 回合尾演化分析 |
| `KERNEL_AUTONOMOUS_GOAL_COMMIT_ENABLED` | proposal 挂载 goal_graph（默认 false） |

---

## 附录 G：RuntimeTurnDispatcher.resolve_runtime_name 决策树

```text
strategy_projection.preferred_runtime
  ├─ data_intelligence → data_intelligence
  ├─ multi_goal → multi_goal
  └─ goal_graph.goals.length > 2 → multi_goal
      else → cognitive_executive
```

---

## 附录 H：Agent Runtime V3 与 Tier 拓扑

Manifest v3.0.0：tier1 bootstrap agents；tier2 仅 DAG 内部。`agent_runtime_executor`：`validate_contribution` + `missing_unified_evidence`（strict）。`contribution_from_agent_result` ← `evidence_objects`。

---

## 附录 I：RuntimeGateway 快路径 API

```python
# kernel/runtime_gateway.py（概念签名）
class Tier0ChatContext:
    db, current_user, data_query_fn, data_query_request_factory

async def try_tier0_chat(query, session_id, request_id, tier0_ctx, force_database, data_source_id) -> Tier0SyncOutcome | None
async def try_tool_fast_path(request) -> KernelResponse | None
async def stream_tool_fast_path(request) -> AsyncIterator[dict]
```

Gateway `tier0_paths.py`：`run_database_direct_tier0` 包装 `DataQueryRequest` 工厂，避免 kernel 依赖 gateway 路由模块。

---

## 附录 J：Manifest 与 Bootstrap/DAG 校验

```python
from kernel.agent_runtime.manifest import validate_manifest_integrity, get_manifest, reload_manifest
from kernel.agent_runtime.sync import validate_bootstrap_parity
from agents.data_agent_v2.dag_builder import (
    build_cognitive_dag,
    get_enabled_agents,
    validate_dag_against_manifest,
    validate_dag_spec,
)

reload_manifest()
assert validate_manifest_integrity() == []
assert validate_bootstrap_parity() == []

spec = build_cognitive_dag("测试查询", enabled=get_enabled_agents())
assert validate_dag_spec(spec) == []
assert validate_dag_against_manifest(spec) == []
```

| 校验 | 职责 |
|------|------|
| `validate_manifest_integrity` | YAML `bootstrap`/`worker` 列表与 entry 标志、`bus_eligible` 不变量 |
| `validate_bootstrap_parity` | `agents/bootstrap.py` 工厂表覆盖 manifest bootstrap |
| `validate_dag_against_manifest` | Data V2 DAG `agent_type` ∈ tier2 manifest；semantic 依赖与 topology |
| `manifest.assert_bus_routing` | 发布 Bus 任务前拒绝 `bus_eligible=false` |

契约：`tests/test_agent_runtime_v3_contract.py`（`test_manifest_integrity`、`test_rules_in_worker_list_not_on_bus`）。

---

## 附录 K：`gateway/api_gateway/main.py` 挂载 Router 全表

| 模块 | 典型前缀 / 能力 |
|------|-----------------|
| `health` | `/health`、`/health/deps`、`/health/cognitive-os` |
| `prometheus` | Prometheus 导出 |
| `auth` | JWT 登录 |
| `chat` | 同步/SSE、Tier0 前置 |
| `conversations` | 会话、消息、`MessageOut.metadata` |
| `cognitive` | 认知调试 |
| `documents` | 文档与向量索引 |
| `memories` | 记忆 CRUD |
| `tasks` | 异步任务 |
| `audit` | 审计 |
| `connectors` | 连接器 |
| `skills` / `analytical_skills` | 技能市场 |
| `data` / `databases` / `table_relationships` | 数据源、语义、关系图 |
| `feedback` | 反馈 |
| `sandbox` | 沙箱下载 |
| `admin` / `enterprise_admin` | 管理、租户、配额 |
| `rules` | 规则配置 |
| `metrics` | 语义指标 |
| `ui_settings` | UI 配置 |

启动副作用：`register_builtin_agents()`、`ensure_runtime_schema()`、`memory_event_subscriber` 后台任务、`TenantContextMiddleware`（可降级跳过）。

---

### 44 补充（2026-06-11 文档覆写批次）

1. **service_cursor.md** 扩写：§6 熔断/Graph Redis、§19 Worker bus 过滤、§20 Data/Vision、§21 DAG manifest 校验、**§48 Turn Envelope**、**附录 J/K**。  
2. 与代码对齐：`data_v2_failure_memory`、`kernel_vision_require_images`、`validate_manifest_integrity`、`rules` worker 列表。  
3. 测试基线 **1158**；`lint-imports` 入 CI / weekly checklist。

### 44 补充（2026-06-12 认知能力深化批次）

1. **多轮**：`resolve_multi_turn_query`（DST + `ReferenceResolver`）在 `CognitiveKernel.run/stream` 的 `classify_intent` 之前；metadata `multi_turn_resolution`；Gateway `RuntimeContext.to_metadata_dict()` 与 `kernel_metadata["history"]` 双写 `conversation_history`。  
2. **World**：`hydrate_world_model_for_turn`（`world_turn_begin`）→ metadata `world_hydrate` / `world_cross_process`；回合末 `finalize_world_model_for_turn`（`world_turn_finalize`）+ `world_slice_hooks`（data/rag）。  
3. **偏好**：`apply_preference_injection_for_turn` → `user_preference_context_block`；`merge_learned_preference` 写回 `ConversationState.learned_preferences`。  
4. **Data V2 学习**：`data_agent_v2_auto_learning_enabled` → `_run_learning_pipeline`（feedback/pattern/knowledge）；成功路径 `record_agent_learning_signal`；熔断 `data_v2_failure_memory` + learning_hook（`agents/data_agent.py`）。  
5. **RAG/Web 证据同构**：`enrich_evidence_intelligence` + `claim_verification`（`rag_claim_anchor_enabled`）；Web metadata 含 `rag_evidence_intelligence.source_kind=web`。  
6. **Context**：`ContextAssembler._build_state_block` 含 `active_constraints`（含 user_correction）、`last_turn_type`、`active_domain`。  
7. **契约**：`test_preference_world_data_learning_contract`、`test_multi_turn_resolution_contract`、`test_rag_evidence_intelligence_contract`、`test_web_intelligence_agent_contract`。

---

*文档结束 — 维护时请同步：`pytest --collect-only` 数量、`docs/architecture/turn_envelope_field_mapping.md`、`docs/CAPABILITY_MATURITY.md`、`docs/ENV_PROFILES.md`。*
