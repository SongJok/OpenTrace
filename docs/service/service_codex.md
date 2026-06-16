# OpenTrace 项目代码梳理（Claude 版）

> 本文档以当前仓库代码为事实来源，参考 `docs/service/service_codex.md` 的组织方式重新梳理。
>
> 目标是提供一份可维护的项目说明，覆盖架构、入口、核心链路、运行时、数据/RAG/记忆、安全、配置、部署、测试与排障。
>
> 最后更新：2026-05-27

---

## 目录

1. [项目定位](#1-项目定位)
2. [当前代码状态摘要](#2-当前代码状态摘要)
3. [技术栈](#3-技术栈)
4. [整体架构](#4-整体架构)
5. [目录结构](#5-目录结构)
6. [前端应用](#6-前端应用)
7. [API 网关](#7-api-网关)
8. [聊天主链路](#8-聊天主链路)
9. [认知内核与认知控制](#9-认知内核与认知控制)
10. [AI Runtime 统一运行时](#10-ai-runtime-统一运行时)
11. [V4 编排器、路由与多轮增强](#11-v4-编排器路由与多轮增强)
12. [Agent 集群](#12-agent-集群)
13. [DataAgent V2 认知型数据智能体](#13-dataagent-v2-认知型数据智能体)
14. [数据源、Knowledge Assets 与 Text2SQL](#14-数据源knowledge-assets-与-text2sql)
15. [RAG 与文档系统](#15-rag-与文档系统)
16. [记忆系统](#16-记忆系统)
17. [Capability Intelligence](#17-capability-intelligence)
18. [工具、技能、插件与连接器](#18-工具技能插件与连接器)
19. [规则引擎与灰度发布](#19-规则引擎与灰度发布)
20. [执行平面与 Agent Bus](#20-执行平面与-agent-bus)
21. [模型网关](#21-模型网关)
22. [安全、审计与可解释性](#22-安全审计与可解释性)
23. [基础设施与持久化](#23-基础设施与持久化)
24. [数据库模型](#24-数据库模型)
25. [配置项](#25-配置项)
26. [部署与运行](#26-部署与运行)
27. [测试体系](#27-测试体系)
28. [开发规范与维护建议](#28-开发规范与维护建议)
29. [排障入口](#29-排障入口)
30. [已知风险与后续优化](#30-已知风险与后续优化)

---

## 1. 项目定位

OpenTrace 是一个以 **Cognitive Kernel** 为中枢的 AgentOS / AI Runtime 项目。它不是单轮 ChatBot，而是将聊天、RAG、数据查询、工具调用、记忆、任务、审计、规则、技能、连接器和运行时观测整合到一套可部署的智能体系统中。

当前代码体现出的核心目标：

- **统一入口**：所有聊天请求进入 `gateway/api_gateway/routers/chat.py`，再进入 `kernel.cognitive_kernel.CognitiveKernel`。
- **受控认知链路**：通过 `kernel/cognitive_controls.py` 提供 Intent Lock、Cognitive Budget、Capability Guard 和 Relevance Anchor，防止简单问题被复杂 Runtime 过度扩张。
- **分层路由**：L0 规则、L0.5 语义缓存、L1 TinyRouter、复杂度引擎共同处理简单/中等请求，复杂任务进入完整编排。
- **双运行时并存**：稳定路径是 `CognitiveOrchestratorV4`，新运行时是 `kernel/runtime/` 下的 CognitiveExecutive / Unified Runtime。
- **多 Agent 能力**：Data、RAG、Web、Tool、Skills、Rule、Vision 等 Agent 由规划器、调度器或能力运行时调用。
- **数据认知**：DataAgent V2 将 Text2SQL 扩展为知识层、推理层、学习层组成的认知数据智能体。
- **证据优先**：RAG、Data、Web、Tool 等产物先作为 Evidence/候选材料进入融合和审校，再形成最终回答。
- **可观测与审计**：TraceLog、ReasoningTrace、CognitiveEvent、AuditLog、XAI trace、runtime snapshots 等记录运行过程。

---

## 2. 当前代码状态摘要

| 维度 | 当前状态 |
|------|----------|
| 后端入口 | FastAPI，默认端口 `14100` |
| 前端入口 | React/Vite，默认端口 `14108` |
| 主聊天入口 | `POST /api/v1/chat` |
| Kernel 主入口 | `kernel/cognitive_kernel.py` |
| 稳定编排器 | `kernel/orchestrator_v4.py` |
| 新运行时 | `kernel/runtime/cognitive_executive.py` |
| 分层路由 | `query_router_v2.py`、`tiny_router.py`、`complexity_engine.py`、`semantic_cache.py` |
| 认知控制 | `kernel/cognitive_controls.py` |
| DataAgent | V2 默认启用，V1 保留 |
| RAG | 文档 chunk、LLMWiki、pgvector/embedding、rerank、answerability gate |
| 记忆 | working / episodic / semantic / procedural / temporal / evolution |
| Capability Intelligence | capability profile、KG、reasoner、execution memory、strategy memory、evolution |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存/队列 | Redis 7，多 DB 隔离 |
| 部署 | Docker Compose + 本地 Vite 前端 |

关键默认配置来自 `infra/config/settings.py`：

```env
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_ENABLED=true
KERNEL_V5_ROUTING_ENABLED=true
KERNEL_L0_RULE_ROUTER_ENABLED=true
KERNEL_L1_TINY_ROUTER_ENABLED=true
KERNEL_SEMANTIC_CACHE_ENABLED=true
KERNEL_COGNITIVE_PLANNER_V2_ENABLED=true
KERNEL_CAPABILITY_INTELLIGENCE_ENABLED=true
KERNEL_CAPABILITY_INTELLIGENCE_PHASE2_ENABLED=true
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
ATTACHMENT_UPLOAD_ENABLED=true
```

---

## 3. 技术栈

### 3.1 后端

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI |
| ASGI 服务 | Uvicorn |
| ORM | SQLAlchemy asyncio |
| 数据库迁移 | Alembic |
| 数据库 | PostgreSQL 16 |
| 向量能力 | pgvector |
| 缓存/队列 | Redis 7 |
| LLM SDK | OpenAI-compatible API、DashScope |
| 配置 | pydantic-settings + `.env` |
| SQL | sqlglot、自研 `kernel/data_cognition` |
| 可观测 | OpenTelemetry、Prometheus、Jaeger、structlog |
| 安全 | JWT、bcrypt、host guard、PII masking、tool permission token |

### 3.2 前端

| 类别 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite |
| 路由 | react-router-dom |
| 状态 | Zustand |
| Markdown | react-markdown、remark-gfm、rehype-raw、shiki |
| 图表 | Recharts |
| 图标 | lucide-react |
| 测试 | Vitest + Testing Library |

### 3.3 基础设施

| 组件 | 容器/端口 |
|------|-----------|
| API | `opentrace_api`, `14100` |
| Agent Worker | `agent-worker` |
| PostgreSQL | `opentrace_postgres`, host `${POSTGRES_PORT:-5432}` |
| Redis | `opentrace_redis`, host `${REDIS_PORT:-6380}` |
| Prometheus | observability profile |
| Jaeger | observability profile |

---

## 4. 整体架构

```text
┌─────────────────────────────────────────────────────────────┐
│ Frontend: React/Vite                                        │
│ Chat / Databases / Documents / Skills / Rules / Memory ...  │
└───────────────────────────────┬─────────────────────────────┘
                                │ HTTP / SSE
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ API Gateway: FastAPI /api/v1                                │
│ auth, chat, conversations, documents, databases, data, ...   │
└───────────────────────────────┬─────────────────────────────┘
                                │ ChatRequest / RuntimeContext
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ CognitiveKernel                                               │
│ Intent Lock / L0 / Cache / TinyRouter / Context Assembly      │
└───────────────────────────────┬─────────────────────────────┘
                                │
              ┌─────────────────┴─────────────────┐
              ▼                                   ▼
┌─────────────────────────────┐     ┌─────────────────────────────┐
│ CognitiveExecutive Runtime  │     │ CognitiveOrchestratorV4      │
│ Rewrite -> Understand ->    │     │ Plan -> Dispatch -> Agent    │
│ Plan -> Execute -> Evidence │     │ Results -> Fusion -> Critic  │
└──────────────┬──────────────┘     └──────────────┬──────────────┘
               │                                   │
               ▼                                   ▼
        ┌─────────────────────────────────────────────────────┐
        │ Agent / Capability / Tool / Data / RAG / Web / Skill │
        └──────────────────────┬──────────────────────────────┘
                               ▼
        PostgreSQL + pgvector / Redis / Model Gateway / Audit
```

实际系统可分为六层：

1. **交互层**：前端页面、API client、SSE 消息处理。
2. **网关层**：认证、会话、附件、权限、路由、错误封装。
3. **认知层**：意图锁定、复杂度门控、规划、对话状态、上下文压缩、引用消解。
4. **执行层**：Agent、工具、数据查询、RAG、规则、技能、DAG。
5. **模型层**：按角色调度 LLM、Embedding、Rerank、Vision。
6. **基础设施层**：PostgreSQL、Redis、审计、事件、可观测、部署脚本。

---

## 5. 目录结构

```text
opentrace/
├── agent_runtime/              # Agent runtime、planner、executor、critic、market、reflector
├── agents/                     # Data/RAG/Web/Tool/Skills/Rule/Vision Agent
│   └── data_agent_v2/           # DataAgent V2 认知数据智能体
├── alembic/                    # Alembic 迁移
├── connectors/                 # connector SDK 与内置连接器
├── deploy/                     # Docker、Helm、K8s、Prometheus 配置
├── docs/                       # 项目文档与 catalog
├── evolution/                  # learning、feedback、self-play、meta-learning、data flywheel
├── execution/                  # DAG、workflow、sandbox、tool router、data executor
├── frontend/                   # React/Vite 前端
├── gateway/                    # FastAPI API gateway 与 cognitive gateway
├── infra/                      # config/storage/cache/security/observability/message bus
├── kernel/                     # Cognitive Kernel、Runtime、V4 Orchestrator、routing、fusion、critic
│   ├── runtime/                 # AI Runtime 统一运行时
│   ├── capability_intelligence/ # 能力画像、KG、执行记忆、策略记忆、演进
│   ├── data_cognition/          # SQL planning / validation / dialect / semantic layer
│   └── cognitive_controls.py    # Intent Lock / Cognitive Budget / Relevance Anchor
├── memory/                     # working/semantic/episodic/procedural/temporal/evolution memory
├── model/                      # LLM gateway、adapter、embedding、rerank
├── plugins/                    # chart/code/data/file/tool/document 插件
├── safety/                     # guardrails、policy、masking、canary、xai、audit
├── sandbox_runtime/            # sandbox providers
├── scripts/                    # 启停、验证、迁移、schema 同步脚本
├── sdk/                        # plugin/python SDK
├── services/                   # 文件解析等服务层辅助模块
├── skills/                     # skills runtime、store、installed
├── tests/                      # 后端合约与回归测试
├── tools/                      # tool registry 和内置工具
├── docker-compose.yml
├── requirements.txt
├── start.sh
└── stop.sh
```

---

## 6. 前端应用

前端入口：

- `frontend/src/main.tsx`
- `frontend/src/App.tsx`
- `frontend/src/api/client.ts`

### 6.1 页面

| 页面 | 作用 |
|------|------|
| `ChatPage.tsx` | 主聊天界面，同步/SSE、推理链、执行图、附件、快捷模式 |
| `DatabasesPage.tsx` | 数据源 CRUD、连接测试、schema 同步、语义配置 |
| `KnowledgeAssetsPage.tsx` | 知识资产管理入口 |
| `DocumentsPage.tsx` | 文档上传、列表、预览、删除、检索 |
| `SkillsPage.tsx` | 技能市场、创建、安装、测试、会话绑定 |
| `RulesPage.tsx` | 规则管理、版本、灰度、发布/回滚 |
| `MemoryPage.tsx` | 用户记忆、记忆设置 |
| `TasksPage.tsx` | 任务定义、运行、事件触发、通知 |
| `AuditPage.tsx` | 审计日志查询 |
| `IntegrationsPage.tsx` | 外部连接器管理 |
| `SettingsPage.tsx` | UI/用户设置 |
| `LoginPage.tsx` / `RegisterPage.tsx` | 登录注册 |

### 6.2 核心组件

| 组件 | 作用 |
|------|------|
| `ChatInput.tsx` | 输入框、斜杠命令、附件、发送控制 |
| `ChatMessage.tsx` | 消息渲染、工具卡片、JSON/Markdown/表格结构化显示 |
| `MessageList.tsx` | 消息列表 |
| `ReasoningChain.tsx` | 推理链展示 |
| `ExecutionGraphPanel.tsx` | 执行图展示 |
| `DagTimeline.tsx` | DAG 时间线 |
| `DecisionTraceCard.tsx` | 决策轨迹卡片 |
| `DataQueryResult.tsx` | 数据查询结果 |
| `DataTableChart.tsx` | 表格/图表切换 |
| `MetricDefinitionEditor.tsx` | 指标定义编辑 |
| `TableRelationGraph.tsx` | 表关系展示 |

### 6.3 前端数据流

```text
ChatInput
  -> apiChatStream / apiChatSync
  -> /api/v1/chat
  -> SSE delta / reasoning_step / tool_call / final_answer
  -> Zustand chat store
  -> ChatMessage / ReasoningChain / ExecutionGraphPanel
```

---

## 7. API 网关

主入口：

- `gateway/api_gateway/main.py`
- `gateway/api_gateway/routers/*.py`

### 7.1 Router 清单

| Router | 作用 |
|--------|------|
| `chat.py` | 聊天同步/流式、附件、停止、反馈、再生成 |
| `auth.py` | 注册、登录、JWT |
| `conversations.py` | 会话 CRUD、分支、消息版本 |
| `documents.py` | 文档上传、搜索、详情、删除 |
| `databases.py` | 数据源 CRUD、连接测试、schema 同步 |
| `data.py` | 数据查询 API |
| `metrics.py` | 指标定义 |
| `table_relationships.py` | 表关系 |
| `analytical_skills.py` | 分析技能 |
| `memories.py` | 记忆 CRUD 与设置 |
| `skills.py` | 技能安装、测试、会话绑定 |
| `rules.py` | 规则引擎管理 |
| `tasks.py` | 任务管理 |
| `audit.py` | 审计日志 |
| `feedback.py` | 用户反馈 |
| `connectors.py` | 连接器 |
| `sandbox.py` | 沙箱 |
| `ui_settings.py` | UI 设置 |
| `health.py` | 健康检查 |
| `cognitive.py` | 认知事件查询 |

### 7.2 ChatRequest 关键字段

| 字段 | 说明 |
|------|------|
| `query` | 用户输入 |
| `session_id` | 会话 ID |
| `stream` | 是否 SSE |
| `web_enabled` | 是否允许联网 |
| `force_mode` | 强制模式：`rag/data_query/data_analysis/anomaly_tracking/product/rule_engine/vision` |
| `data_source_id` | 数据源绑定 |
| `attachment_ids` | 附件上下文 |
| `parent_message_id` | 分支/编辑上下文 |
| `clarify_context` | 主动追问补充信息 |
| `enabled_skills` / `disabled_skills` | 会话技能控制 |

---

## 8. 聊天主链路

同步路径：

```text
POST /api/v1/chat
  -> gateway/api_gateway/routers/chat.py
  -> 认证 / 会话 / 历史 / 附件 / 数据源 / 用户偏好
  -> KernelRequest
  -> CognitiveKernel.run()
  -> Intent Lock / L0 / Cache / TinyRouter
  -> CognitiveExecutive 或 OrchestratorV4
  -> Agent/Capability 执行
  -> Fusion / Critic / Annotation
  -> TraceLog / Message / Memory 写回
  -> ChatResponse
```

流式路径：

```text
POST /api/v1/chat stream=true
  -> CognitiveKernel.stream()
  -> SSE:
      reasoning_step
      tool_call
      tool_result
      delta
      final_answer
```

重要特性：

- 支持同步和 SSE 流式两种模式。
- 支持 `/rag`、`/data`、`/web` 等前端斜杠命令。
- 支持附件解析和上下文注入。
- 支持 ConversationState、ResultRef、ReferenceResolver。
- 支持主动追问、纠正重规划、分支会话和消息版本。
- 支持工具权限 token 和高风险操作确认。

---

## 9. 认知内核与认知控制

主文件：

- `kernel/cognitive_kernel.py`
- `kernel/cognitive_controls.py`
- `kernel/query_router_v2.py`
- `kernel/tiny_router.py`
- `kernel/complexity_engine.py`
- `kernel/semantic_cache.py`
- `kernel/context_assembler.py`

### 9.1 CognitiveKernel 职责

`CognitiveKernel` 是聊天唯一中枢，负责：

1. 恢复 WorkingMemory。
2. 构建 Intent Lock。
3. 执行 L0 规则路由、语义缓存、L1 TinyRouter。
4. 按预算决定是否注入 memory/context。
5. 优先调用 CognitiveExecutive，失败时回退 V4。
6. 写回 WorkingMemory、EpisodicMemory、SemanticHistory。
7. 返回统一 `KernelResponse` 或 SSE event。

### 9.2 Intent Lock / Cognitive Budget

`kernel/cognitive_controls.py` 是当前项目最关键的稳定性控制层。

| 对象 | 作用 |
|------|------|
| `IntentLock` | 锁定 `raw_user_query`、`protected_intent`、`task_type`、允许/禁止能力 |
| `CognitiveBudget` | 限制 planning depth、capability 数量、memory token、context expansion、replan、critic |
| `classify_intent()` | 零 LLM 的确定性意图分类 |
| `direct_answer_for_intent()` | 能力/帮助类问题直接回答 |
| `relevance_score()` | 查询与候选输出的相关性评分 |
| `passes_relevance_anchor()` | Relevance Anchor，防止最终答案偏题 |

典型规则：

- `你好`、`你是谁`、`你可以做什么`、`怎么帮我` 走 L0 或 `intent_lock_direct`。
- 简单问答默认禁用 `rag.retrieve`、`memory.retrieve`、`web.search`、`data.query`。
- 文档/数据/联网/工具类任务才允许对应能力进入执行链路。
- RAG/fusion 输出必须通过相关性锚点，弱相关证据不能接管答案。

### 9.3 V5 Routing Tier

```text
L0 Rule Router
  -> identity / greeting / FAQ / slash command
L0.5 Semantic Cache
  -> 高相似历史回答复用
L1 Tiny Router
  -> simple / knowledge / complex 分类
Complexity Engine
  -> simple / medium / complex 评分
L2/V4 or Runtime
  -> 完整认知编排
```

---

## 10. AI Runtime 统一运行时

目录：`kernel/runtime/`

AI Runtime 是新一代统一执行管线，目标是将旧链路中分散的上下文拼装、规划、证据收集、融合、审校、产物写回收敛到 `RuntimeContext` 和 `CognitiveExecutive`。

### 10.1 核心管线

```text
RuntimeContext
  -> RewriteEngine
  -> UnderstandingEngine
  -> PolicyEngine
  -> CognitivePlannerV2
  -> StrategyBuilder
  -> ExecutionProjection
  -> CapabilityGraphBuilder
  -> ExecutionRuntime
  -> EvidenceBus
  -> FusionEngineV2
  -> CriticEngineV2
  -> ArtifactComposer
  -> Workspace / MemoryFabric
```

### 10.2 关键模块

| 模块 | 作用 |
|------|------|
| `context.py` | `RuntimeContext`，统一请求上下文 |
| `objects.py` | Evidence、RuntimeObject、ExecutionPlan、ExecutionNode 等对象模型 |
| `rewrite_engine.py` | 查询规范化，受 Intent Lock 约束 |
| `understanding_engine.py` | 深度任务理解 |
| `cognitive_executive.py` | 新 Runtime 单一入口 |
| `constraint_layer.py` | budget/policy/risk/capability/historical 五维守卫 |
| `capability.py` | CapabilityRegistry |
| `capability_graph_builder.py` | 能力图构建 |
| `executor.py` | ExecutionRuntime + DAG 执行 |
| `evidence_bus.py` | Evidence pub/sub 与生命周期 |
| `fusion.py` | FusionEngineV2 |
| `critic.py` | CriticEngineV2 |
| `artifact_composer.py` | Artifact 生成 |
| `workspace.py` | Workspace 状态 |
| `memory_fabric.py` | Runtime 记忆写回 |

### 10.3 Runtime 子目录

| 子目录 | 作用 |
|--------|------|
| `runtime/cognitive/` | CognitivePlannerV2、StrategyBuilder、ExecutionProjection、CognitiveGraph |
| `runtime/context_runtime/` | ContextCompressor、ContextRanker、EvidenceSelector、MemorySelector、SemanticDistiller |
| `runtime/evidence/` | Evidence lifecycle、ranking、resolution、state machine |
| `runtime/memory/` | truth maintenance、confidence decay、contradiction resolution、fact supersession |
| `runtime/replay/` | prompt snapshot、runtime snapshot、deterministic trace、execution replay |

---

## 11. V4 编排器、路由与多轮增强

主文件：`kernel/orchestrator_v4.py`

### 11.1 V4 经典管线

```text
OrchestratorV4Request
  -> identity shortcut
  -> TaskModel / WorldModel
  -> DialogueStateTracker / ReferenceResolver
  -> multi-question split
  -> RefinePlanner correction path
  -> PlanAgent.generate_plan()
  -> Dispatcher / DAG Scheduler
  -> AgentResult[]
  -> FusionEngine
  -> LLM grounded answer
  -> Epistemology Annotator / Validator
  -> CriticEngine
  -> ClarificationGate
  -> state_patch / result_refs
```

### 11.2 多轮增强

| 模块 | 作用 |
|------|------|
| `conversation_state.py` | 结构化会话状态 |
| `reference_resolver.py` | 指代/引用/纠正解析 |
| `result_ref_builder.py` | 结果引用构建 |
| `dialogue_state_tracker.py` | 对话状态追踪 |
| `refine_planner.py` | 局部纠正重规划 |
| `clarification_gate.py` | 主动追问 |
| `context_assembler.py` | 结构化上下文组装 |
| `context_composer.py` | 压缩与摘要 |
| `history_retriever.py` | 语义历史召回 |
| `preference_layers.py` | 用户偏好分层注入 |

### 11.3 融合与审校

- `kernel/fusion_engine/engine.py`：V1 加权融合。
- `kernel/fusion_engine/sequence_fusion.py`：多问题顺序融合。
- `kernel/critic_engine/engine.py`：候选答案评分、低置信补充提示、质量审校。
- `kernel/epistemology/`：证据标注、输出验证、渲染 hint。

---

## 12. Agent 集群

目录：`agents/`

| Agent | 文件 | 作用 |
|-------|------|------|
| DataAgent | `data_agent.py` | 数据查询入口，支持 V1/V2 |
| RagAgent | `rag_agent.py` | 文档、LLMWiki、memory 检索 |
| WebAgent | `web_agent.py` | 联网检索 |
| ToolAgent | `tool_agent.py` / V4 内置类 | 时间、天气、计算等工具 |
| SkillsAgent | `skills_agent.py` | 技能执行 |
| RuleEngineAgent | `rule_engine_agent.py` | 产品/业务规则匹配 |
| VisionAgent | `vision_agent.py` | 图片/图表理解 |
| Worker | `worker.py` | Agent Bus worker |
| Registry | `registry.py` | Agent 注册与查询 |

Agent 返回 `AgentResult`，包含：

- `task_id`
- `agent_type`
- `status`
- `content`
- `confidence`
- `metadata`
- `evidence`
- `error`

---

## 13. DataAgent V2 认知型数据智能体

目录：`agents/data_agent_v2/`

DataAgent V2 将数据查询分为三层：

1. **Knowledge Layer**：schema metadata、metric definitions、table relationships、analytical skills。
2. **Reasoning Layer**：意图、实体、指标、时间、join、语义、计划、SQL 编译、验证、反思。
3. **Learning Layer**：反馈收集、pattern extraction、metric refinement、schema enrichment。

### 13.1 主要模块

| 模块 | 作用 |
|------|------|
| `intent_agent.py` | 数据问题意图分类 |
| `entity_agent.py` | 实体识别 |
| `metric_agent.py` | 指标解析 |
| `time_reasoning_agent.py` | 时间范围推理 |
| `join_agent.py` | join 路径推理 |
| `semantic_agent.py` | 语义补全 |
| `planner_agent.py` | 数据查询计划 |
| `sql_compiler_agent.py` | SQL 生成 |
| `verification_agent.py` | SQL/结果验证 |
| `reflection_agent.py` | 错误反思 |
| `data_critic.py` | 数据答案审校 |
| `supervisor.py` | V2 supervisor 与重试修复 |
| `dag_builder.py` | 并行 DAG 构建 |
| `statistical_agent.py` | 统计分析 |
| `insight_agent.py` | 洞察生成 |
| `visualization_agent.py` | 可视化建议 |
| `skills_engine.py` | 分析技能执行 |

### 13.2 配置

```env
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
DATA_AGENT_V2_KNOWLEDGE_RETRIEVER_ENABLED=true
DATA_AGENT_V2_USE_METRIC_DEFINITIONS=true
DATA_AGENT_V2_USE_SCHEMA_METADATA=true
DATA_AGENT_V2_USE_TABLE_RELATIONSHIPS=true
DATA_AGENT_V2_CONFIDENCE_THRESHOLD=0.40
DATA_AGENT_V2_SUPERVISOR_MAX_RETRIES=2
```

---

## 14. 数据源、Knowledge Assets 与 Text2SQL

相关目录：

- `gateway/api_gateway/routers/databases.py`
- `gateway/api_gateway/routers/data.py`
- `gateway/api_gateway/routers/metrics.py`
- `gateway/api_gateway/routers/table_relationships.py`
- `gateway/api_gateway/routers/analytical_skills.py`
- `kernel/data_cognition/`
- `execution/data/`

### 14.1 数据源支持

| 类型 | 说明 |
|------|------|
| MySQL | 业务库查询 |
| PostgreSQL | 业务库查询 |
| ClickHouse | 分析型查询 |
| Doris | 分析型查询 |

### 14.2 Data Cognition 模块

| 模块 | 作用 |
|------|------|
| `semantic_layer.py` | 指标、维度、语义层 |
| `schema_linker.py` | schema linking |
| `query_planner.py` | 查询计划 |
| `logical_plan.py` | 逻辑计划 |
| `sql_builder.py` | SQL 构造 |
| `sql_validator.py` | SQL 验证 |
| `sql_rewriter.py` | SQL 修复 |
| `sql_reflector.py` | 反思 |
| `sql_dialect.py` | 方言适配 |
| `query_executor.py` | 执行 |
| `explanation.py` | 结果解释 |

---

## 15. RAG 与文档系统

相关文件：

- `agents/rag_agent.py`
- `plugins/document_plugin.py`
- `plugins/document_retrieval.py`
- `gateway/api_gateway/routers/documents.py`
- `services/file_parser.py`

### 15.1 RAG 流程

```text
query
  -> normalize / rewrite
  -> query type classify
  -> query expansion
  -> DocumentPlugin.search_chunks
  -> DocumentPlugin.search_llmwiki
  -> optional rerank
  -> evidence quality gate
  -> relevance anchor
  -> AgentResult(metadata.chunks / citations / quality)
```

### 15.2 重要控制

- `RAG_MIN_SCORE` / `rag_min_evidence_score` 控制检索阈值。
- `rag_rerank_enabled` 控制 reranker。
- `llmwiki_enabled` 控制 LLMWiki。
- RAG 会输出 `quality.answerable`、`quality.gated`、`quality.relevance_anchor`。
- 低相关 supporting chunk 会被降级，不再直接作为最终答案。

### 15.3 附件上传

支持 txt、md、csv、tsv、pdf、docx、xlsx、json、代码文件、图片等类型，解析后注入 `attachment_contexts`。

---

## 16. 记忆系统

目录：`memory/`

| 模块 | 作用 |
|------|------|
| `working_memory/` | Redis 支持的会话窗口、scratchpad、identity cache |
| `episodic_memory/` | 情节记忆，记录 turn/event |
| `semantic_memory/` | 语义记忆 |
| `procedural_memory/` | 程序性记忆 |
| `memory_router/` | 统一记忆检索路由 |
| `temporal_memory/` | 时间衰减索引 |
| `evolution/` | 记忆演进、治理、路由增强 |

### 16.1 记忆治理

`memory/evolution/governance.py` 提供：

- 信心衰减。
- 矛盾检测。
- 来源追踪。
- 记忆启用/禁用与质量控制。

### 16.2 注入原则

当前项目已引入 Cognitive Budget：

- 简单问答默认不注入 memory。
- 记忆类、延续类、个性化类任务才允许 memory 进入上下文。
- memory 作为候选上下文，不能覆盖 `raw_user_query`。

---

## 17. Capability Intelligence

目录：`kernel/capability_intelligence/`

Capability Intelligence 将系统从 “tool calling” 升级为 “capability cognition”。Planner 看到的不只是工具名，而是能力画像、可靠性、延迟、历史成功率、替代关系和策略记忆。

| 模块 | 作用 |
|------|------|
| `profile.py` | CapabilityProfile |
| `profiler.py` | 能力画像构建 |
| `adapter.py` | 为 Understanding/Planner 格式化能力信息 |
| `feedback.py` | 执行反馈闭环 |
| `ontology.py` | 能力本体 |
| `knowledge_graph.py` | 能力关系图 |
| `reasoner.py` | 基于 KG 和历史的能力推荐 |
| `execution_memory.py` | 执行统计与退化检测 |
| `strategy_memory.py` | 编排策略记忆 |
| `failure_memory.py` | 失败模式记录 |
| `evolution.py` | 持续改进引擎 |

关键配置：

```env
KERNEL_CAPABILITY_INTELLIGENCE_ENABLED=true
KERNEL_CAPABILITY_INTELLIGENCE_PHASE2_ENABLED=true
KERNEL_CAPABILITY_KNOWLEDGE_GRAPH_ENABLED=true
KERNEL_CAPABILITY_REASONER_ENABLED=true
KERNEL_CAPABILITY_EXECUTION_MEMORY_ENABLED=true
KERNEL_CAPABILITY_STRATEGY_MEMORY_ENABLED=true
KERNEL_CAPABILITY_EVOLUTION_ENABLED=true
```

---

## 18. 工具、技能、插件与连接器

### 18.1 Tools

相关目录：

- `kernel/tools/`
- `tools/registry/`
- `tools/builtin_tools/`
- `execution/tool_router/`

内置能力包括：

- 时间/日期。
- 天气。
- 计算器。
- Python/code sandbox。
- Web search。

### 18.2 Plugins

目录：`plugins/`

| 插件 | 作用 |
|------|------|
| `document_plugin.py` | 文档检索 |
| `web_plugin.py` | Web 检索 |
| `knowledge_plugin.py` | 知识增强 |
| `memory_plugin.py` | 记忆访问 |
| `tool_plugin.py` | 工具封装 |
| `code/` | 安全代码解释器 |
| `chart/` | 图表生成 |
| `data/` | 数据分析插件 |

### 18.3 Skills

目录：

- `skills/runtime/`
- `skills/store/`
- `skills/installed/`

Skills 支持 manifest 验证、加载、市场条目、会话启用/禁用和测试执行。

### 18.4 Connectors

目录：

- `connectors/sdk/`
- `connectors/builtin/`
- `gateway/api_gateway/routers/connectors.py`

用于外部系统集成和插件式数据接入。

---

## 19. 规则引擎与灰度发布

相关文件：

- `agents/rule_engine_agent.py`
- `gateway/api_gateway/routers/rules.py`
- `infra/storage/models.py`

能力：

- YAML 规则定义。
- 规则 CRUD。
- 版本化。
- 灰度发布。
- 发布/回滚。
- 与 Product/Rule force mode 集成。

配置：

```env
KERNEL_RULE_GRAYSCALE_ENABLED=true
KERNEL_RULE_GRAYSCALE_DEFAULT_PERCENTAGE=100
```

---

## 20. 执行平面与 Agent Bus

相关目录：

- `execution/`
- `kernel/dispatcher.py`
- `kernel/dag_scheduler.py`
- `kernel/runtime/executor.py`
- `agents/worker.py`

### 20.1 执行方式

| 模式 | 说明 |
|------|------|
| 直接执行 | Dispatcher 本进程调用 Agent |
| DAG 调度 | 根据依赖拓扑执行任务 |
| Speculative Execution | 并行候选执行 |
| Agent Bus | Redis pubsub/stream 分发给 worker |
| Runtime Executor | 新运行时中的 ExecutionRuntime |

### 20.2 Agent Bus 配置

```env
KERNEL_AGENT_BUS_ENABLED=true
KERNEL_AGENT_BUS_REQUIRE_WORKER=true
KERNEL_AGENT_BUS_NAMESPACE=opentrace:agent
KERNEL_AGENT_BUS_MODE=pubsub
KERNEL_AGENT_BUS_GROUP=agent-workers
KERNEL_AGENT_BUS_MAX_RETRY=2
```

---

## 21. 模型网关

目录：`model/`

### 21.1 角色化模型

| Role | 用途 |
|------|------|
| `QUERY` | 主回答、复杂推理、融合 |
| `PLANNING` | 任务分解、计划生成 |
| `COMPRESS` | 压缩与摘要 |
| `ROUTER` | L1 轻量分类 |
| `FAST` / `MIDDLESHORT` | 简单问答 |
| `MINSHORT` / `IDENTITY` | 身份与极轻任务 |
| `VISION` | 图像理解 |
| `CHEAP_CRITIC` | 低成本审校 |

### 21.2 Embedding / Rerank

| 模块 | 作用 |
|------|------|
| `model/embedding/` | embedding 调用 |
| `model/reranker/` | rerank 调用 |
| `model/model_gateway/` | 角色到模型的路由 |
| `model/llm_adapter/` | OpenAI-compatible adapter |

---

## 22. 安全、审计与可解释性

相关目录：

- `safety/`
- `infra/security/`
- `infra/audit/`
- `infra/observability/`
- `safety/xai/`

### 22.1 安全能力

| 能力 | 说明 |
|------|------|
| Zero Trust | 查询风险评估和权限 token |
| PII Masking | NER PII 脱敏 |
| Guardrails | 输入和策略防护 |
| SQL Safety | 只读 SQL、host guard、方言限制 |
| Tool Permission | 高风险工具确认 |
| Canary | 金丝雀测试与自动回滚 |

### 22.2 审计与可解释性

| 对象 | 说明 |
|------|------|
| `TraceLog` | 每轮 query/response/graph |
| `ReasoningTrace` | 推理步骤 |
| `CognitiveEvent` | runtime/cognitive event |
| `AuditLog` | 审计日志 |
| `XAI cognitive_trace` | 决策、fusion、critic、final 的可解释轨迹 |
| Runtime Snapshot | prompt/runtime deterministic replay |

---

## 23. 基础设施与持久化

### 23.1 PostgreSQL

默认数据库：

```env
DATABASE_URL=postgresql://postgres:<password>@postgres:5432/opentrace_v2
TOKEN_DB_URL=postgresql://postgres:<password>@postgres:5432/opentrace_v2
```

宿主机本地运行后端时通常需要改为：

```env
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2
TOKEN_DB_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2
```

`infra/config/settings.py` 会将 `postgresql://` 自动转换为 asyncpg 使用的 `postgresql+asyncpg://`。

### 23.2 Redis

默认：

```env
REDIS_URL=redis://redis:6379/10
```

逻辑 DB：

| DB | 用途 |
|----|------|
| 10 | session |
| 11 | cache |
| 12 | memory |
| 13 | queue |
| 14 | rate-limit |
| 15 | pubsub |

---

## 24. 数据库模型

主要模型集中在 `infra/storage/models.py`。

| 类别 | 典型模型 |
|------|----------|
| 用户与认证 | `User` |
| 会话与消息 | `ChatSession`、`Message`、`TraceLog` |
| 文档与附件 | `Document`、`DocumentChunk`、`Attachment` |
| 数据源 | `DataSource`、`DataSourceSchema` |
| 语义资产 | metric definitions、table relationships、analytical skills |
| 记忆 | `UserMemory`、`UserMemorySettings` |
| 任务 | task 相关模型 |
| 审计 | `AuditLog`、`ReasoningTrace`、`CognitiveEvent` |
| 规则 | rule、rule version、grayscale 相关模型 |
| 技能 | skill manifest / install / session config |

迁移目录：

```text
alembic/
└── versions/
```

---

## 25. 配置项

配置入口：

- `infra/config/settings.py`
- `.env`
- `.env.example`
- `docker-compose.yml`

### 25.1 运行端口

```env
API_PORT=14100
FRONTEND_PORT=14108
VITE_API_URL=http://localhost:14100
```

### 25.2 Kernel / Runtime

```env
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_ENABLED=true
KERNEL_V5_ROUTING_ENABLED=true
KERNEL_L0_RULE_ROUTER_ENABLED=true
KERNEL_L1_TINY_ROUTER_ENABLED=true
KERNEL_SEMANTIC_CACHE_ENABLED=true
KERNEL_MEMORY_CONTEXT_ENABLED=true
KERNEL_CONTEXT_COMPOSER_ENABLED=true
KERNEL_COGNITIVE_PLANNER_V2_ENABLED=true
KERNEL_RUNTIME_REWRITE_ENABLED=true
KERNEL_RUNTIME_UNDERSTANDING_ENABLED=true
KERNEL_RUNTIME_CAPABILITY_GRAPH_ENABLED=true
KERNEL_RUNTIME_EVIDENCE_FUSION_CRITIC_ENABLED=true
KERNEL_RUNTIME_WORKSPACE_ENABLED=true
```

### 25.3 RAG / 文档

```env
RAG_MIN_EVIDENCE_SCORE=0.65
RAG_AUTO_FALLBACK_TO_WEB=true
RAG_RERANK_ENABLED=true
LLMWIKI_ENABLED=true
LLMWIKI_TOP_K=3
ATTACHMENT_UPLOAD_ENABLED=true
ATTACHMENT_MAX_SIZE_MB=20
ATTACHMENT_MAX_CHARS=4000
```

### 25.4 DataAgent V2

```env
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
DATA_AGENT_V2_CONFIDENCE_THRESHOLD=0.40
DATA_AGENT_V2_SUPERVISOR_MAX_RETRIES=2
DATA_AGENT_V2_LEARNING_ENABLED=true
```

### 25.5 安全与治理

```env
KERNEL_NER_MASKING_ENABLED=true
KERNEL_CANARY_AUTO_ROLLBACK_ENABLED=true
KERNEL_RULE_GRAYSCALE_ENABLED=true
KERNEL_MEMORY_TRUTH_MAINTENANCE_ENABLED=true
```

---

## 26. 部署与运行

### 26.1 Docker 启动

```bash
bash start.sh
```

或：

```bash
docker compose up -d postgres redis api agent-worker
```

健康检查：

```bash
curl http://127.0.0.1:14100/api/v1/health
curl http://127.0.0.1:14100/api/v1/health/deps
curl http://127.0.0.1:14100/api/v1/health/runtime
```

### 26.2 本地后端

```bash
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
PYTHONPATH=. python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

### 26.3 本地前端

```bash
cd frontend
npm install
npm run dev
```

默认访问：

- API: `http://localhost:14100`
- Swagger: `http://localhost:14100/docs`
- Frontend: `http://localhost:14108`

### 26.4 迁移

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic history --verbose
```

---

## 27. 测试体系

### 27.1 后端测试

常用命令：

```bash
PYTHONPATH=. pytest -q
```

重点测试文件：

| 测试 | 覆盖 |
|------|------|
| `tests/test_v5_routing_contract.py` | L0/L1/语义缓存/上下文组装 |
| `tests/test_cognitive_controls_contract.py` | IntentLock、CognitiveBudget、Relevance Anchor |
| `tests/test_runtime_cognitive_executive.py` | CognitiveExecutive 集成 |
| `tests/test_cognitive_runtime_contract.py` | Runtime V2 合约 |
| `tests/test_capability_intelligence.py` | Capability Intelligence |
| `tests/test_data_agent_v2_agent_contract.py` | DataAgent V2 agent 层 |
| `tests/test_data_agent_v2_supervisor_contract.py` | DataAgent V2 supervisor |
| `tests/test_rag_agent_contract.py` | RAG agent |
| `tests/test_rag_fusion_output_contract.py` | RAG/fusion 输出 |
| `tests/test_force_mode_routing.py` | 强制模式 |
| `tests/test_documents_rag_retrieval_contract.py` | 文档/RAG |
| `tests/test_databases_api_contract.py` | 数据源 API |
| `tests/test_memory_api_contract.py` | 记忆 API |
| `tests/test_health_runtime_metrics_contract.py` | health/runtime metrics |

### 27.2 前端测试

```bash
cd frontend
npm run test
npm run build
```

### 27.3 注意事项

裸 `pytest` 在某些环境下可能找不到 `kernel` 包，推荐显式设置：

```bash
PYTHONPATH=. pytest -q
```

---

## 28. 开发规范与维护建议

1. **聊天输出不得绕过 CognitiveKernel**：所有对话输出必须从 Kernel 进入。
2. **简单问题优先 L0 / Intent Lock**：不要让“你好/你是谁/你能做什么”进入 RAG、memory、planner。
3. **不要覆盖 raw query**：重写只能生成 canonical query，不能替代 `raw_user_query`。
4. **能力选择必须受约束**：Planner 输出需符合 allowed/disallowed capabilities。
5. **RAG 只做证据，不做无条件答案**：低相关证据必须被 answerability gate 拦截。
6. **Memory 按需注入**：避免长期记忆污染当前问题。
7. **新增能力要补合约测试**：路由、配置、API、AgentResult metadata 都要覆盖。
8. **保持文档事实化**：不要把规划中的模块写成已完成，除非代码和测试存在。
9. **保留用户改动**：仓库常有并行修改，编辑时只动任务相关文件。

---

## 29. 排障入口

### 29.1 服务健康

```bash
curl http://127.0.0.1:14100/api/v1/health
curl http://127.0.0.1:14100/api/v1/health/deps
curl http://127.0.0.1:14100/api/v1/health/runtime
```

### 29.2 日志

```bash
bash scripts/docker_logs.sh api
docker compose logs -f api
docker compose logs -f agent-worker
```

### 29.3 数据库

```bash
docker compose exec -T postgres psql -U postgres -d opentrace_v2 -c "\dt"
docker compose exec -T api alembic current
```

### 29.4 Redis

```bash
docker compose exec -T redis redis-cli ping
docker compose exec -T redis redis-cli -n 10 keys '*'
```

### 29.5 常见问题

| 问题 | 排查 |
|------|------|
| API 连不上数据库 | 检查 `DATABASE_URL` 是容器地址 `postgres` 还是宿主机 `127.0.0.1` |
| Redis 连接失败 | Docker 内使用 `redis:6379`，宿主机使用 `127.0.0.1:6380` |
| 简单问答答非所问 | 检查 `kernel/cognitive_controls.py` 和 L0 FAQ 是否命中 |
| RAG 返回无关文档 | 检查 `quality.answerable`、`quality.relevance_anchor`、`rag_min_evidence_score` |
| DataAgent 查询失败 | 检查数据源连接、schema 同步、metric/table relationships |
| SSE 无响应 | 检查 `/api/v1/chat` stream、浏览器 network、后端日志 |
| 前端 API 地址错误 | 检查 `VITE_API_URL` |
| 测试 import 失败 | 使用 `PYTHONPATH=. pytest -q` |

---

## 30. 已知风险与后续优化

### 30.1 当前风险

- 新旧运行时并存，`CognitiveExecutive` 与 `OrchestratorV4` 的职责边界仍需继续收敛。
- Capability Intelligence 默认开启后，能力推荐会受历史反馈影响，需要持续监控退化。
- Agent Bus 依赖 worker 和 Redis，部署不完整时可能产生执行等待或回退路径。
- 文档、README、CLAUDE.md、service 文档之间仍可能出现事实漂移。
- 前端 contract 测试与 UI 快速演进之间可能存在短期不一致。

### 30.2 优先优化方向

1. 将 `IntentLock` 贯穿所有 planner、fusion、critic 和 memory selector。
2. 为复杂度分级建立更完整的评测集。
3. 将 RAG 的 answerability gate 与 citation 展示统一到 Evidence lifecycle。
4. 合并 V4 与 Runtime 的重复融合/审校逻辑。
5. 为 DataAgent V2 增加真实数据源集成回归。
6. 建立文档自动校验：配置项、router、测试文件、模块清单自动生成摘要。
7. 增强前端 Trace UI，展示 raw query、protected intent、selected capabilities、relevance score。

---

## 附录：推荐阅读顺序

1. `README.md`
2. `docs/service/service_codex.md`
3. `docs/service/service_claude.md`
4. `gateway/api_gateway/routers/chat.py`
5. `kernel/cognitive_kernel.py`
6. `kernel/cognitive_controls.py`
7. `kernel/orchestrator_v4.py`
8. `kernel/runtime/cognitive_executive.py`
9. `agents/rag_agent.py`
10. `agents/data_agent_v2/`
