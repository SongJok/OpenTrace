# OpenTrace 项目全量梳理（Cursor 版 · Enterprise Cognitive OS）

> **事实来源**：仅以当前仓库源码、`infra/config/settings.py`、`.env.example`、`docker-compose.yml`、`importlinter.ini`、启动/验证脚本与 `tests/` 契约为准。  
> **格式基线**：在 `docs/service/service_claude.md` 目录深度上扩展；本文是 **维护用 SSOT 索引**，覆盖 **端到端流程、Tier 拓扑、每个 Agent 的触发条件与内部管线、企业控制面、SSE/前端契约、配置与门禁、问答一致性防控**。  
> **最后更新**：2026-06-22（全量覆写：ContextAssembler 当前轮记忆注入 · 认知控制 relevance · Fusion 输出门控 · Data V2 全节点 · 测试基线 **1255** collected）  
> **需求矩阵**：`docs/ARCHITECTURE_REQUIREMENTS_MATRIX.md`（#1–#30）。  
> **架构定义**：**Runtime-First Cognitive Architecture** — Agent 为 Capability Provider；Goal / Evidence / Memory / World 经 **RuntimeContribution** + **CognitiveStateGraph** 统一演化（**bus 单写** + Redis 可选）。  
> **测试规模**：`PYTHONPATH=. pytest tests/ --collect-only -q` → **1255** tests；vNext 门禁套件 `scripts/run_vnext_final_tests.sh` → **371** passed（2026-06-22 实测）。  
> **Alembic head（当前）**：**`20260613_documents_tenant_workspace`**（`documents.tenant_id` + `workspace_id`）。  
> **Turn Envelope SSOT**：`docs/architecture/turn_envelope_field_mapping.md` + `frontend/src/utils/streamEnvelope.ts`。  
> **生产主路径**：`CognitiveKernel` → **`RuntimeGateway`**（Tier0 / Tool 快路径）→ `CognitiveSupervisor.prepare_run` → `RuntimeTurnDispatcher` → `registry` → `cognitive_executive` | `data_intelligence` | `multi_goal` → `run_outcomes` → `turn_outcomes` / `enterprise_outcomes` / `finalize_turn`。

---

## 目录

1. [项目定位与产品边界](#1-项目定位与产品边界)
2. [当前代码状态摘要](#2-当前代码状态摘要)
3. [技术栈与依赖](#3-技术栈与依赖)
4. [整体架构与六域模型](#4-整体架构与六域模型)
5. [vNext 主路径（强制遵守）](#5-vnext-主路径强制遵守)
6. [端到端流程走向总图](#6-端到端流程走向总图)
7. [斜杠命令与 force_mode 全链路](#7-斜杠命令与-force_mode-全链路)
8. [目录结构与模块地图](#8-目录结构与模块地图)
9. [前端应用](#9-前端应用)
10. [API 网关与路由清单](#10-api-网关与路由清单)
11. [聊天主链路（同步 / SSE / 企业预检 / Tier0）](#11-聊天主链路同步--sse--企业预检--tier0)
12. [认知内核、V5 路由与认知控制](#12-认知内核v5-路由与认知控制)
13. [身份与人设（System Identity）](#13-身份与人设system-identity)
14. [V4 编排器（遗留、默认禁用）](#14-v4-编排器遗留默认禁用)
15. [RuntimeGateway、Supervisor 与 TurnDispatcher](#15-runtimegatewaysupervisor-与-turndispatcher)
16. [Cognitive Runtime V2（Executive 管线）](#16-cognitive-runtime-v2executive-管线)
17. [Goal 生命周期、多目标与 turn_outcomes](#17-goal-生命周期多目标与-turn_outcomes)
18. [认知规划门面与多问题运行时](#18-认知规划门面与多问题运行时)
19. [Runtime Registry、Tier-1 与 Data Intelligence](#19-runtime-registrytier-1-与-data-intelligence)
20. [Agent 集群总览、Manifest 与 Worker](#20-agent-集群总览manifest-与-worker)
21. [Agent 调用决策矩阵（何时用哪个 Agent）](#21-agent-调用决策矩阵何时用哪个-agent)
22. [各 Agent 内部管线（逐 Agent）](#22-各-agent-内部管线逐-agent)
23. [DataAgent V2 子 Agent 与 DAG](#23-dataagent-v2-子-agent-与-dag)
24. [数据源、语义层与 Text2SQL](#24-数据源语义层与-text2sql)
25. [RAG、证据图与 RAG 智能层](#25-rag证据图与-rag-智能层)
26. [记忆系统与 Memory Fabric](#26-记忆系统与-memory-fabric)
27. [Capability OS、Control Plane 与执行路由](#27-capability-oscontrol-plane-与执行路由)
28. [World Model、Redis 与 Shared World State](#28-world-modelredis-与-shared-world-state)
29. [企业多租户、配额、计费与审计](#29-企业多租户配额计费与审计)
30. [Policy Runtime 与变异点治理](#30-policy-runtime-与变异点治理)
31. [工具、技能、插件与连接器](#31-工具技能插件与连接器)
32. [规则引擎与灰度](#32-规则引擎与灰度)
33. [执行平面、DAG 与 Agent Bus](#33-执行平面dag-与-agent-bus)
34. [模型网关、Token 计量与 Embedding / Rerank](#34-模型网关token-计量与-embedding--rerank)
35. [治理体系（canonical kernel.governance）](#35-治理体系canonical-kernelgovernance)
36. [安全、审计、沙箱与可解释性](#36-安全审计沙箱与可解释性)
37. [基础设施、配置、Flag 治理与环境 Profile](#37-基础设施配置flag-治理与环境-profile)
38. [数据库模型与迁移](#38-数据库模型与迁移)
39. [部署、脚本与本地开发](#39-部署脚本与本地开发)
40. [测试体系与发布门禁](#40-测试体系与发布门禁)
41. [架构治理文档矩阵](#41-架构治理文档矩阵)
42. [开发规范与代码阅读顺序](#42-开发规范与代码阅读顺序)
43. [已知风险、架构债与演进](#43-已知风险架构债与演进)
44. [SSE 与流式事件契约](#44-sse-与流式事件契约)
45. [Kernel / Runtime / Goal / Enterprise 模块索引](#45-kernel--runtime--goal--enterprise-模块索引)
46. [工程变更日志](#46-工程变更日志)
47. [Runtime-First 统一运行时（Contribution / StateGraph）](#47-runtime-first-统一运行时contribution--stategraph)
48. [计费、账本与 Alembic 企业表](#48-计费账本与-alembic-企业表)
49. [Turn Envelope 字段映射详表](#49-turn-envelope-字段映射详表)
50. [需求矩阵、成熟度与 P0–P2 认知平台](#50-需求矩阵成熟度与-p0p2-认知平台)
51. [与 service_claude 的差异](#51-附录与-service_claudemd-的差异)
52. [问答一致性与答非所问防控](#52-问答一致性与答非所问防控)

**附录**：A [CognitiveKernel 分支](#附录-a-cognitivekernelrun-内部分支) · B [Executive × Policy](#附录-b-cognitiveexecutive-阶段与-policy) · C [import 边界](#附录-c-import-边界) · D [DataAgent V2 文件清单](#附录-d-dataagent-v2-文件清单) · E [Redis Key](#附录-e-redis-key-节选) · F [环境变量](#附录-f-关键环境变量) · G [resolve_runtime_name](#附录-g-resolveruntime_name) · H [Agent Runtime V3](#附录-h-agent-runtime-v3) · I [RuntimeGateway API](#附录-i-runtimegateway-api) · J [Manifest 校验](#附录-j-manifest-校验) · K [Gateway Router 全表](#附录-k-gateway-router-全表) · L [场景速查（用户说什么 → 走哪条链）](#附录-l-场景速查用户说什么--走哪条链)

---

## 1. 项目定位与产品边界

OpenTrace 是以 **Cognitive Kernel** 为唯一聊天中枢的 **AgentOS / Enterprise Cognitive OS**：对话、RAG、工具、联网、数据分析、记忆、任务、审计、技能市场、连接器、附件、多租户与运行时观测一体化，Docker 可部署，配套 React 管理端。

| 能力域 | 代码锚点 | 对外表现 |
|--------|----------|----------|
| 统一认知入口 | `kernel/cognitive_kernel.py` | 所有 `/api/v1/chat` 经 `CognitiveKernel.run/stream` |
| 快路径统一入口 | `kernel/runtime_gateway.py` | Tier0 数据/SQL、Tool 天气时间 |
| 意图与预算 | `kernel/cognitive_controls.py` | Intent Lock、CognitiveBudget、relevance 锚点 |
| 分层路由 | `query_router_v2.py`、`kernel/routing/v5_facade.py`、`semantic_cache`、`tiny_router` | L0 / L0.5 / L1 |
| vNext 编排 | `RuntimeGateway` + `CognitiveSupervisor` + `RuntimeTurnDispatcher` | Goal、治理、证据、Artifact |
| 企业控制面 | `control_plane/`、`tenant/`、`chat_preflight.py` | 预检、配额、PII、租户头 |
| Goal-centric | `kernel/goal/*` | 状态机、回合收尾、Portfolio |
| Policy | `kernel/governance/policy_runtime.py` | plan / evidence / memory 变异点 |
| World | `runtime_grounding`、`world/` | 七切片 + Redis 可选 |
| 数据智能 | `agents/data_agent_v2/` + `services/data_intelligence_runtime` | Text2SQL、澄清、evidence_objects |
| RAG | `agents/rag_agent.py` + `services/rag_evidence_intelligence.py` | 混合检索、证据图、answerable 门控 |
| 联网 | `agents/web_intelligence_agent.py` | 搜索 → rank → evidence graph → coverage |
| 记忆 | `memory/*` + `memory/fabric/` | 六层 + TMS bridge |
| 拓扑契约 | `kernel/agent_runtime/agent_topology_manifest.yaml` | bootstrap / worker / bus SSOT |
| 前端协议 | `frontend/src/utils/streamEnvelope.ts` | `final_answer` → `TurnMetaEnvelope` |

**非目标（当前仓库）**：

- 前端默认不在 `docker-compose` 核心栈，需本地 `npm run dev`（端口常 **14108**，`VITE_API_URL` → **14100**）。
- 多副本 World / CognitiveStateGraph 强一致仍为架构债。
- Postgres 全表 RLS 需独立 migration 与 runbook（`docs/runbooks/tenant-rls-staging.md`）。
- 计费为 token 估价 + ledger 草稿，非税务级发票。
- 文档**不**写入 `.env` 真实密钥。
- CI **不**默认跑全量真 LLM E2E；语义级「答非所问」需 staging 人工或 nightly。

---

## 2. 当前代码状态摘要

| 维度 | 状态（2026-06-22） |
|------|---------------------|
| API | FastAPI，`APP_PORT` 默认 **14100**（`GATEWAY_PORT` 可能为 14101，健康检查以 APP_PORT 为准） |
| 主聊天 | `POST /api/v1/chat`（同步 + SSE） |
| 编排 | **vNext**；`kernel_orchestrator_v4_enabled=false` |
| Tier0 SSOT | `kernel/runtime/tier0_paths.py` + gateway 薄 re-export |
| Tool 快路径 | `kernel/fast_tool_path.py` → `RuntimeGateway` |
| DataAgent | V2 默认；澄清 + `turn_metadata` + V3 evidence |
| Web | **`web_intelligence` 单轨**（manifest **3.1.0**） |
| Manifest | **3.1.0** — bootstrap: data, rag, web_intelligence, tool, vision, skills, rules |
| Alembic head | **`20260613_documents_tenant_workspace`** |
| V5 门面 | `kernel/routing/v5_facade.py`（非身份问句禁止返回 canonical 身份文案） |
| RAG 门控 | `answerable` + `relevance_score` / `_substantive_query_terms` + 检索强信号 OR |
| 身份 | `enforce_identity_output` + `finalize_assistant_content` + working_memory 缓存 |
| 记忆注入 query | **`ContextAssembler` 使用当前轮 `tctx.query`**（防 RAG/记忆串轮） |
| 契约测试 | **1255** collected；`run_vnext_final_tests.sh` **371** |

### vNext / Enterprise 默认（摘录，详见 `infra/config/settings.py`）

```text
kernel_goal_driven_dag_enabled=true
kernel_orchestrator_v4_enabled=false
data_agent_v2_enabled=true
data_agent_business_semantic_enabled=true
kernel_web_intelligence_preferred=true
kernel_v5_routing_enabled=true
kernel_l0_rule_router_enabled=true
kernel_goal_supervisor_enabled=true
kernel_cognitive_iteration_enabled=true
kernel_agent_runtime_v3_enabled=true
kernel_memory_fabric_retrieval_enabled=true
enterprise_quota_redis_enabled=false   # staging 推荐 true
```

### Staging / Production 自动强化（`app_env` ∈ {staging, production}）

| 开关 | 行为 |
|------|------|
| `kernel_memory_fabric_primary_only` | 强制 true |
| `kernel_cognitive_state_persist_enabled` | 强制 true |
| `kernel_world_state_persist_enabled` | 强制 true |
| `kernel_agent_runtime_v3_strict` | 强制 true |
| `kernel_unified_evidence_strict` | 强制 true |
| `kernel_policy_mutation_fail_closed` | 强制 true |

---

## 3. 技术栈与依赖

### 3.1 后端

Python **3.11+**（CI/dev 可见 3.13）、FastAPI、SQLAlchemy 2.0 asyncio、asyncpg、Alembic、pgvector、Redis、OpenAI-compatible LLM（`LLMRole`）、sqlglot、pydantic-settings、OTel、prometheus-client、import-linter。

### 3.2 前端

React 18、TypeScript、Vite、Zustand、react-router-dom、Tailwind、Vitest（`**/*.contract.test.ts(x)`）。

### 3.3 Docker Compose（典型）

`api` :14100、`agent-worker`、`postgres`（pgvector）、`redis`、可选 `prometheus` / `jaeger`。见根目录 `docker-compose.yml`、`deploy/docker/Dockerfile`。

### 3.4 仓库顶层包（除 kernel/agents 外仍活跃）

| 包 | 用途 |
|----|------|
| `gateway/api_gateway/` | 对外 REST + SSE |
| `services/` | RAG 智能、evidence_graph、data_intelligence_runtime |
| `execution/` | DAG engine、db_router、tool_router、sql_executor |
| `plugins/` | document、web、chart、code、file |
| `skills/`、`connectors/`、`sandbox_runtime/` | 技能市场、连接器、沙箱 |
| `legacy/v4/` | V4 orchestrator 隔离 |
| `agent_runtime/`（根） | 旧 agent_runtime 市场/executor（与 `kernel/agent_runtime` 区分） |

---

## 4. 整体架构与六域模型

| 域 | 职责 | 目录 |
|----|------|------|
| Cognitive | 规划、理解、多问题、World | `kernel/cognition/` |
| Strategy | 能力链、预算 | `kernel/strategy/`、`capability_runtime/` |
| Runtime | Executive、证据、融合、Tier0 | `kernel/runtime/` |
| Protocol | 稳定契约 | `kernel/protocol/` |
| Governance | Policy、合规、semantic metrics | **`kernel/governance/`** |
| Goal | 目标生命周期 | `kernel/goal/` |
| Enterprise | 租户、配额 | `tenant/`、`control_plane/` |
| Agent Runtime | Manifest、V3 证据 | `kernel/agent_runtime/` |

```text
Frontend :14108
    │ HTTP/SSE + Authorization + X-Tenant-Id / X-Org-Id / X-Workspace-Id
    ▼
gateway/api_gateway/main.py
    │ TenantContextMiddleware · request_id · CORS
    │ chat_preflight · tenant session vars · reset_turn_tokens
    ▼
CognitiveKernel.run / stream
    │ classify_intent · identity cache · tool_fast_path · V5Facade
    ▼
RuntimeGateway → CognitiveSupervisor.prepare_run → RuntimeTurnDispatcher
    ▼
Tier-1 runtimes + Tier-1 Agents (in-process / Redis Agent Bus)
    ▼
run_outcomes · goal/turn_outcomes · enterprise_outcomes · finalize_turn
```

---

## 5. vNext 主路径（强制遵守）

```text
CognitiveKernel.run / stream
  → [可选] RuntimeGateway.try_tool_fast_path / try_tier0_chat（HTTP 层亦可 Tier0 早退）
  → bootstrap_turn_intent · multi_turn_resolution
  → CognitiveSupervisor.prepare_run
      → control_plane / policy / runtime_governor
      → goal bind · world hydrate · dispatch_enrichment
  → RuntimeGateway.run / stream
  → RuntimeTurnDispatcher.dispatch_runtime
  → cognitive_executive | data_intelligence | multi_goal
  → run_outcomes → executive_result_to_kernel_response
  → enrich_turn_enterprise_metadata
  → post_turn_enterprise_accounting (finalize_turn)
```

| 禁止 | 校验 |
|------|------|
| Gateway 内跑完整 Planner/Executive 逻辑 | importlinter |
| vNext 路径 import `legacy.v4` 实现 | `check_import_boundaries.sh` |
| `kernel/**` → `from governance.*`（顶层包） | `test_kernel_import_boundaries` |
| Tier0 业务仅散落 gateway | `kernel/runtime/tier0_paths.py` SSOT |

```bash
bash scripts/run_vnext_final_tests.sh
bash scripts/run_enterprise_contract_tests.sh
bash scripts/check_import_boundaries.sh
```

---

## 6. 端到端流程走向总图

### 6.1 同步聊天

```text
POST /api/v1/chat (stream=false)
  ├─ build_tenant_metadata · run_chat_preflight
  ├─ reset_turn_tokens · _ensure_session · set_session_tenant_context
  ├─ [HTTP] RuntimeGateway.try_tier0_chat → 早退 ChatResponse
  ├─ bootstrap_turn_intent(kernel_request)
  ├─ CognitiveKernel.run
  │     ├─ multi_turn_resolution（intent 前）
  │     ├─ classify_intent → IntentLock
  │     ├─ direct_answer / identity（无 force_mode）
  │     ├─ should_use_tool_fast_path → RuntimeGateway.try_tool_fast_path
  │     ├─ V5RoutingFacade.try_fast_path（L0/cache/L1）
  │     └─ RuntimeGateway.run → dispatcher → handler
  ├─ run_outcomes · turn_outcomes · enrich_turn_enterprise_metadata
  └─ post_turn_enterprise_accounting
```

### 6.2 流式 SSE

```text
POST /api/v1/chat (stream=true)
  → 预检与会话
  → try_tier0_chat → stream_tier0_events
  → CognitiveKernel.stream → RuntimeGateway.stream
  → delta | reasoning_step | dag_* | final_answer | error
  → 前端 normalizeFinalAnswerEnvelope → turn_meta
```

### 6.3 Turn bootstrap / enrichment / finalize（横切）

| 阶段 | 模块 | 产出 |
|------|------|------|
| Gateway / Kernel | `turn_bootstrap.py` | `intent_lock`、`dispatch_query`、world hydrate 种子 |
| Supervisor 前 | `turn_enrichment.py` | `enrich_turn_before_dispatch`、RAG/Data params 含 tenant |
| Dispatcher | `runtime_turn_dispatcher.py` | registry 解析、lifecycle、stream metadata |
| 回合末 | `finalize_turn.py` | billing、quota、learning_hook、world finalize |
| 语义闭环 | `finalize_semantic_and_evolution.py` | kernel turn health + evolution（与 Executive 去重） |

契约：`test_turn_bootstrap_contract`、`test_turn_enrichment_contract`、`test_finalize_turn_contract`。

### 6.4 Data 路径分叉

```text
force_database + data_source_id
  → try_tier0_chat（tier0_data_query）或 gateway/routers/data.py
否则
  → preferred_runtime=data_intelligence 或 Executive 内 data 子任务
DataAgent → DataAgentV2Supervisor（clarification_gate 可短路 DAG）
  → services/data_intelligence_runtime 包装 V3 evidence + GoalRuntimeHooks
```

### 6.5 Supervisor 拒绝早退

`control_plane_denied` | `runtime_policy_denied` | `runtime_governance_denied` → 短路 `KernelResponse` / SSE `error`（不经 Executive）。

### 6.6 Registry 治理拒绝

`registry_dispatch_denied` + `metadata.registry_dispatch_gate`（violations、capability_ranking）。模块：`kernel/runtime/registry_governance.py`。

### 6.7 Data V2 熔断侧链

```text
Supervisor 低置信 + data_agent_v2_fallback_to_v1
  → record_data_v2_circuit_breaker（failure_memory）
  → LowConfidenceError → DataAgent V1.execute
```

### 6.8 能力执行（Executive 内子任务）

```text
ExecutionPlan.subtasks[]
  → kernel/runtime/executor.py
  → capability_registry.resolve_execution_agent(agent_type)
  → [V3] agent_runtime/executor.execute_task → UnifiedEvidence → EvidenceBus
  → dispatch_pipeline.attach_goal_participation → RuntimeContribution → CognitiveStateGraph
  → record_capability_outcomes → metadata.capabilities_used
```

### 6.9 Fusion 与 Critic（Executive 末段）

```text
agent_results → evidence_bus → kernel/runtime/fusion.py
  → relevance / format hints（cognitive_controls）
  → kernel/critic_engine 或 runtime/critic.py
  → finalize_assistant_content（identity）
  → CognitiveExecutiveResult
```

契约：`test_rag_fusion_output_contract`、`test_fusion_critic_flags_contract`。

---

## 7. 斜杠命令与 force_mode 全链路

用户输入 **`/rag 什么是队长`** 时的 canonical 路径：

```text
ChatInput / API body（可选显式 force_mode）
  ▼
L0RuleRouter（query_router_v2.py）
  正则 ^/(rag|data|web|tool|…) (.+)
  → L0RouteResult(route=force_mode, force_mode=rag, answer=剥离前缀后的 query)
  ▼
Gateway chat.py → metadata.force_mode
  ▼
CognitiveKernel → force_mode 存在：跳过 V5 复杂路由（v5_facade.should_skip_v5）
  ▼
RuntimeGateway → Executive 或 dedicated runtime
  → resolve_execution_agent("rag") → RagAgent.execute(TaskMessage)
  ▼
Fusion / LLM 生成最终自然语言（RagAgent 主产出为 evidence）
```

**斜杠别名映射**（`_SLASH_FORCE_MODE`）：

| 命令 | force_mode |
|------|------------|
| `/rag` | `rag` |
| `/data` | `data_query` |
| `/web` | `web` |
| `/tool` `/tools` | `tool` |
| `/skills` | `skills` |
| `/vision` | `vision` |
| `/anomaly` | `anomaly_tracking` |
| `/rule` | `rule_engine` |

**L0 额外**：天气/时间正则 → `force_mode=tool`（避免误走 RAG）。

契约：`test_force_mode_routing.py`、`test_force_mode_multi_turn_contract.py`。

---

## 8. 目录结构与模块地图

```text
opentrace/
├── gateway/api_gateway/          # FastAPI main、chat、documents、enterprise_admin
├── kernel/
│   ├── cognitive_kernel.py       # 唯一 run/stream 入口
│   ├── runtime_gateway.py        # Tier0 + Tool + run/stream 委托
│   ├── fast_tool_path.py · query_router_v2.py · routing/v5_facade.py
│   ├── cognitive_controls.py     # Intent Lock、relevance、direct_answer
│   ├── context_assembler.py      # 结构化上下文；memory_injection_query=当前轮
│   ├── turn_bootstrap.py · turn_enrichment.py · multi_turn_resolution.py
│   ├── cognitive_supervisor/     # prepare_run、run_outcomes、dispatch_enrichment
│   ├── runtime/                  # executive、dispatcher、registry、fusion、finalize_turn
│   ├── goal/ · governance/ · cognition/
│   ├── identity/                 # system_identity
│   └── agent_runtime/            # manifest 3.1.0、executor、unified_evidence
├── agents/                       # Tier-1 + data_agent_v2/
├── services/                     # data_intelligence_runtime、rag_evidence_intelligence
├── memory/ · world/ · tenant/ · control_plane/
├── execution/                    # dag_engine、tool_router、db_router
├── plugins/ · model/ · infra/
├── frontend/src/                 # Chat、streamEnvelope、pages
├── legacy/v4/                    # 默认关闭
├── tests/                        # 1255+ 契约
├── docs/ · scripts/ · alembic/
```

### 8.1 `kernel/runtime/` 子树（执行面 SSOT）

| 子目录/文件 | 职责 |
|-------------|------|
| `cognitive_executive.py` | 主 Executive 状态机 |
| `runtime_turn_dispatcher.py` | lookup + stream + registry |
| `registry.py` · `registry_governance.py` | runtime 名 → handler |
| `executor.py` | 子任务 → Agent |
| `fusion.py` | 多源证据合成答 |
| `evidence_runtime.py` · `evidence_bus.py` | 回合证据合并 |
| `cognitive_state/` | store、bus、graph、persistence |
| `cognitive/` | planner v2、execution_projection、strategy_builder |
| `tier0_paths.py` | SQL 检索 / force DB |
| `finalize_turn.py` · `resume_turn.py` | 计费与世界收尾 |
| `multi_question_runtime.py` | 多问题卡片运行时 |
| `replay/` | 确定性回放 |

---

## 9. 前端应用

- **入口**：`frontend/src/main.tsx` → `App.tsx`（react-router）
- **API**：`frontend/src/api/client.ts`（SSE、`onFinalAnswer`、租户头）
- **状态**：`store/chat.ts`、`store/auth.ts`、`store/theme.ts`

| 页面 | 路径 | 职责 |
|------|------|------|
| ChatPage | `/` | 主对话、流式、TurnMeta、DAG 时间线 |
| DocumentsPage | `/documents` | 文档上传与 RAG 源 |
| DatabasesPage | `/databases` | 数据源、同步 schema |
| SkillsPage / RulesPage | `/skills` `/rules` | 技能与规则 |
| MemoryPage | `/memory` | 用户记忆 |
| TasksPage / AuditPage | `/tasks` `/audit` | 任务与审计 |
| SettingsPage / IntegrationsPage | | 配置与连接器 |
| LoginPage / RegisterPage | | JWT 认证 |

**聊天组件**：`ChatInput`（斜杠提示）、`ChatMessage`、`MarkdownMessage`、`DataQueryResult`、`ExecutionGraphPanel`、`DagTimeline`、`MultiQuestionCards`、`DecisionTraceCard`。

| 环节 | 行为 |
|------|------|
| SSE `final_answer` | `normalizeFinalAnswerEnvelope` → `setLastAssistantTurnMeta` |
| 历史消息 | `MessageOut.metadata` → `turn_meta` |
| 契约测试 | 17 文件 / 31 tests（Vitest `--run`） |

---

## 10. API 网关与路由清单

- **应用**：`gateway/api_gateway/main.py`（FastAPI 0.1.0）
- **启动**：`register_builtin_agents()`、`ensure_runtime_schema()`、`memory_event_subscriber`
- **中间件**：CORS、`TenantContextMiddleware`、`x-request-id` / `x-response-time-ms`
- **错误**：`AppException` → 统一 JSON envelope（`infra/errors`）

健康：`GET /health`、`/health/deps`、**`/health/cognitive-os`**（认知栈自检）。

详见 **附录 K**。

---

## 11. 聊天主链路（同步 / SSE / 企业预检 / Tier0）

### 11.1 预检（`chat_preflight.py` + `control_plane/preflight.py`）

PII 检测 → `EnterpriseControlPlane.evaluate_turn` → 拒绝则 `AppException`（chat 路由捕获）。

### 11.2 Tier0（`kernel/runtime/tier0_paths.py`）

| 路径 | 触发 |
|------|------|
| `sql_retrieval` | SQL 检索意图 + TraceLog |
| `tier0_data_query` | `force_database` + `data_source_id` |

HTTP：**`RuntimeGateway.try_tier0_chat`** 可短路全量 Supervisor。

### 11.3 会话与 metadata

```text
ConversationStateManager / conversation_state.py
  → RuntimeContext.to_metadata_dict()
  → tenant_id / org_id / workspace_id
  → bootstrap_turn_intent → dispatch_query SSOT
  → ContextAssembler.assemble(TurnContext) → memory_injection_query = 当前 query
```

### 11.4 横切钩子

| 模块 | 作用 |
|------|------|
| `preference_injection.py` | 用户偏好块 |
| `multi_turn_resolution.py` | DST + ReferenceResolver |
| `world_turn_begin` / `world_turn_finalize` | World hydrate / publish |
| `clarification_enrichment.py` | 澄清回合 enrich |

---

## 12. 认知内核、V5 路由与认知控制

### 12.1 CognitiveKernel（`cognitive_kernel.py`）

- `run` / `stream`：复杂路径 `get_runtime_gateway().run/stream`
- V4：`kernel_orchestrator_v4_enabled=true` → `legacy/v4` shim
- 身份：working_memory 缓存命中 → `route=working_memory`，不调 orchestrator
- 附件：`has_attachments` 影响 V5 / vision 路由

### 12.2 V5 层级

| 层 | 模块 | 说明 |
|----|------|------|
| L0 | `L0RuleRouter` | 斜杠、身份、FAQ、天气/时间→tool |
| L0.5 | `semantic_cache.py` | 向量缓存 |
| L1 | `tiny_router.py` + `complexity_engine.py` | 轻量 pipeline |
| 门面 | `routing/v5_facade.py` | `_v5_answer_allowed`：非身份问句禁止 canonical 身份答 |

### 12.3 Intent Lock（`cognitive_controls.py`）

`classify_intent()` → `IntentLock`：

- `task_type`：`general_qa` | `document_qa` | `data_query` | `capability_help` | …
- `allowed_capabilities` / `disallowed_capabilities`
- `CognitiveBudget`：`memory_injection`、`max_capabilities`、`complexity_level`
- `direct_answer_for_intent`：能力帮助等零 Executive
- `should_use_tool_fast_path`：天气/时间
- `relevance_score` / `passes_relevance_anchor` / `_substantive_query_terms`：RAG/Fusion 锚定
- `_strip_rag_routing_query`：去掉「根据知识库…」路由套话再算相关度
- `detect_response_format_hint`：如 `one_sentence`
- `_detect_follow_up` + `prior_intent`：防止 follow-up 误继承 data_query（例：「我饿了」）

契约：`tests/test_cognitive_controls_contract.py`。

### 12.4 ContextAssembler（`context_assembler.py`）

V5 链路组件：历史 / 记忆 / 附件 / conversation_state → `AssembledContext`。

**关键**：`memory_injection_query` **必须**为 `tctx.query`（或 `metadata.raw_user_query`），**不得**用 history 最后一条 user（否则 RAG/记忆检索串到上一轮 → 答非所问）。

契约：`test_v5_routing_contract.py::test_memory_injection_query_uses_current_turn_query`。

### 12.5 横切模块索引

| 模块 | 职责 |
|------|------|
| `clarification_gate.py` | 通用 + Data V2 澄清 |
| `context_fabric*.py` | 会话上下文图 |
| `memory_injection.py` | Fabric 优先注入 |
| `planner_facade.py` | Goal → Strategic → Execution → Projection |
| `dialogue_state_tracker.py` · `reference_resolver.py` | 多轮 |
| `history_retriever.py` | Tier0 SQL 历史 |

---

## 13. 身份与人设（System Identity）

| API | 职责 |
|-----|------|
| `system_identity.py` | `CANONICAL_IDENTITY_RESPONSE`、`merge_system_identity` |
| | `is_identity_user_query`、`enforce_identity_output` |
| | 非身份问题：剥离「我是 OpenTrace…」开场 blurb |
| | 禁止自称 Qwen/ChatGPT 等 |
| `model_gateway/gateway.py` | `_post_process_identity_response` |
| `working_memory` | 会话级 identity 缓存 |

契约：`tests/test_identity_guard.py`。

---

## 14. V4 编排器（遗留、默认禁用）

`legacy/v4/orchestrator.py`；`kernel/orchestrator_v4.py` 仅 re-export。  
门禁：`test_v6_v4_import_gate_contract.py`、`scripts/report_v4_imports.sh`。

---

## 15. RuntimeGateway、Supervisor 与 TurnDispatcher

### 15.1 RuntimeGateway

| 方法 | 职责 |
|------|------|
| `run` / `stream` | prepare_run → dispatcher |
| `try_tier0_chat` | SQL + force DB |
| `try_tool_fast_path` | ToolAgent |

### 15.2 CognitiveSupervisor.prepare_run

```text
evaluate_request_control_plane
  → runtime_task_from_request[_light]
  → RuntimePolicyEngine · RuntimeGovernor
  → build_runtime_context · world hydrate
  → bind_goal_graph · goal_projection · strategy_projection
  → apply_dispatch_enrichment（AdaptiveRisk、grounding、fabric phase=dispatch）
  → route_hint（默认 cognitive_executive）
```

### 15.3 RuntimeTurnDispatcher

- `resolve_runtime_name`：附录 G
- `dispatch_runtime`：`registry_governance` 严格模式
- `stream_turn`：`reasoning_step` → `delta` → `final_answer`（V3 metadata 合并）

### 15.4 run_outcomes · enterprise_outcomes · finalize_turn

与 §6.3、§47 一致；`run_outcomes.py` 在 `executive_result_to_kernel_response` 前 `sync_goal_lifecycle_from_metadata`。

---

## 16. Cognitive Runtime V2（Executive 管线）

入口：`kernel/runtime/cognitive_executive.py` — `CognitiveExecutive.execute()`。

```text
understand → plan（PlannerFacade + Policy on_planning）
  → validate_planned_capabilities（registry_governance / dispatch_pipeline）
  → execute（executor + DAG callbacks）
  → evidence_bus → fusion → critic
  → cognitive_iteration（可选）· goal hooks · capability feedback
  → persist_goal_progress · CognitiveExecutiveResult
```

Phase 严格：`kernel_runtime_phase_transition_strict`。  
Policy：附录 B。

---

## 17. Goal 生命周期、多目标与 turn_outcomes

- 状态机：`goal/state_machine.py`
- `goal/turn_outcomes.py`：lifecycle + memory fabric bind
- `goal_supervisor.py` + `prepare_dispatch`：P0 平台
- 多目标：`multi_goal_scheduler.py`、`multi_goal_resources.py`、`multi_goal_outcomes.py`
- `goal_progress.py`：Executive 末 persist

契约：`test_multi_goal_runtime_contract.py`、`test_goal_driven_dag_contract.py`。

---

## 18. 认知规划门面与多问题运行时

- `cognition/planner_facade.py`：四层规划；与 `goal_driven_planner` 联动
- `multi_question_runtime.py` + `cognition/multi_question.py`：拆问 → 可路由 `multi_goal`
- `multi_execution_planner.py`：并行/串行子计划

契约：`test_multi_question_runtime_contract.py`。

---

## 19. Runtime Registry、Tier-1 与 Data Intelligence

| runtime 名 | handler |
|------------|---------|
| `cognitive_executive` | `CognitiveExecutive().execute` |
| `data_intelligence` | `services/data_intelligence_runtime.run_data_intelligence_turn` |
| `multi_goal` | `multi_question_runtime.run_multi_question` |

`data_intelligence_runtime`：包装 `DataAgent`、挂载 V3、`GoalRuntimeHooks`、`attach_data_intelligence_to_metadata`。

契约：`test_data_intelligence_runtime_v3_contract.py`。

---

## 20. Agent 集群总览、Manifest 与 Worker

**Manifest 3.1.0** — `kernel/agent_runtime/agent_topology_manifest.yaml`

| agent_type | 类 | capability | bootstrap | worker | bus |
|------------|-----|------------|-----------|--------|-----|
| `data` | DataAgent | data_query | ✓ | ✓ | ✓ |
| `rag` | RagAgent | document_retrieval | ✓ | ✓ | ✓ |
| `web_intelligence` | WebIntelligenceAgent | web_search | ✓ | ✓ | ✓ |
| `web` | WebAgent | web_search | ✗ | ✗ | ✗ | legacy |
| `tool` | ToolAgent | tool | ✓ | ✓ | ✓ |
| `vision` | VisionAgent | vision_analysis | ✓ | ✓ | ✓ |
| `skills` | SkillsAgent | skill_execution | ✓ | ✓ | ✓ |
| `rules` | RuleEngineAgent | policy_rules | ✓ | ✓ | ✗ |

- **注册**：`agents/bootstrap.py` → `sync_manifest_to_runtime` → `capability_registry.register_agent`
- **Worker**：`agents/worker.py` — Redis stream，仅 `bus_eligible`
- **V3**：`kernel/agent_runtime/executor.py` — `UnifiedEvidence`、`validate_contribution`

### 20.1 基类（`agents/base.py`）

`TaskMessage`、`AgentResult`（含 `evidence_objects`）、`execute_as_capability()`。

### 20.2 CognitiveAgent（`agents/cognitive_agent.py`）

六阶段 trace；**WebIntelligenceAgent** 设置 `metadata.cognitive_agent=true`。

### 20.3 evidence_helpers（`agents/evidence_helpers.py`）

Agent 侧构造 V3 evidence 的共享 helper。

---

## 21. Agent 调用决策矩阵（何时用哪个 Agent）

| 触发条件 | 解析路径 | Agent / Runtime |
|----------|----------|-----------------|
| `/rag` 或 `force_mode=rag` | Executive 子任务 / capability | **RagAgent** |
| `/data` 或 data 意图 | `data_intelligence` / Tier0 | **DataAgent** V2 |
| `force_database` + source | `try_tier0_chat` | 无 Agent（Tier0） |
| web 意图 / `/web` | manifest preferred | **WebIntelligenceAgent** |
| 天气/时间 L0 或 `force_mode=tool` | `try_tool_fast_path` | **ToolAgent** |
| 图片附件 + vision | capability | **VisionAgent** |
| `/skills` | capability | **SkillsAgent** |
| `/rule` | capability | **RuleEngineAgent** |
| 「你可以做什么」 | `direct_answer` / capability_help | 少或无 Agent |
| 「你是谁」 | identity L0 / cache | 无 orchestrator（缓存） |
| 通用复杂 | `cognitive_executive` | Planner 选 capability 链 |
| 多问题 | `multi_goal` | multi_question_runtime |
| SQL 历史 Tier0 | tier0_paths | 内核快路径 |

**执行 SSOT**：`runtime/executor.py` → `capability_registry.resolve_execution_agent`。

---

## 22. 各 Agent 内部管线（逐 Agent）

### 22.1 RagAgent（`agents/rag_agent.py`）

```text
execute(task)
  → normalize/rewrite/classify query
  → tenant_id / workspace_id（turn_enrichment）
  → DocumentPlugin.search_chunks + llmwiki（多 query cap）
  → optional UserMemory
  → RRF · rerank（settings.rag_rerank_enabled）
  → DocumentEvidenceGate + answerable（relevance_score、substantive terms、retrieval_strong OR）
  → not answerable → 清空 chunks + 「未在知识库中找到…」
  → enrich_evidence_intelligence（claim/contradiction）
  → evidence_items / evidence_objects / ResultRef / metadata.rag_evidence_intelligence
```

**边界**：证据为主；用户可见长答由 **Fusion + LLM** 生成（受 relevance / format hint 约束）。

### 22.2 WebIntelligenceAgent（`agents/web_intelligence_agent.py`）

CognitiveAgent 六阶段 → `web_engine` 搜索 rank → evidence graph → **`coverage_evaluator`** 补搜循环（开关控制）。

### 22.3 WebAgent（`agents/web_agent.py`）

Legacy；`kernel_web_intelligence_preferred` 时 dispatch 解析到 web_intelligence。

### 22.4 ToolAgent（`agents/tool_agent.py`）

`execution/tool_router` + `kernel/tools`（weather、time）；与 `fast_tool_path` 共享。

### 22.5 DataAgent（`agents/data_agent.py`）

V2 supervisor 默认；`LowConfidenceError` + fallback → V1（`kernel/data_cognition`）。

### 22.6 VisionAgent · SkillsAgent · RuleEngineAgent

见 manifest contract 与 `test_agent_stubs_contract.py` / 各 `test_*_agent_contract.py`。

---

## 23. DataAgent V2 子 Agent 与 DAG

**Supervisor**：`agents/data_agent_v2/supervisor.py`

```text
clarification_gate（可短路，metadata.turn_outcome=needs_clarification）
  → L0 并行：intent · entity · metric · time · join · knowledge（检索）
  → semantic → business_semantic（开关 data_agent_business_semantic_enabled）
  → planner → sql_compiler → verification
  → SQL 执行（db_router）→ reflection / error_classifier 重试
  → insight · statistical · visualization（开关）
  → turn_metadata · evidence_objects · learning_hook
```

### 23.1 Tier-2 节点 ↔ 文件

| node_role | 模块 |
|-----------|------|
| intent | `intent_agent.py` |
| entity | `entity_agent.py` |
| metric | `metric_agent.py` + `metric_refiner.py` |
| time | `time_reasoning_agent.py` |
| join | `join_agent.py` |
| semantic | `semantic_agent.py` |
| business_semantic | `business_semantic_agent.py` |
| planner | `planner_agent.py` |
| compiler | `sql_compiler_agent.py` |
| verification | `verification_agent.py` |
| knowledge | `knowledge_retriever.py` |
| 分析/可视化 | `insight_agent.py`、`statistical_agent.py`、`visualization_agent.py` |
| 质量 | `reflection_agent.py`、`data_critic.py`、`error_classifier.py` |
| 学习 | `feedback_collector.py`、`knowledge_updater.py`、`pattern_extractor.py` |

DAG 构建：`dag_builder.py` + `validate_dag_against_manifest`。

契约：`test_data_agent_v2_*` 系列（supervisor、clarification、dag、manifest、turn_outcomes）。

---

## 24. 数据源、语义层与 Text2SQL

- **HTTP**：`routers/databases.py`、`data.py`、`table_relationships.py`、`metrics.py`
- **内核**：`kernel/data_cognition/*`（semantic_parser、sql_planner、validator、ranker、reflector、table_graph）
- **执行**：`execution/data/db_router.py`、`sql_executor.py`、`database_hosts.py`
- **元数据**：`infra/metadata/schema_inspector.py`

契约：`test_text2sql_*`、`test_database_*`、`test_data_cognition_pipeline.py`。

---

## 25. RAG、证据图与 RAG 智能层

| 模块 | 职责 |
|------|------|
| `plugins/document_plugin.py` | 分块、embedding、tenant/workspace 过滤 |
| `plugins/document_retrieval.py` | 混合检索、EvidenceGate |
| `services/rag_evidence_intelligence.py` | rank、graph、claim anchor |
| `services/rag_retrieval_clusters.py` | 聚类 |
| `services/evidence_graph/` | claim_graph、contradictions |
| `services/rag_retrieval_fusion.py` | RRF |

**配置**：代码侧 min score 常读 `RAG_MIN_SCORE`；settings 字段名见 `CONFIG_TRUTH.md`。

**运维**：文档 `ready`、tenant/workspace 与上传用户一致、embedding provider 可用（`docs/runbooks/evidence-gate-failure.md`）。

---

## 26. 记忆系统与 Memory Fabric

| 层 | 目录 |
|----|------|
| working | `memory/working_memory/` |
| episodic/semantic/procedural | 各 `memory/*_memory/` |
| Fabric | `memory/fabric/retrieval.py`、`memory_graph_redis.py`、`tms_bridge.py` |
| 注入 | `kernel/memory_injection.py` + Executive memory write |

`kernel_memory_fabric_primary_only=true`（staging/production 强制）：legacy router 仅在显式 false 时合并。

契约：`test_memory_graph_redis_contract.py`、`test_tms_bridge_contract.py`。

---

## 27. Capability OS、Control Plane 与执行路由

- `kernel/runtime/capability/capability_registry.py`
- `kernel/capability_runtime/`：selector、dispatch_pipeline、capability_os、contract strict
- `CapabilityAdapter`：web → web_intelligence
- `control_plane/control_plane.py` + `EnterpriseControlPlane`

契约：`test_capability_os_contract.py`、`test_capability_dispatch_pipeline.py`。

---

## 28. World Model、Redis 与 Shared World State

- `kernel/cognition/runtime_grounding.py` — 七切片
- `world/world_state_redis.py`、`cross_process_world_redis.py`（跨进程默认 off）
- `kernel/agent_runtime/world_decision_runtime.py` — counterfactual 启发式
- `world_turn_begin` / `world_turn_finalize`

契约：`test_world_model_runtime_contract.py`、`test_world_state_redis_contract.py`。

---

## 29. 企业多租户、配额、计费与审计

| 模块 | 职责 |
|------|------|
| `tenant/tenant_context.py` · middleware | 头解析 → session vars |
| `quota_redis_store.py` | Lua 原子 reserve/consume |
| `usage_redis_store.py` · `usage_metering.py` | 用量 |
| `billing_runtime.py` · `billing_store.py` | turn cost、ledger |
| `compliance_audit_store.py` | 合规事件 |

契约：`test_enterprise_control_plane_contract.py`、`test_quota_redis_atomic_contract.py`。

---

## 30. Policy Runtime 与变异点治理

`kernel/governance/policy_runtime.py` — planning / fusion / memory；`kernel_policy_mutation_fail_closed`（staging+ 强制）。

`GovernanceCenter.evaluate_turn` → `semantic_observability`、adaptive risk 闭环（`dispatch_enrichment`）。

---

## 31. 工具、技能、插件与连接器

- `execution/tool_router/router.py`
- `tools/builtin_tools/builtins.py`
- `plugins/*` — document、web、chart、code、file
- `skills/store/marketplace.py` + `gateway/routers/skills.py`
- `connectors/` + `sandbox_runtime/`

---

## 32. 规则引擎与灰度

`RuleEngineAgent` + `gateway/routers/rules.py`；`force_mode=rule_engine`。

---

## 33. 执行平面、DAG 与 Agent Bus

- **Executive 子任务**：`kernel/runtime/executor.py`
- **Data V2 DAG**：`execution/dag_engine/` + supervisor 内调度
- **Agent Bus**：`infra/message_bus/agent_bus.py` — Redis stream、DLQ、reclaim

契约：`test_agent_bus_e2e_contract.py`、`test_all_agent_bus_routing_contract.py`。

---

## 34. 模型网关、Token 计量与 Embedding / Rerank

- `model/model_gateway/gateway.py` — chat/completion、identity 后处理
- `infra/observability/turn_metering.py` — 回合 token
- `model/embedding/`、`model/reranker/` — RAG 管线
- `model/llm_adapter/` — OpenAI-compatible

---

## 35. 治理体系（canonical kernel.governance）

实现以 **`kernel/governance/`** 为准；仓库根 `governance/` 多为兼容 re-export。

| 组件 | 文件 |
|------|------|
| Evidence / Memory / Risk / Policy | `*_governor.py`、`*_policy_engine.py` |
| Semantic metrics | `semantic_metrics_pipeline.py`、`semantic_alerts.py` |
| Compliance | `compliance_runtime.py`、`compliance_audit_store.py` |
| Adaptive risk | `adaptive_risk_engine.py` |

契约：`test_governance_single_source_contract.py`。

---

## 36. 安全、审计、沙箱与可解释性

JWT（`routers/auth.py`）、`chat_preflight` PII、SQL 只读策略、`sandbox` 路由、`infra/security/zero_trust.py`、`safety/` 包（guardrails、audit、xai trace）。

---

## 37. 基础设施、配置、Flag 治理与环境 Profile

- **SSOT**：`infra/config/settings.py`（`AppSettings`）
- **文档**：`docs/ENV_PROFILES.md`、`docs/CONFIG_TRUTH.md`、`docs/FEATURE_FLAG_REGISTRY.md`
- **Flag 治理**：`infra/config/flag_registry.py`、`flag_governance.py`
- **自适应**：`kernel/adaptive_profiles.py` — 按 `app_env` 收紧 strict 开关

---

## 38. 数据库模型与迁移

`infra/storage/models.py`：`User`、`ChatSession`、`Message`、`TraceLog`、`DataSource`、`Document`（tenant/workspace）、`DocumentChunk`（pgvector）、`UserMemory`、企业 billing…

| 迁移 | 说明 |
|------|------|
| `20260613_documents_tenant_workspace` | **head** — 文档租户 |
| `20260611_billing_invoice_tables` | 账本 |
| `20260610_merge_cognitive_enterprise_heads` | 合并 head |
| `20260606_enterprise_tenants_rls` | RLS 基础 |

`ensure_runtime_schema()`：dev 兜底列。

契约：`test_alembic_single_head_contract.py`。

---

## 39. 部署、脚本与本地开发

```bash
cp .env.example .env
bash start-dev.sh          # 或 scripts/work/dev-boot-all-in-one.sh
curl -s http://127.0.0.1:14100/api/v1/health/cognitive-os | head
cd frontend && npm install && npm run dev   # :14108
bash scripts/run_vnext_final_tests.sh
```

| 脚本 | 用途 |
|------|------|
| `scripts/work/backend-*.sh` | API 启停 |
| `scripts/work/frontend-*.sh` | 前端 |
| `scripts/verify_all.sh` / `verify_docker.sh` | 集成验证 |
| `scripts/preflight_release.sh` | 发布前 |
| `scripts/weekly_release_checklist.sh` | 周检 |

---

## 40. 测试体系与发布门禁

```bash
pip install -e ".[dev]"
lint-imports --config importlinter.ini
PYTHONPATH=. pytest tests/ -q
bash scripts/run_vnext_final_tests.sh      # 371 tests（vNext 子集）
bash scripts/check_import_boundaries.sh
cd frontend && npm test -- --run           # 31 tests
```

### 40.1 `run_vnext_final_tests.sh` 完整列表（合并门禁）

`test_vnext_architecture_contract`、`test_vnext_full_stack_contract`、`test_architecture_requirements_alignment`、`test_architecture_governance_phase2`、`test_vnext_requirements_matrix`、`test_cognitive_supervisor_contract`、`test_multi_goal_runtime_contract`、`test_cognitive_runtime_contract`、`test_multi_question_runtime_contract`、`test_force_mode_multi_turn_contract`、`test_turn_enrichment_contract`、`test_multi_turn_resolution_contract`、`test_multi_turn_scenarios_fixture`、`test_documents_rag_retrieval_contract`、`test_execution_projection_enrichment_runtime`、`test_clarification_enrichment_contract`、`test_turn_bootstrap_contract`、`test_v6_v4_import_gate_contract`、`test_p2_p3_completion_contract`、`test_cognitive_controls_contract`、`test_clarification_gate`、`test_runtime_cognitive_executive`、`test_runtime_phase_strict_integration`、`test_kernel_import_boundaries`、`test_config_truth_contract`、`test_orchestrator_label_contract`、`test_goal_driven_dag_contract`、`test_memory_graph_redis_contract`、`test_capability_dispatch_pipeline`、`test_semantic_metrics_alerts_contract`、`test_governance_single_source_contract`、`test_data_agent_v2_dag_builder_contract`、`test_agent_runtime_v3_contract`、`test_agent_runtime_v3_strict_contract`、`test_agent_bus_eligibility_contract`、`test_all_agent_bus_routing_contract`、`test_agents_import_boundaries`、`test_data_intelligence_runtime_v3_contract`、`test_p0_cognitive_platform_contract`、`test_p1_decision_intelligence_contract`、`test_p2_completion_contract`、`test_rag_evidence_intelligence_contract`、`test_evidence_graph_contract`。

### 40.2 按域代表性契约

| 域 | 测试 |
|----|------|
| 问答一致 | `test_cognitive_controls_contract`、`test_identity_guard`、`test_rag_fusion_output_contract` |
| 多轮 | `test_multi_turn_*`、`tests/fixtures/multi_turn_scenarios.json` |
| RAG | `test_rag_agent_contract` |
| Data V2 | `test_data_agent_v2_turn_outcomes_contract` |
| Enterprise | `test_chat_preflight_contract` |
| Runtime-First | `test_runtime_contribution_contract`、`test_evidence_runtime_contract` |

CI：`.github/workflows/vnext-contract.yml`、`ci-fast.yml`、`nightly-multi-turn.yml`。

---

## 41. 架构治理文档矩阵

| 文档 | 内容 |
|------|------|
| `ARCHITECTURE_REQUIREMENTS_MATRIX.md` | #1–#30 需求对照 |
| `CAPABILITY_MATURITY.md` | 能力成熟度 |
| `RELEASE_GATE.md` | 发布门禁 |
| `docs/adr/001–003` | vNext 主路径、治理层、Memory Fabric |
| `docs/runbooks/*` | turn-trace、evidence-gate、tenant-rls |
| `docs/catalog/*` | 子系统深度说明 |
| `docs/architecture/SCENARIO_FLOW_GUIDES.md` | 场景流 |
| **本文** | 全项目索引 SSOT |

---

## 42. 开发规范与代码阅读顺序

1. 聊天必须 **CognitiveKernel**；复杂路径 **RuntimeGateway**。
2. Tier0 / Tool：**tier0_paths** + **fast_tool_path**。
3. 新 Agent：**manifest** + **bootstrap.py** + 契约测试。
4. SSE metadata：**turn_envelope_field_mapping** + **streamEnvelope.ts**。
5. RAG/相关度：**cognitive_controls** + **rag_agent answerable**。
6. 记忆检索 query：**ContextAssembler 当前轮 query**。

### 推荐阅读（2 天）

1. `gateway/routers/chat.py` → `cognitive_kernel.py` → `runtime_gateway.py`
2. `query_router_v2.py` + `v5_facade.py` + `cognitive_controls.py` + `context_assembler.py`
3. `cognitive_supervisor/supervisor.py` → `runtime_turn_dispatcher.py` → `cognitive_executive.py` → `fusion.py`
4. `agents/rag_agent.py` + `data_agent_v2/supervisor.py`
5. `agent_topology_manifest.yaml` + `bootstrap.py` + `agent_runtime/executor.py`
6. `frontend/utils/streamEnvelope.ts`

---

## 43. 已知风险、架构债与演进

| 项 | 说明 |
|----|------|
| RAG「未找到」 | 可能是 **answerable** 门控；查 relevance、tenant、embedding |
| 答非所问 | 查 `memory_injection_query`、intent_lock、fusion relevance；§52 |
| 身份误答 | V5 + `enforce_identity_output` + gateway 后处理 |
| World / StateGraph 多副本 | 强一致 ⚠️ |
| V4 源码 | `legacy/v4` 待物理删除 |
| 真 LLM E2E | 非 CI 默认 |

---

## 44. SSE 与流式事件契约

| type | 含义 |
|------|------|
| `delta` | 增量文本 |
| `reasoning_step` | 推理/DAG |
| `dag_node_*` | Data V2 节点 |
| `final_answer` | content + metadata + execution_graph |
| `error` | 预检/治理/异常 |

前端：`frontend/src/utils/streamEnvelope.ts` — `TurnMetaEnvelope`、`governance_warnings` 派生。

---

## 45. Kernel / Runtime / Goal / Enterprise 模块索引

（与上一版一致，略扩展）

- **runtime/**：`cognitive_executive`、`runtime_turn_dispatcher`、`registry`、`registry_governance`、`executor`、`fusion`、`finalize_turn`、`evidence_runtime`、`cognitive_state/`、`cognitive_iteration.py`、`self_optimizing_runtime.py`
- **cognitive_supervisor/**：`supervisor`、`prepare_dispatch`、`dispatch_enrichment`、`run_outcomes`、`enterprise_outcomes`、`control_plane_gate`
- **agent_runtime/**：`manifest`、`executor`、`runtime_contribution`、`unified_evidence`、`stream_metadata`、`world_decision_runtime`
- **goal/**：`goal_supervisor`、`turn_outcomes`、`goal_progress`、`multi_goal_*`、`autonomous_goal_discovery`
- **Enterprise**：`control_plane/`、`tenant/`、`observability/enterprise_telemetry.py`

---

## 46. 工程变更日志

### 2026-06-22（本文全量覆写）

1. 测试基线 **1255** collected；vNext 套件 **371** passed。
2. 新增 **§52 问答一致性**；**§12.4 ContextAssembler** 当前轮 memory 注入 SSOT。
3. **§6.9 Fusion** 链；**§23** Data V2 全 tier2 文件表；**§40.1** 完整 vNext 测试列表。
4. **§9** 前端页面表；**§8.1** runtime 子树；附录 **L 场景速查**。
5. 对齐 `cognitive_controls` relevance、identity `enforce_identity_output`、registry_governance。

### 2026-06-18

斜杠全链路、Agent 矩阵、RAG answerable、V5 身份守卫。

### 2026-06-11 — Runtime-First · Manifest 3.1.0

RuntimeContribution、CognitiveStateGraph、web_intelligence 单轨。

---

## 47. Runtime-First 统一运行时（Contribution / StateGraph）

**原则**：Agent 产出经 **RuntimeContribution** 写入 **CognitiveStateGraph**（Goal→Evidence→Memory→World）；`cognitive_state/bus.py` 单写路径。

**接线**：`dispatch_pipeline.attach_goal_participation_metadata` → `apply_runtime_contribution_to_bus` → `run_outcomes` metadata。

Redis（可选）：`cog_state_graph:{session_id}:{request_id}`。

---

## 48. 计费、账本与 Alembic 企业表

`turn_metering` → `billing_runtime` → `consume_turn_quota_async`（finalize_turn，有 event loop 时异步）。

---

## 49. Turn Envelope 字段映射详表

权威：`docs/architecture/turn_envelope_field_mapping.md`。

| 前端 | 后端 |
|------|------|
| `content` | `data.content` |
| `execution_graph` | `data.execution_graph` |
| `turn_meta` | `normalizeFinalAnswerEnvelope(data)` |

高频 metadata：`intent_lock`、`rag_evidence_intelligence`、`multi_turn_resolution`、`runtime_contribution_turn`、`cognitive_state_graph`、`goal_progress`、`registry_dispatch_gate`、`semantic_observability`。

流式合并键：`_V3_STREAM_KEYS` in `stream_metadata.py`。

---

## 50. 需求矩阵、成熟度与 P0–P2 认知平台

见 `ARCHITECTURE_REQUIREMENTS_MATRIX.md`。

| 阶段 | 能力 |
|------|------|
| P0 | GoalSupervisor、Cognitive Iteration、Strategy Memory |
| P1 | Claim Graph、Web Coverage、Capability Score、Predictive World |
| P2 | Evolution hook、Autonomous goals、Self-optimizing hints |

---

## 51. 附录：与 service_claude.md 的差异

| 主题 | service_claude | service_cursor |
|------|----------------|----------------|
| 快路径 | 分散 | RuntimeGateway 统一 |
| 答非所问 | 少 | §52 + relevance + 当前轮 memory query |
| Agent | 列表 | §21 矩阵 + §22–23 管线 |
| 测试 | 较早 | 1255 + run_vnext 371 |

---

## 52. 问答一致性与答非所问防控

**定义**：用户问 A，系统答 B（无关文档、错轮记忆、错能力、身份 blurb）— 本项目用**多层门禁**降低概率；**无** CI 内全自动语义 judge。

| 层级 | 机制 | 模块 | 契约 |
|------|------|------|------|
| 路由 | Intent Lock、follow-up 不继承 data_query | `cognitive_controls.py` | `test_cognitive_controls_contract` |
| 记忆/RAG query | 当前轮 `query` 作 memory_injection | `context_assembler.py` | `test_memory_injection_query_uses_current_turn_query` |
| 检索门控 | answerable + relevance_anchor | `rag_agent.py` + controls | `test_rag_agent_contract` |
| 合成 | Fusion 相关度 / format hint | `runtime/fusion.py` | `test_rag_fusion_output_contract` |
| 身份 | 非身份问句剥离 OpenTrace 开场 | `system_identity.py` | `test_identity_guard` |
| 多轮 | DST、ReferenceResolver | `multi_turn_resolution.py` | `multi_turn_scenarios.json` |
| V5 | 禁止 cache 返 canonical 身份 | `v5_facade.py` | `test_v5_routing_contract` |

**排查顺序**（runbook 风格）：

1. Turn trace 中 `metadata.intent_lock`、`memory_injection_query`（或 assembled context）
2. RAG `metadata.rag_evidence_intelligence.answerable`、scores
3. `capabilities_used` 是否误选 data/web
4. `multi_turn_resolution.applied` 与 `resolved_query`

**Staging 手工冒烟**：「你可以做什么」「我饿了（上一轮 SQL）」「根据知识库：如何成为队长」「你是谁」— 见 `docs/runbooks/turn-trace.md`。

---

## 附录 A. CognitiveKernel.run 内部分支

```text
multi_turn_resolution → classify_intent
  → identity cache / direct_answer
  → tool_fast_path → V5Facade.try_fast_path
  → RuntimeGateway.run/stream
```

---

## 附录 B. CognitiveExecutive 阶段与 Policy

PLAN → `on_planning`；FUSION → `on_evidence_fusion`；MEMORY → `on_memory_write`。

---

## 附录 C. import 边界

`bash scripts/check_import_boundaries.sh`；`importlinter.ini`。

---

## 附录 D. DataAgent V2 文件清单

`supervisor.py`、`dag_builder.py`、`turn_metadata.py`、`types.py`、`*_agent.py`（intent/entity/metric/time/join/semantic/business_semantic/planner/sql_compiler/verification/knowledge/insight/statistical/visualization）、`error_classifier.py`、`reflection_agent.py`、`data_critic.py`、`skills_engine.py`（DAG 内，≠ SkillsAgent）、`repair_strategies.json`。

---

## 附录 E. Redis Key 节选

| Key | 用途 |
|-----|------|
| `opentrace:quota:turns:*` | 日 turn 配额 |
| `world_state:{session_id}` | World |
| `cog_state_graph:*` | 认知图 |

---

## 附录 F. 关键环境变量

| 变量 | 含义 |
|------|------|
| `KERNEL_ORCHESTRATOR_V4_ENABLED` | false = vNext |
| `DATA_AGENT_V2_ENABLED` | Data V2 |
| `KERNEL_V5_ROUTING_ENABLED` | V5 |
| `KERNEL_WEB_INTELLIGENCE_PREFERRED` | web → web_intelligence |
| `ENTERPRISE_QUOTA_REDIS_ENABLED` | 配额 Redis |
| `USE_PGVECTOR` | 向量 |
| `RAG_MIN_SCORE` | RagAgent 阈值 |

完整列表：`.env.example` + `CONFIG_TRUTH.md`。

---

## 附录 G. resolve_runtime_name 决策树

```text
strategy_projection.preferred_runtime
  → data_intelligence | multi_goal
  → len(active_goals) > 阈值 → multi_goal
  → default cognitive_executive
```

---

## 附录 H. Agent Runtime V3

Strict（staging+）：缺 `evidence_objects` / unified evidence → 失败。契约：`test_agent_runtime_v3_strict_contract.py`。

---

## 附录 I. RuntimeGateway API

`try_tier0_chat`、`try_tool_fast_path`、`run`、`stream` — `kernel/runtime_gateway.py`。

---

## 附录 J. Manifest 校验

```python
from kernel.agent_runtime.manifest import validate_manifest_integrity
from agents.data_agent_v2.dag_builder import validate_dag_against_manifest
```

---

## 附录 K. Gateway Router 全表

| Router | 前缀/能力 |
|--------|-----------|
| health | 健康、cognitive-os |
| prometheus | 指标 |
| auth | 注册登录 JWT |
| chat | **主聊天** SSE/同步 |
| conversations | 会话历史 |
| cognitive | 调试认知 |
| documents | 文档 RAG 源 |
| memories | 记忆 CRUD |
| data · databases · table_relationships · metrics | 数据面 |
| tasks · audit | 任务审计 |
| skills · analytical_skills | 技能 |
| connectors · sandbox | 连接器沙箱 |
| feedback · rules · ui_settings | 反馈规则 UI |
| admin · enterprise_admin | 管理租户 |

挂载：`main.py` 中 `app.include_router(...)`。

---

## 附录 L. 场景速查（用户说什么 → 走哪条链）

| 用户输入特征 | 典型链路 |
|--------------|----------|
| `/rag …` | L0 → force rag → RagAgent → Fusion |
| `/data …` 或绑定 DB | data_intelligence 或 Tier0 |
| 「北京天气」 | L0 tool → ToolAgent / fast_path |
| 「你是谁」 | identity → cache 或 canonical（无 Executive） |
| 「你可以做什么」 | capability_help → direct_answer，禁无关 RAG |
| 上传图片问图表 | vision capability |
| 复杂开放问题 | cognitive_executive 多 capability |
| 一句多问题 | multi_goal / MultiQuestionCards |
| 低置信 SQL | clarification 或 V2→V1 fallback |

---

*文档结束 — 维护时请同步更新 §2 状态表、§46 变更日志与 `ARCHITECTURE_REQUIREMENTS_MATRIX.md`。*
