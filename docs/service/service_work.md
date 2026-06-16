# OpenTrace 项目全量代码梳理（ Enterprise Cognitive OS）

> **事实来源**：仅以当前仓库源码、`infra/config/settings.py`、`.env.example`、`docker-compose.yml`、`importlinter.ini`、启动/验证脚本与 `tests/` 契约为准。  
> **格式基线**：在 `docs/service/service_claude.md` 目录深度上扩展；本文增加 **企业控制面**、**每 Agent 内部管线**、**全链路走向图**、**流式/SSE 企业字段**、**Capability 执行路由**、**Agent Topology Manifest** 与 **发布门禁** 的完整索引。  
> **最后更新**：2026-06-08  
> **测试规模**：`PYTHONPATH=. pytest tests/ --collect-only` → **1044** 个用例；vNext 门禁 `bash scripts/run_vnext_final_tests.sh`（**27** 个契约文件）；企业门禁 `bash scripts/run_enterprise_contract_tests.sh`（**27** 个契约文件）。  
> **生产主路径**：`CognitiveKernel` → `RuntimeGateway` → `CognitiveSupervisor.prepare_run` → `RuntimeTurnDispatcher` → `kernel.runtime.registry` → `cognitive_executive` | `data_intelligence` | `multi_goal` → `run_outcomes` / `turn_outcomes` / `enterprise_outcomes`（V4 默认禁用，实现于 `legacy/v4/`）。

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
10. [聊天主链路（同步 / SSE / 企业预检）](#10-聊天主链路同步--sse--企业预检)
11. [认知内核与认知控制](#11-认知内核与认知控制)
12. [V5 路由层与快路径](#12-v5-路由层与快路径)
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
44. [工程变更日志（2026-06 Enterprise 深化）](#44-工程变更日志2026-06-enterprise-深化)
45. [附录：与 service_claude 的差异](#45-附录与-service_claude-的差异)

**附录索引**：A [CognitiveKernel 分支](#附录-acognitivekernelrun-内部分支细化) · B [Executive × Policy](#附录-bcognitiveexecutive-阶段与-policy-钩子对照) · C [import 边界](#附录-cimport-边界与单实现治理运维速查) · D [DataAgent V2 文件清单](#附录-ddataagent-v2-文件清单agentsdata_agent_v2) · E [Redis Key](#附录-eredis--持久化-key-约定节选) · F [环境变量](#附录-f关键环境变量索引envexample-对照) · G [Runtime 解析规则](#附录-gruntimeturndispatcherresolve_runtime_name-决策树) · H [Agent Runtime V3](#附录-hagent-runtime-v3-与-tier-拓扑)

---

## 1. 项目定位与产品边界

OpenTrace 是以 **Cognitive Kernel** 为唯一聊天中枢的 **AgentOS / Enterprise Cognitive OS** 后端：把对话、RAG、工具、联网、数据分析、记忆、任务、审计、技能市场、连接器、附件、多租户与运行时观测组织成可 Docker 部署的一体化服务，并配套 React 管理端。

| 能力域 | 代码锚点 | 对外表现 |
|--------|----------|----------|
| 统一认知入口 | `kernel/cognitive_kernel.py` | 所有 `/api/v1/chat` 经 `CognitiveKernel.run/stream` |
| 意图与预算 | `kernel/cognitive_controls.py` | Intent Lock、CognitiveBudget、零 LLM 分类 |
| 分层路由 | V5：`query_router_v2`、`semantic_cache`、`tiny_router` | L0 / L0.5 / L1，降本降延迟 |
| **vNext 编排** | `RuntimeGateway` + `CognitiveSupervisor` + `RuntimeTurnDispatcher` | Goal、治理、证据、Artifact、Replay |
| **企业控制面** | `control_plane/`、`tenant/`、`gateway/chat_preflight.py` | 预检、配额、合规、PII、租户头 |
| **Goal-centric Runtime** | `kernel/goal/*` | 状态机、回合收尾、Evidence/Memory 绑定、Portfolio |
| **Policy Runtime** | `kernel/governance/policy_runtime.py` | plan / evidence / memory / replay 变异点 |
| **World State** | `kernel/cognition/runtime_grounding.py`、`world/` | 七切片 + Goal 切片 + Redis 可选持久化 |
| 数据智能 | `agents/data_agent_v2/` + `services/data_intelligence_runtime` | Text2SQL；Tier-1 registry runtime；KPI/根因启发式 |
| 检索增强 | `agents/rag_agent.py` + `services/rag_evidence_intelligence.py` | HyDE、混合检索、证据图、矛盾检测 |
| 联网智能 | `agents/web_intelligence_agent.py`（CognitiveAgent） | 搜索 → rank → evidence graph |
| 多 Agent | `agents/*` + `execution` 平面 | Redis Agent Bus（stream / pubsub） |
| 记忆 | `memory/*` + `memory/fabric/` | 六层记忆 + TMS bridge + Redis graph shadow |
| 治理 | **`kernel/governance/`**（唯一 Governor 实现） | 证据/风险/审计/语义健康/合规审计 store |
| 可观测 | OTel、Prometheus、`enterprise_telemetry`、`turn_metering` | `/health/*`、**`/health/cognitive-os`**、企业指标 |
| **拓扑契约** | `kernel/agent_runtime/agent_topology_manifest.yaml` | bootstrap / worker / bus / capability contract 单一事实源 |

**非目标（当前仓库）**：

- 前端默认**不在** `docker-compose.yml` 核心栈内，需 `frontend` 本地 `npm run dev`。
- 跨进程/多副本 **World Model** 强一致仍为架构债（单进程 + Redis `world_state:{session_id}`）。
- Postgres **RLS POLICY** 全表启用需独立 migration 工程。
- 真实发票级计费仍为 token 估价 + 内存聚合（`tenant/usage_metering.py`）。
- 本文档**不**写入 `.env` 中真实密钥。

---

## 2. 当前代码状态摘要

| 维度 | 状态（2026-06-08） |
|------|---------------------|
| API | FastAPI，`APP_PORT` / 健康检查默认 **14100**（`GATEWAY_PORT` 可与 Compose 映射不同，以 `APP_PORT` 为准） |
| 前端 | React 18 + Vite + TS，默认 **14108** |
| 主聊天 | `POST /api/v1/chat`（同步 + SSE） |
| 编排 | **vNext**；`kernel_orchestrator_v4_enabled=false` |
| 健康 `orchestrator` | `orchestrator_label.py`：V4 关 → **`vnext`** |
| Agent Bus | `KERNEL_AGENT_BUS_ENABLED`、stream 模式 |
| DataAgent | V2 默认 `data_agent_v2_enabled=true` |
| Web 执行路由 | `kernel_web_intelligence_preferred=true` 时 `web` → `web_intelligence` |
| Agent Runtime V3 | `kernel_agent_runtime_v3_enabled`（manifest + `agent_runtime_executor`） |
| 测试 | **1044** collected |
| Import 边界 | `kernel/**` 不得 `from governance.*`（合规审计在 `kernel/governance/compliance_audit_store.py`） |

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
kernel_orchestrator_v4_enabled=false
```

---

## 3. 技术栈与依赖

### 3.1 后端

Python **3.11+**、FastAPI、SQLAlchemy 2.0 asyncio、asyncpg、Alembic、pgvector、Redis 7、OpenAI-compatible LLM（多 `LLMRole`）、sqlglot、pydantic-settings、black/ruff/mypy、OpenTelemetry、prometheus-client、import-linter。

### 3.2 前端

React 18、TypeScript、Vite、Zustand、react-router-dom、react-markdown、Recharts。

### 3.3 Docker Compose 核心服务

`api`（:14100）、`agent-worker`、`postgres`（pgvector）、`redis`（宿主常 6380）、可选 `prometheus` / `jaeger`。

---

## 4. 整体架构与六域模型

| 域 | 职责 | 主要目录 |
|----|------|----------|
| **Cognitive** | 规划、理解、多问题、World Model | `kernel/cognition/` |
| **Strategy** | 能力链、预算、路由提示 | `kernel/strategy/`、`capability_runtime/` |
| **Runtime** | Executive、证据、融合、批评、Artifact | `kernel/runtime/` |
| **Protocol** | 稳定契约 | `kernel/protocol/` |
| **Governance** | 控制面、Policy Runtime、合规审计 | **`kernel/governance/`** |
| **Goal** | 一等目标生命周期 | `kernel/goal/` |
| **Enterprise** | 租户、配额、计费、遥测 | `tenant/`、`control_plane/`、`observability/` |
| **Agent Runtime** | Manifest、Tier-2、Bus、贡献度 | `kernel/agent_runtime/` |

```text
Frontend :14108
    │ HTTP / SSE + X-Tenant-Id / X-Org-Id / X-Workspace-Id
    ▼
gateway/api_gateway/main.py
    │ chat_preflight · tenant RLS session vars · reset_turn_tokens
    ▼
CognitiveKernel
    │ classify_intent · V5 · memory_injection · ContextFabric
    ▼
RuntimeGateway
    │ CognitiveSupervisor.prepare_run + control_plane_gate
    ▼
RuntimeTurnDispatcher → registry (Tier-1)
    ├─ cognitive_executive
    ├─ data_intelligence
    └─ multi_goal
    ▼
run_outcomes + turn_outcomes + enterprise_outcomes
```

---

## 5. vNext 主路径（强制遵守）

```text
CognitiveKernel.process / stream
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
```

| 禁止 | 校验 |
|------|------|
| Gateway 内跑 Executive / Planner | importlinter、supervisor 契约 |
| vNext 路径 import `legacy.v4` 实现体 | `check_import_boundaries.sh` |
| `kernel/**` 直接 `from governance.*` | `test_kernel_import_boundaries` |
| Gateway 内单独拼 Artifact 终态 | `run_outcomes` 拥有 |

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
  │     └─ 拒绝 → AppException policy_denied JSON
  ├─ reset_turn_tokens()
  ├─ _ensure_session(..., tenant_metadata)  → ChatSession.tenant_id/org_id/workspace_id
  ├─ set_session_tenant_context(db, TenantContext)  → app.tenant_id RLS vars
  │
  ├─ CognitiveKernel.run(KernelRequest)
  │     ├─ classify_intent / IntentLock / CognitiveBudget
  │     ├─ V5: L0 → semantic_cache → L1（可被 force_mode、附件跳过）
  │     ├─ memory_injection、SelfModel、ContextFabric
  │     └─ RuntimeGateway.run
  │           ├─ supervisor.prepare_run
  │           └─ dispatcher → resolve_runtime_name（见附录 G）
  │                 ├─ cognitive_executive → CognitiveExecutive.execute（见 §15）
  │                 ├─ data_intelligence → run_data_intelligence_turn（见 §18）
  │                 └─ multi_goal → run_multi_question（见 §17）
  │
  ├─ run_outcomes: Artifact、replay、governance bundle
  ├─ apply_turn_goal_and_memory_outcomes
  ├─ enrich_turn_enterprise_metadata（control_plane、usage_metering、compliance audit、prometheus）
  │
  └─ ChatResponse + metadata（goal_graph、semantic_observability、control_plane…）
```

### 6.2 流式聊天（SSE）

```text
POST /api/v1/chat (stream=true)
  → 同上预检与会话租户（在 stream 分支前已完成）
  → CognitiveKernel.stream → RuntimeGateway.stream → stream_turn
  → reasoning_step(ROUTE, runtime_name) → dispatch_runtime(..., event_cb)
  → 事件: delta | reasoning_step | final_answer | error
  → build_stream_final_metadata + enrich_turn_enterprise_metadata
  → final_answer.data 顶层可含: control_plane, capabilities_used, prompt_tokens, enterprise_telemetry
  → chat.py 持久化 ConversationState、Trace、CognitiveEventBus
```

### 6.3 能力执行（Executive 内子任务）

```text
ExecutionPlan.subtasks[]
  → kernel/runtime/executor.py
  → capability_registry.resolve_execution_agent(agent_type)
       web / web_search → web_intelligence（若已注册且 kernel_web_intelligence_preferred）
  → TaskMessage → agent.execute() 或 agent_runtime_executor（V3）
  → record_capability_outcomes + collect_executed_capability_types → ctx.metadata["capabilities_used"]
```

### 6.4 Data 路径分叉

```text
force_database + data_source_id
  → gateway/data.py data_query 快路径（可 stream 直出）
否则
  → Kernel → strategy_projection.preferred_runtime=data_intelligence 或 Executive 内 data 子任务
DataAgent (agents/data_agent.py)
  → data_agent_v2_enabled ? DataAgentV2Supervisor : DataAgentV1 pipeline
```

### 6.5 Supervisor 拒绝早退（不进入 Executive）

```text
prepare_run → route_hint in:
  control_plane_denied | runtime_policy_denied | runtime_governance_denied
  → RuntimeGateway 短路 → KernelResponse / SSE error
  → goal_recovery.mark_goals_blocked_for_governance（policy/gov 路径）
```

### 6.6 Registry 治理拒绝

```text
dispatch_runtime → evaluate_registry_dispatch 失败
  → KernelResponse route=registry_dispatch_denied
  → ctx.metadata.registry_dispatch_gate
```

---

## 7. 目录结构与模块地图

```text
opentrace/
├── gateway/api_gateway/
│   ├── main.py · routers/chat.py · chat_preflight.py · tenant_middleware.py
│   └── routers/enterprise_admin.py
├── kernel/
│   ├── cognitive_kernel.py · runtime_gateway.py · cognitive_controls.py
│   ├── cognitive_supervisor/   # prepare · gate · run_outcomes · enterprise_outcomes · dispatch_enrichment
│   ├── runtime/                # executive · turn_dispatcher · registry · executor · multi_question_runtime
│   ├── goal/                   # lifecycle · turn_outcomes · portfolio · multi_goal_*
│   ├── governance/             # GovernanceCenter · policy_runtime · compliance_audit_store
│   ├── cognition/              # runtime_grounding · planner_facade · multi_question
│   ├── agent_runtime/          # manifest · executor · tier2_registry · dag_invoke · unified_evidence
│   ├── capability_runtime/ · capability_intelligence/
│   └── protocol/
├── control_plane/ · tenant/ · observability/
├── services/
│   ├── data_intelligence_runtime/
│   ├── evidence_graph/
│   └── rag_evidence_intelligence.py
├── agents/ · agents/data_agent_v2/
├── memory/fabric/ · world/
├── model/ · execution/ · tools/ · plugins/
├── legacy/v4/
├── frontend/ · tests/ · scripts/ · docs/ · alembic/
```

---

## 8. 前端应用

- 入口：`frontend/src/main.tsx` → `App.tsx`
- API：`frontend/src/api/client.ts`（`VITE_API_URL`）

| 页面 | 能力 |
|------|------|
| ChatPage | SSE、`delta` / `reasoning_step` / `final_answer`、推理链、执行图 |
| Databases / Documents | 数据源、RAG |
| Skills / Rules / Memory | 技能、规则、记忆 |
| Tasks / Audit / Settings | 任务、审计、集成 |

**建议展示 metadata**：`governance`、`goal_graph`、`goal_lifecycle`、`semantic_observability`、`replay_contract`、`control_plane`、`shared_world_state`、`data_intelligence`、`rag_evidence_intelligence`、`capabilities_used`、`agent_runtime_v3`、`goal_participation`。

---

## 9. API 网关与路由清单

- 应用：`gateway/api_gateway/main.py`
- 启动：`register_builtin_agents()`、`ensure_runtime_schema()`、memory 订阅

### 9.1 Router（前缀 `/api/v1`）

`health`、`prometheus`、`auth`、`chat`、`conversations`、`cognitive`、`documents`、`memories`、`tasks`、`audit`、`connectors`、`skills`、`ui_settings`、`data`、`databases`、`feedback`、`sandbox`、`admin`、**`enterprise_admin`**、`rules`、`metrics`、`table_relationships`、`analytical_skills`。

### 9.2 Enterprise Admin（`routers/enterprise_admin.py`）

| 路径 | 说明 |
|------|------|
| `GET /admin/enterprise/tenants` | 内存 TenantManager 列表 |
| `GET /admin/enterprise/control-plane/health` | 样例 evaluate_turn |
| `GET /admin/enterprise/capabilities/marketplace` | Capability OS 产品列表 |
| `GET /admin/enterprise/compliance/audit` | `list_recent_events_from_db` |
| `GET /admin/enterprise/usage/{tenant_id}` | usage + billing snapshot |
| `POST /admin/enterprise/tenants/{tenant_id}/quota` | 设置日配额 |

### 9.3 健康检查

| 路径 | 内容 |
|------|------|
| `GET /health` | 存活 |
| `GET /health/deps` | DB、Redis、Agent Bus、worker |
| **`GET /health/cognitive-os`** | flag 快照、Tier-1 runtime 列表、orchestrator 标签 |

---

## 10. 聊天主链路（同步 / SSE / 企业预检）

### 10.1 企业预检（`gateway/api_gateway/chat_preflight.py`）

```text
run_chat_preflight(query, user_id, session_id, tenant_md)
  → detect_pii_signals(query) → tenant_md.pii_detected
  → preflight_from_metadata → EnterpriseControlPlane.evaluate_turn
  → allowed=false → AppException（policy_denied + violations）
```

### 10.2 多租户头（`tenant_middleware.py`）

`X-Tenant-Id`、`X-Org-Id`、`X-Workspace-Id`、`X-Data-Residency` → `resolve_tenant_context` → `PolicyManager.apply_to_metadata` → `ensure_tenant_registered` → 异步 `upsert_tenant_record`。

### 10.3 Token 计量（`infra/observability/turn_metering.py`）

- 回合开始：`reset_turn_tokens()`（`chat.py` 构建 `KernelRequest` 前）
- `ModelGateway.complete`：累加 `prompt_tokens` / `completion_tokens`
- `ModelGateway.stream`：流结束后 `TokenCounter` 估算并 `add_llm_usage`
- `enrich_turn_enterprise_metadata`：`merge_turn_tokens_into_metadata` → `usage_metering.record_turn`

---

## 11. 认知内核与认知控制

### 11.1 CognitiveKernel（`kernel/cognitive_kernel.py`）

唯一 `run/stream`；复杂路径 **仅** `get_runtime_gateway().run/stream`。V4 仅在 `kernel_orchestrator_v4_enabled=true` 时经 shim 进入 `legacy/v4`。

### 11.2 Intent Lock（`kernel/cognitive_controls.py`）

`classify_intent()`、`IntentLock`、`CognitiveBudget`、`apply_intent_lock_to_context()`。L0/L1 复杂度可触发 `prepare_run` 的 **slim** 路径（`runtime_task_from_request_light`）。

### 11.3 横切模块

`clarification_gate.py`、`context_fabric*.py`、`memory_injection.py`、`semantic_cache.py`、`refine_planner.py`、`dialogue_state_tracker.py`、`history_retriever.py`。

---

## 12. V5 路由层与快路径

| 层 | 模块 | 开关 |
|----|------|------|
| L0 | `query_router_v2.py` | `kernel_l0_rule_router_enabled` |
| L0.5 | `semantic_cache.py` | `kernel_semantic_cache_enabled` |
| L1 | `tiny_router.py` | `kernel_l1_tiny_router_enabled` |
| Tool | `fast_tool_path.py` | `kernel_tool_fast_path_enabled` |

Facade：`kernel/routing/v5_facade.py`。

---

## 13. V4 编排器（遗留、默认禁用）

实现：`legacy/v4/orchestrator.py`；Shim：`kernel/orchestrator_v4.py`；开关：`kernel_orchestrator_v4_enabled=false`。健康标签与 `orchestrator_label.py` 在关闭时报告 **`vnext`**。

---

## 14. RuntimeGateway、Supervisor 与 TurnDispatcher

### 14.1 CognitiveSupervisor.prepare_run（`supervisor.py`）

```text
evaluate_request_control_plane（最早；拒绝 → control_plane_denied）
  → runtime_task_from_request[_light]（L0/L1 slim）
  → RuntimePolicyEngine.evaluate_planning_phase（拒绝 → runtime_policy_denied）
  → RuntimeGovernor.evaluate_task（拒绝 → runtime_governance_denied）
  → build_runtime_context_from_kernel_request
  → _hydrate_world_state_if_enabled
  → bind_goal_graph_to_context · goal_projection
  → _apply_runtime_policy · _inject_strategy_projection · _seed_context_fabric
  → apply_dispatch_enrichment
  → route_hint（默认 cognitive_executive；多问/策略可改）
```

### 14.2 dispatch_enrichment（`dispatch_enrichment.py`）

`project_goal_graph_to_execution_hints` → `AdaptiveRiskEngine` → `runtime_grounding` → cognitive_state bind/hydrate → `context_fabric.evolve_runtime(phase=dispatch)`。

### 14.3 RuntimeTurnDispatcher（`runtime_turn_dispatcher.py`）

- `run_turn`：`resolve_runtime_name` → `dispatch_runtime`
- `stream_turn`：`reasoning_step` + `event_cb` 转发 Executive 内步骤 → 分片 `delta` → `final_answer`（`build_stream_final_metadata`）
- 流式治理拒绝 → `{type: error}`

### 14.4 run_outcomes（`run_outcomes.py`）

`build_runtime_artifact`、`executive_result_to_kernel_response`、`replay_contract` 片段、goal_graph 合并。

### 14.5 enterprise_outcomes（`enterprise_outcomes.py`）

`evaluate_turn`、异步 `record_compliance_event`、配额 `consume_turn_quota`、`usage_metering`、`build_shared_world_state`、可选 `save_session_world_state`、`enterprise_telemetry` + Prometheus。

---

## 15. Cognitive Runtime V2（Executive 管线）

入口：`kernel/runtime/cognitive_executive.py` — `CognitiveExecutive.execute()`。

```text
init / understand（UnderstandingEngine）
  → plan（PlannerFacade · PolicyRuntime.on_planning · phase governance）
  → build capability graph · validate_planned_capabilities（dispatch_pipeline）
  → execute（ExecutionRuntime / executor · DAG 节点 · event_cb 流式推理步）
       → resolve_execution_agent · record_capability_outcomes · capabilities_used
  → evidence bus（publish · resolve · ranking · lifecycle）
  → fusion（SequenceFusion / FusionEngine）
  → critic（Policy post_fusion）
  → memory write（Policy on_memory_write）
  → GoalRuntimeHooks · optional world_state persist
  → CognitiveExecutiveResult（answer · metadata · critic_result）
```

**Phase 严格模式**：`kernel_runtime_phase_transition_strict`；违规写入 `phase_transition_violations`。

---

## 16. Goal 生命周期、多目标与 turn_outcomes

### 16.1 状态机（`state_machine.py`）

`CREATED → PROJECTED → ACTIVE → EXECUTING → EVIDENCE_COLLECTED → FUSED → COMPLETED | FAILED → ARCHIVED`（含 BLOCKED、REPLANNING）。

### 16.2 turn_outcomes（`turn_outcomes.py`）

`apply_turn_goal_and_memory_outcomes`：`finalize_turn_goal_lifecycle` → `evolve_goals_after_execution` → `bind_goal_turn_to_memory_fabric`；data 路由合并 `enrich_data_turn_outcomes`。

### 16.3 Goal Portfolio（`goal_portfolio.py`）

Program → Task 层级；`enterprise_outcomes` 写入 `goal_portfolio` metadata。

### 16.4 多目标调度（`multi_goal_scheduler.py` / `multi_goal_resources.py`）

Portfolio 级资源与并行子目标（契约：`test_multi_goal_runtime_contract.py`）。

---

## 17. 认知规划门面与多问题运行时

| 模块 | 职责 |
|------|------|
| `planner_facade.py` | Goal / Strategic / Execution / Projection 四层 |
| `multi_question.py` | 多问题检测 |
| `multi_question_runtime.py` | 子图执行、SequenceFusion、`capabilities_used`、governance、`turn_outcomes` |

**Registry `multi_goal` handler**：`run_multi_question` 返回 `None` 时 **回退** `CognitiveExecutive.execute`（单问题降级）。

---

## 18. Runtime Registry、Tier-1 与 Data Intelligence

### 18.1 Tier-1 Runtime 表

| runtime | handler | 入参签名 |
|---------|---------|----------|
| `cognitive_executive` | `CognitiveExecutive().execute` | `(query, ctx, event_cb?)` |
| `data_intelligence` | `run_data_intelligence_turn` | `(request, ctx)` |
| `multi_goal` | `run_multi_question` → 可选 Executive | `(request, ctx, event_cb?)` |

`dispatch_runtime` 前：`evaluate_registry_dispatch` + `attach_tier_metadata`。

### 18.2 `run_data_intelligence_turn` 走向（`services/data_intelligence_runtime/__init__.py`）

```text
resolve_root_goal_from_ctx
  → capability_registry.get_agent("data")
  → TaskMessage（data_params、goal_id、session_id）
  → [V3] agent_runtime_executor.execute_task → contribution_to_agent_result
     [else] data_agent.execute(task)
  → attach_data_intelligence_to_metadata（sql、row_count、query 启发式）
  → record_capability_outcomes（data_query）
  → 组装 KernelResponse / Executive 兼容结果（含 data_intelligence metadata）
```

### 18.3 启发式层

`enrich_data_turn_outcomes`：空结果异常、KPI 问句、根因/下降类诊断 hint（确定性，契约：`test_data_intelligence_turn_outcomes_contract.py`）。

---

## 19. Agent 集群总览与 Worker

### 19.1 Manifest 与注册（`agent_topology_manifest.yaml` + `agents/bootstrap.py`）

Manifest **version 3.0.0**；`sync_manifest_to_runtime()` 后按 `bootstrap_agent_types` 实例化：

| agent_type | 类 | capability_type | owner_runtime |
|------------|-----|-----------------|---------------|
| `data` | `DataAgent` | `data_query` | tier1_data |
| `rag` | `RagAgent` | `document_retrieval` | tier1_executive |
| `web` | `WebAgent` | `web_search` | tier1_executive（可被 web_intelligence 取代） |
| `web_intelligence` | `WebIntelligenceAgent` | `web_search` | tier1_executive（`preferred_over: web`） |
| `tool` | `ToolAgent` | `tool` | tier1_executive |

契约：`test_agent_runtime_v3_contract.py`、`test_agent_stubs_contract.py`。

### 19.2 Worker（`agents/worker.py`）

与 API 相同 agent 集合；Redis Agent Bus 消费；DLQ、reclaim、heartbeat。

### 19.3 基类（`agents/base.py`）

`TaskMessage`（`task_id`、`agent_type`、`query`、`params`、`session_id`）  
`AgentResult`（`status`、`content`、`confidence`、`metadata`、`evidence`、`agent_trace`）

### 19.4 CognitiveAgent 契约（`agents/cognitive_agent.py`）

```text
execute()
  → perception → reasoning → planning → execute_core（子类实现）
  → reflection → learning
  → agent_trace 六阶段 · metadata.cognitive_agent=true
```

实现类：**`WebIntelligenceAgent`**。

### 19.5 Registry（`agents/registry.py`）

扩展/插件 Agent 名解析（与 bootstrap 内置集合并使用）。

---

## 20. 各 Agent 内部管线（逐 Agent）

### 20.1 RagAgent（`agents/rag_agent.py`）

```text
execute(task)
  → _normalize_query / _rewrite_query（中文问句清洗）
  → 并行：DocumentPlugin 向量检索 · LLMwiki · UserMemory（semantic/episodic）
  → Rerank（get_reranker）· DocumentEvidenceGate（min_score、anchor、answerable）
  → 不足则 web fallback（可选）
  → _make_evidence · ResultRef（doc_chunk、citation）
  → enrich_rag_evidence（services/rag_evidence_intelligence.py）
       → rank_evidence · detect_contradictions · evidence_graph · synthesis_preview
  → AgentResult(metadata.rag_evidence_intelligence=…)
```

**不生成最终自然语言答案**（由 Fusion/Kernel 生成）；输出 chunks、citations、quality 块。

### 20.2 WebAgent（`agents/web_agent.py`）

经 `ToolRouter` / `web_search` 工具；较薄封装；当 `web_intelligence` 未优先时由 `resolve_execution_agent` 解析到 `web`。

### 20.3 WebIntelligenceAgent（`agents/web_intelligence_agent.py`）

```text
CognitiveAgent.execute
  → execute_core:
       ToolRouter.execute_by_name("web_search", query)
       → 解析 JSON/items → rank_evidence
       → build_evidence_graph_from_items · synthesize_evidence_summary
       → content=Top5 标题/摘要 · metadata.evidence_graph
```

### 20.4 ToolAgent（`agents/tool_agent.py`）

规范化工具名与参数 → `tools/registry` / `execution/tool_router`；天气、时间等 fast path 可在 Kernel V5 层拦截。

### 20.5 DataAgent（`agents/data_agent.py`）

```text
execute(task)
  → data_agent_v2_enabled=false → DataAgentV1（kernel/data_cognition 管线）
  → data_agent_v2_enabled=true → DataAgentV2Supervisor.execute
       低置信 / 异常 → 可选 fallback V1
```

**DataAgentV1 管线**：

```text
SemanticParser → QueryPlanner → SQLBuilder → SQLValidator → SQLRanker/Reflector
  → QueryExecutor（DBRouter）
  → build_explanation · attach_data_intelligence_to_metadata
  → AgentResult + evidence(sql)
```

### 20.6 SkillsAgent / RuleEngineAgent / VisionAgent

- **Skills**（`agents/skills_agent.py`）：`skills/runtime` manifest，会话绑定技能执行。  
- **RuleEngine**（`agents/rule_engine_agent.py`）：灰度规则、`kernel_rule_grayscale_*`。  
- **Vision**（`agents/vision_agent.py`）：多模态 `LLMRole.VISION`（图表/附件解读）。

---

## 21. DataAgent V2 子 Agent 与 DAG

Supervisor：`agents/data_agent_v2/supervisor.py`（协调器，无业务逻辑；tier-2 经 `tier2_registry`）。

### 21.1 Supervisor 逐步走向

```text
_init_context → _load_datasource_metadata
  → [可选] KnowledgeRetrieverAgent（知识层）
  → 快路径：compiled_sql / pattern_hit → 跳过推理 DAG
  → build_cognitive_dag → DagScheduler 并行执行（L0…L4）
  → SQL 执行 → reflection / error_classifier 重试（max_retries）
  → Phase4：insight / statistical / visualization（开关）
  → data_critic · feedback_collector · knowledge_updater
  → 置信度熔断 → LowConfidenceError → V1 fallback
  → attach_data_intelligence_to_metadata · AgentResult
```

### 21.2 子 Agent 注册名（Tier-2 / `AGENT_REGISTRY`）

| key | 类 | 职责 |
|-----|-----|------|
| `data_knowledge` | KnowledgeRetrieverAgent | 知识层检索 |
| `data_intent` | IntentAgent | 查询意图 |
| `data_entity` | EntityAgent | 实体/link schema |
| `data_metric` | MetricAgent | 指标映射 |
| `data_time` | TimeReasoningAgent | 时间范围推理 |
| `data_join` | JoinAgent | 表连接启发式 |
| `data_semantic` | SemanticAgent | 语义层 |
| `data_planner` | PlannerAgent | 逻辑计划 |
| `data_compiler` | SQLCompilerAgent | SQL 生成 |
| `data_verification` | VerificationAgent | SQL/结果校验 |

Phase 扩展：`insight_agent`、`statistical_agent`、`visualization_agent`、`data_critic`、`reflection_agent`、`pattern_extractor`、`feedback_collector`、`knowledge_updater`、`error_classifier`、`metric_refiner`、`skills_engine`。

### 21.3 DAG 拓扑（`dag_builder.py`）

```text
L0 并行：Intent · Entity · Metric · Time · Join
    ↓
L1：Semantic
    ↓
L2：Planner → L3 SQLCompiler → L4 Verification
    ↓
SQL 执行 → 反思/重试 → Insight/Stat/Viz（开关）
    ↓
_build_final_result → attach_data_intelligence_to_metadata（成功与错误路径）
```

执行引擎：内核 `DagScheduler` / `execution/dag_engine` + `data_agent_v2_dag_parallel_enabled`。

### 21.4 子 Agent 内部要点（逐节点）

| Agent | 输入 | 输出写入 `CognitiveContext` |
|-------|------|-----------------------------|
| IntentAgent | query、schema 摘要 | `intent`（intent_type、metrics、filters） |
| EntityAgent | query、表元数据 | `entities`、`schema_links` |
| MetricAgent | intent、语义指标库 | `metric_mappings` |
| TimeReasoningAgent | query、默认时区 | `time_range` |
| JoinAgent | 实体、FK 图 | `join_hints` |
| SemanticAgent | L0 合并结果 | `semantic_plan` 片段 |
| PlannerAgent | semantic + knowledge | `logical_plan` |
| SQLCompilerAgent | logical_plan | `compiled_sql` |
| VerificationAgent | SQL、方言规则 | `verification_report` |
| KnowledgeRetrieverAgent | query | `knowledge_hits`、pattern |

各 `*_agent.py` 通过 `tier2_registry` 被 DAG 节点调用；失败经 `error_classifier` 决定是否重试 DAG 层。

---

## 22. 数据源、语义层与 Text2SQL

- API：`gateway/.../databases.py`、`data.py`、`table_relationships.py`
- Kernel：`kernel/data_cognition/*`（`semantic_layer`、`schema_linker`、`sql_builder`、`sql_ranker`、`sql_reflector`、`query_executor`…）
- 执行：`execution/data/database_hosts.py`、`db_router.py`（host 规则契约：`test_database_host_rules.py`）

---

## 23. RAG、证据图与 RAG V3 智能层

### 23.1 Evidence Graph（`services/evidence_graph/engine.py`）

`EvidenceGraph` 节点/边；`rank_evidence`、`detect_contradictions`、`build_evidence_graph_from_items`、`synthesize_evidence_summary`。

### 23.2 RAG V3（`services/rag_evidence_intelligence.py`）

`enrich_rag_evidence(chunks, query)` → ranked_chunks、chunk_graph、contradictions、fact_verification hint。

### 23.3 配置阈值

`RAG_MIN_EVIDENCE_SCORE`、`RAG_MIN_EVIDENCE_COUNT`（见 `test_config_truth_contract`）。

---

## 24. 记忆系统与 Memory Fabric

### 24.1 六层

Working、Episodic、Semantic、Procedural、Temporal、Evolution（`memory/*`）。

### 24.2 Fabric（`memory/fabric/`）

`retrieval.py`、`memory_graph.py`、`memory_graph_redis.py`、`relation_engine.py`、`episodic_bind.py`、`memory_compression.py`、`memory_evolution.py`、`salience_engine.py`、`tms_bridge.py`（TMS + 压缩计划）。

`kernel_memory_fabric_primary_only` 控制 Kernel 注入是否仅走 Fabric。  
`turn_outcomes` / fabric 节点 >64 → `memory_maintenance_plan`。

---

## 25. Capability OS、Control Plane 与执行路由

### 25.1 CapabilityRegistry（`kernel/runtime/capability.py`）

`register_agent`；`resolve_capability_type`；**`resolve_execution_agent`**（web → web_intelligence）；`validate_for_execution`。

### 25.2 Capability OS（`kernel/capability_runtime/capability_os.py`）

产品生命周期、`record_invocation`、SLA、`list_marketplace`。

### 25.3 dispatch_pipeline（`kernel/capability_runtime/dispatch_pipeline.py`）

`collect_planned_capability_types`、`collect_executed_capability_types`、`validate_planned_capabilities`、`record_capability_outcomes`（反馈环 + Prometheus SLA）、`resolve_root_goal_from_ctx`。

### 25.4 Enterprise Control Plane（`control_plane/control_plane.py`）

`EnterpriseControlPlane.evaluate_turn`：QuotaManager、ComplianceRuntime、Capability 生命周期、BillingManager。Gateway 预检：`control_plane/preflight.py`。

### 25.5 Capability Intelligence（`kernel/capability_intelligence/`）

Profiler、KG、reasoner、execution/strategy memory、evolution（Planner 能力画像输入）。

---

## 26. World Model、Redis 与 Shared World State

**`kernel/cognition/runtime_grounding.py`**：七切片 + `GoalModelSlice`；`persist_world_state` / `load_persisted_world_state`。

**`world/world_runtime.py`**：`build_shared_world_state(ctx)`。

**`world/world_state_redis.py`**：门面 `save_session_world_state`、`hydrate_session`。

**`kernel/agent_runtime/world_projection.py`**：Agent 贡献投影到 World 切片（V3 元数据）。

开关：`kernel_world_state_persist_enabled`。

---

## 27. 企业多租户、配额、计费与审计

| 模块 | 职责 |
|------|------|
| `tenant/tenant_context.py` | 六层上下文解析 |
| `tenant/tenant_manager.py` · `tenant_store.py` | 注册 + DB upsert（`tenants` 表） |
| `tenant/quota_manager.py` | 日 turn / 日 cost |
| `tenant/billing_manager.py` | 用量归因 |
| `tenant/usage_metering.py` | token 估价记录 |
| `tenant/policy_manager.py` | 合规框架、data_residency |
| `tenant/tenant_isolation.py` | `set_session_tenant_context`（RLS vars） |
| `tenant/workspace_manager.py` | 工作空间维度 |
| `kernel/governance/compliance_audit_store.py` | 审计事件内存 + DB |
| `observability/enterprise_telemetry.py` | 认知健康三层遥测 |
| `observability/prometheus_export.py` | `opentrace_enterprise_*` |

`ChatSession` ORM：`tenant_id`、`org_id`、`workspace_id`；`ensure_runtime_schema` + Alembic `20260606_enterprise_tenant`。

---

## 28. Policy Runtime 与变异点治理

**`kernel/governance/policy_runtime.py`**：`on_planning`、`on_evidence_fusion`、`on_memory_write`、`on_replay_load`。

**GovernanceCenter**（`governance_center.py`）：`evaluate_turn`、`evaluate_*_mutation`、semantic_metrics_pipeline、AdaptiveRiskEngine。

契约：`test_policy_runtime_contract.py`、`test_governance_single_source_contract.py`。

---

## 29. 工具、技能、插件与连接器

`tools/registry/`、`execution/tool_router/router.py`、`plugins/document_plugin.py`、`plugins/web_plugin.py`、`plugins/selector.py`、`skills/`、`connectors/`、`kernel/tools/registry.py`。

---

## 30. 规则引擎与灰度

`agents/rule_engine_agent.py`、`gateway/.../routers/rules.py`、`force_mode`（跳过 V5 / 锁定能力）。

---

## 31. 执行平面、DAG 与 Agent Bus

| 组件 | 路径 | 说明 |
|------|------|------|
| **ExecutionRuntime** | `kernel/runtime/executor.py` | vNext 主执行、子任务并行 |
| DAGEngine | `execution/dag_engine/` | DataAgent V2、`cognitive_nodes`、通用图 |
| Tool Router | `execution/tool_router/router.py` | web_search 等 |
| Workflow | `execution/workflow_engine/workflow.py` | 工作流（任务 API） |
| Agent Bus | `infra/message_bus/agent_bus.py` | stream / pubsub |

---

## 32. 模型网关、Token 计量与 Embedding / Rerank

**`model/model_gateway/gateway.py`**：`LLMRole` 多角色、CircuitBreaker、`complete` / `stream`、identity 后处理、**turn_metering 挂钩**。

**`model/embedding/base.py`**、**`model/reranker/base.py`**：RAG 检索与重排。

---

## 33. 治理体系（canonical kernel.governance）

唯一 Governor 实现：`kernel/governance/*.py`（`evidence_governor`、`risk_governor`、`memory_governor`、`prompt_governor`、`audit_governor`、`runtime_governor`、`capability_governor`…）。顶层 `governance/` 为 re-export + 兼容导入。

Semantic OS 八维：`reasoning_drift`、`goal_stability`、`capability_entropy`、`memory_pollution_risk`、`evidence_integrity`、`planner_volatility`、`runtime_recovery_score`、`cognitive_saturation`。

---

## 34. 安全、审计、沙箱与可解释性

JWT、`infra/security/zero_trust.py`、tool permission token、`governance/pii_detector.py`（预检）、`sandbox_runtime/`、`gateway/.../sandbox.py`、SQL 只读 + `data_source_id`。

---

## 35. 基础设施、配置、Flag 治理与环境 Profile

`infra/config/settings.py`、`flag_governance.py`、`flag_registry.py`、`orchestrator_label.py`。

Staging/production profile 强化：见 `docs/ENV_PROFILES.md`、`docs/CONFIG_TRUTH.md`、`test_config_truth_contract.py`。

Redis 逻辑 DB：10 session · 11 cache · 12 memory · 13 queue · 14 rate-limit · 15 pubsub。

---

## 36. 数据库模型与迁移

`infra/storage/models.py`：`User`、`ChatSession`（含租户列）、`TraceLog`、`Message`、`ConversationState`、`DataSource`…

`ensure_runtime_schema()`：chat_sessions 列 guard + `_ensure_enterprise_tenant_tables`。

Alembic：`alembic/versions/`（含 `20260606_enterprise_tenant_tables.py`）。

---

## 37. 部署、脚本与本地开发

```bash
cp .env.example .env && bash start-dev.sh   # 或 scripts/work/dev-boot-all-in-one.sh
curl http://127.0.0.1:14100/api/v1/health/cognitive-os
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
```

| 脚本 | 用途 |
|------|------|
| `start-dev.sh` / `stop-dev.sh` | 根目录快捷启停 |
| `scripts/work/backend-*.sh` | API / worker 分步 |
| `scripts/work/frontend-*.sh` | 前端 |
| `scripts/verify_e2e.sh` | E2E 冒烟 |
| `scripts/seed_dev_user.py` | 开发用户 |
| `scripts/report_v4_imports.sh` | V4 依赖审计 |

CI：`.github/workflows/ci-fast.yml`、**`.github/workflows/vnext-contract.yml`**（vNext + enterprise + import boundaries）。

---

## 38. 测试体系与发布门禁

### 38.1 合并建议

```bash
pip install -e ".[dev]"
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
bash scripts/check_import_boundaries.sh
lint-imports --config importlinter.ini
```

### 38.2 vNext 契约文件（`run_vnext_final_tests.sh`）

`test_vnext_architecture_contract`、`test_vnext_full_stack_contract`、`test_cognitive_supervisor_contract`、`test_runtime_cognitive_executive`、`test_goal_driven_dag_contract`、`test_capability_dispatch_pipeline`、`test_data_intelligence_runtime_v3_contract`、`test_agent_runtime_v3_contract` 等 **27** 文件。

### 38.3 企业契约文件（`run_enterprise_contract_tests.sh`）

`test_enterprise_control_plane_contract`、`test_multi_tenant_runtime_contract`、`test_chat_preflight_contract`、`test_capability_execution_routing_contract`、`test_turn_metering_contract`、`test_stream_enterprise_metadata_contract`、`test_data_agent_data_intelligence_contract` 等 **27** 文件。

全量：**1044** collected。

---

## 39. 架构治理文档矩阵

| 文档 | 用途 |
|------|------|
| `ARCHITECTURE_REQUIREMENTS_MATRIX.md` | 需求 ↔ 测试 |
| `ENTERPRISE_COGNITIVE_OS_GAP_ANALYSIS.md` | 企业差距与验收 |
| `CAPABILITY_MATURITY.md` | 能力成熟度 |
| `OBSERVABILITY_COGNITIVE_HEALTH.md` | 认知健康 |
| `FEATURE_FLAG_REGISTRY.md` | Flag 登记 |
| `RELEASE_GATE.md` | 发布门禁 |
| `adr/001-vnext-main-path.md` 等 | ADR |
| `runbooks/turn-trace.md`、`evidence-gate-failure.md` | 排障 |
| `catalog/*.md` | 子系统目录 |
| **本文** | Cursor 全量梳理 |

---

## 40. 开发规范与代码阅读顺序

1. 聊天必须 **CognitiveKernel**。  
2. 复杂路径仅 **RuntimeGateway**；Artifact 在 **run_outcomes**。  
3. Governor **仅** `kernel/governance`；kernel 内 import `kernel.governance.compliance_audit_store`。  
4. 新 Agent：更新 **manifest** + `bootstrap` + `capability_registry` + 契约测试。  
5. 回合结束：**`turn_outcomes`** + **`enterprise_outcomes`**。  
6. 企业预检：**`chat_preflight`**，勿在 session 创建后才发现配额耗尽。

### 推荐阅读（vNext + Enterprise）

1. `settings.py` · `chat_preflight.py` · `tenant_middleware.py`  
2. `chat.py` → `cognitive_kernel.py` → `runtime_gateway.py`  
3. `cognitive_supervisor/`（`control_plane_gate`、`enterprise_outcomes`）  
4. `runtime_turn_dispatcher.py` · `registry.py` · `cognitive_executive.py`  
5. `goal/turn_outcomes.py` · `services/data_intelligence_runtime/`  
6. `agents/bootstrap.py` · `agent_topology_manifest.yaml` · 各 Agent §20  
7. `control_plane/` · `tenant/` · `observability/enterprise_telemetry.py`  
8. `services/evidence_graph/` · `rag_evidence_intelligence.py`  

---

## 41. 已知风险、架构债与演进

| 项 | 说明 |
|----|------|
| V4 并存 | 默认 off；`report_v4_imports.sh` |
| 分布式 World Model | Redis + 单进程；多副本一致性 ⚠️ |
| RLS POLICY | 已有 `set_config`；表级 POLICY 未全开 |
| 计费 | 估价 + 内存；非发票系统 |
| DLP | PII 启发式 |
| RAG/Web 生产核验 | 证据图启发式；非 LLM 事实核验 |
| slim prepare_run | L0/L1 轻量 task 与完整 Goal 图行为差异需在复杂多轮场景验证 |

**目标态**：Enterprise Cognitive OS — Control Plane + Capability OS + Goal Portfolio + World State + Agent V3 证据链；工程完成度约 **9.2–9.4/10**（骨架），SaaS 运营 **7.5–8/10**。

---

## 42. SSE 与流式事件契约

| type | 含义 |
|------|------|
| `delta` | 增量文本（TurnDispatcher 分片） |
| `reasoning_step` | 推理步骤（含 stage、node_id、status） |
| `final_answer` | 终局（content、metadata、execution_graph、state_patch） |
| `error` | 治理/运行时/预检拒绝 |

流式 metadata 经 **`build_stream_final_metadata`** + **`enrich_turn_enterprise_metadata`**；`final_answer.data` 可提升字段：`control_plane`、`capabilities_used`、`prompt_tokens`、`enterprise_telemetry`、`agent_runtime_v3`、`data_intelligence`。

---

## 43. Kernel / Runtime / Goal / Enterprise 模块索引

### kernel/goal/

`state_machine`、`goal_lifecycle`、`goal_portfolio`、`turn_outcomes`、`multi_goal_*`、`goal_runtime_hooks`、`goal_evidence_binding`、`goal_memory_binding`、`goal_replay`。

### kernel/runtime/

`cognitive_executive`、`runtime_turn_dispatcher`、`registry`、`executor`、`multi_question_runtime`、`evidence_bus`、`fusion`、`cognitive_state/`、`artifact_composer`、`replay/`。

### kernel/agent_runtime/

`manifest.py`、`executor.py`、`tier2_registry.py`、`contribution.py`、`goal_participation.py`、`unified_evidence.py`、`stream_metadata.py`、`dag_invoke.py`。

### Enterprise

`control_plane/control_plane.py`、`control_plane/preflight.py`、`tenant/*`、`observability/enterprise_telemetry.py`、`gateway/.../chat_preflight.py`、`enterprise_admin.py`。

### services/

`data_intelligence_runtime/`、`evidence_graph/engine.py`、`rag_evidence_intelligence.py`。

---

## 44. 工程变更日志（2026-06 Enterprise 深化）

1. **Enterprise Control Plane**：预检、配额、合规、Capability 生命周期；Gateway `chat_preflight`。  
2. **多租户**：头注入、PolicyManager、`ChatSession` 租户列、RLS session vars。  
3. **Agent V3**：Manifest 3.0、`WebIntelligenceAgent`、`agent_runtime_executor`、`resolve_execution_agent`。  
4. **RAG V3**：`rag_evidence_intelligence` + `evidence_graph`。  
5. **Data Intelligence**：Tier-1 `data_intelligence` runtime + V1/V2 接线。  
6. **合规审计**：`compliance_audit_store` + admin API DB 读。  
7. **Token 计量**：`turn_metering` + ModelGateway。  
8. **World Redis**：`world_state_redis` + turn 结束 persist。  
9. **Memory**：`tms_bridge`、压缩计划。  
10. **Goal Portfolio**：Program→Task 元数据。  
11. **CI**：`vnext-contract.yml`。  
12. **本文档（2026-06-08）**：测试 1044、§6.5/6.6、§18.2、§21 Supervisor 逐步、附录 G/H。

---

## 45. 附录：与 service_claude 的差异

| 主题 | service_claude | service_cursor（本文） |
|------|----------------|---------------------------|
| 默认编排 | 常述 V4 为主 | **Supervisor + Registry + Tier-1** |
| 企业层 | 较少 | **Control Plane、租户、审计、遥测、预检** |
| Agent 内部 | 表格式简介 | **§20 逐步 + §21 DAG + 子节点表** |
| 流程 | 单链路 | **§6 同步/流式/执行/Data/拒绝分叉** |
| RAG/Web | 检索为主 | **证据图 + web_intelligence 路由** |
| 拓扑 | 无 manifest | **`agent_topology_manifest.yaml` §19** |
| 测试门禁 | 泛述 | **双脚本 27+27 文件、1044 全量** |

---

## 附录 A：CognitiveKernel.run 内部分支（细化）

```text
CognitiveKernel.run(request)
  │
  ├─ [可选] clarification 早退 → KernelResponse + pending_clarification
  ├─ classify_intent → IntentLock + CognitiveBudget → RuntimeContext
  ├─ direct_answer / 身份 / 能力问答（零 Executive）
  ├─ WorkingMemory 命中
  ├─ V5 routing（kernel_v5_routing_enabled）
  │     ├─ L0 query_router_v2 → 规则直答
  │     ├─ L0.5 semantic_cache → 向量缓存命中
  │     ├─ L1 tiny_router → 轻量 LLM 路由
  │     └─ tool_fast_path → 天气/时间等
  ├─ memory_injection（fabric + legacy router 受 primary_only 控制）
  ├─ SelfModel · ContextFabric.evolve（pre-dispatch）
  └─ RuntimeGateway.run(request)   # 复杂路径唯一出口
```

`stream()` 与 `run()` 在路由决策上对齐；流式在 Gateway 层产出事件而非一次性 `KernelResponse`。

---

## 附录 B：CognitiveExecutive 阶段与 Policy 钩子对照

| 阶段 | RuntimePhase（示意） | PolicyRuntime / GovernanceCenter |
|------|----------------------|----------------------------------|
| 理解 | UNDERSTAND | — |
| 规划 | PLAN | `on_planning` · `evaluate_planning_mutation` |
| 执行前 | PRE_EXECUTE | capability contract · registry_governance |
| 证据融合前 | PRE_FUSION | `on_evidence_fusion` |
| 融合后 / Critic | POST_FUSION | `evaluate_evidence_fusion_mutation` |
| 记忆写入 | MEMORY | `on_memory_write` |
| 完成 | COMPLETE | replay_contract 组装 |

`kernel_policy_mutation_fail_closed` 或 staging → `policy_denied` 提前返回 `CognitiveExecutiveResult`。

---

## 附录 C：import 边界与单实现治理（运维速查）

| 规则 | 脚本/测试 |
|------|-----------|
| `kernel/**` 不得 `from governance.` | `test_kernel_import_boundaries` |
| 顶层 `governance/*_governor.py` 不得定义 class | `test_governance_single_source_contract` |
| vNext 不得直接 import `legacy.v4` 编排实现 | `check_import_boundaries.sh` |
| `importlinter.ini` 分层 | `lint-imports` |

合规审计：**实现**在 `kernel/governance/compliance_audit_store.py`。

---

## 附录 D：DataAgent V2 文件清单（`agents/data_agent_v2/`）

| 文件 | 角色 |
|------|------|
| `supervisor.py` | 主编排、重试、熔断 V1 |
| `dag_builder.py` | DAG 拓扑与 `validate_dag_spec` |
| `types.py` | `CognitiveContext`、`LowConfidenceError` |
| `intent_agent.py` · `entity_agent.py` · `metric_agent.py` | L0 并行认知 |
| `time_reasoning_agent.py` · `join_agent.py` | 时间/连接 |
| `semantic_agent.py` · `planner_agent.py` | L1/L2 |
| `sql_compiler_agent.py` · `verification_agent.py` | L3/L4 |
| `knowledge_retriever.py` · `knowledge_updater.py` | 知识层 |
| `data_critic.py` · `reflection_agent.py` · `error_classifier.py` | 质量与修复 |
| `insight_agent.py` · `statistical_agent.py` · `visualization_agent.py` | Phase 4 分析 |
| `metric_refiner.py` · `pattern_extractor.py` · `feedback_collector.py` | 增强 |
| `skills_engine.py` | 分析技能 |

---

## 附录 E：Redis / 持久化 Key 约定（节选）

| Key 模式 | 用途 | 模块 |
|----------|------|------|
| `world_state:{session_id}` | World grounding JSON | `world_state_redis` |
| `opentrace:agent:stream:*` | Agent Bus | `agent_bus` |
| Memory graph shadow | 关系图副本 | `memory_graph_redis` |
| Cognitive state（可选） | phase 持久化 | `cognitive_state/persistence` |

---

## 附录 F：关键环境变量索引（`.env.example` 对照）

| 变量 | 含义 |
|------|------|
| `APP_PORT` / `GATEWAY_PORT` | API 端口（健康检查以 APP_PORT 为准） |
| `KERNEL_ORCHESTRATOR_V4_ENABLED` | false → vNext |
| `DATA_AGENT_V2_ENABLED` | DataAgent V2 主管线 |
| `KERNEL_AGENT_BUS_*` | Bus 模式、consumer、DLQ |
| `KERNEL_AGENT_RUNTIME_V3_ENABLED` | Goal 参与 + unified contribution |
| `KERNEL_MEMORY_FABRIC_*` | Fabric 检索与 Redis graph |
| `KERNEL_WORLD_STATE_PERSIST_ENABLED` | World Redis 写 |
| `KERNEL_WEB_INTELLIGENCE_PREFERRED` | web → web_intelligence |
| `DATABASE_URL` | PostgreSQL + pgvector |
| `REDIS_URL` | 多 DB 索引见 §35 |

---

## 附录 G：RuntimeTurnDispatcher.resolve_runtime_name 决策树

```text
strategy_projection.preferred_runtime
  ├─ "data_intelligence" → data_intelligence
  ├─ "multi_goal"        → multi_goal
  └─ else:
        goal_graph.goals.length > 2 → multi_goal
        else → cognitive_executive
```

`strategy_projection` 由 Supervisor `_inject_strategy_projection` 与 Goal/Intent 元数据共同影响；`data_intelligence` 常见于数据意图 + 策略层显式偏好。

---

## 附录 H：Agent Runtime V3 与 Tier 拓扑

```text
agent_topology_manifest.yaml (v3.0.0)
  tier0_kernel     → CognitiveKernel / Gateway / Supervisor
  tier1_executive  → cognitive_executive + rag/web/tool/web_intelligence 能力执行
  tier1_data       → data_intelligence runtime → DataAgent(V2)
  tier2_nodes      → data_agent_v2/*_agent（仅 DAG 内部，不直接 dispatch_runtime）

agent_runtime_executor.execute_task
  → goal_participation（goal_id、trace_id）
  → contribution → unified_evidence / stream_metadata 合并
  → record_capability_outcomes（与 dispatch_pipeline 闭环）
```

契约：`test_agent_runtime_v3_contract.py`、`test_capability_execution_routing_contract.py`。

---

*文档维护：随 `tests/` 契约与 `settings.py` 变更同步更新；争议以源码为准。*