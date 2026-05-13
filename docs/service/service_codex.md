# OpenTrace 项目代码梳理（Codex 版）

> 本文档不以现有项目 Markdown 文档作为事实来源，而是基于代码入口、配置、路由、模型、测试与部署脚本反向梳理。
>
> 输出格式参考 `SERVICE.md` 的组织方式；内容判断以当前代码为准。
>
> 最后更新：2026-05-09

---

## 目录

1. [项目定位](#1-项目定位)
2. [技术栈](#2-技术栈)
3. [整体架构](#3-整体架构)
4. [目录结构](#4-目录结构)
5. [前端应用](#5-前端应用)
6. [API 网关](#6-api-网关)
7. [聊天主链路](#7-聊天主链路)
8. [认知内核](#8-认知内核)
9. [编排器与路由](#9-编排器与路由)
10. [Agent 集群](#10-agent-集群)
11. [模型网关](#11-模型网关)
12. [数据认知与 Text2SQL](#12-数据认知与-text2sql)
13. [RAG 与文档系统](#13-rag-与文档系统)
14. [记忆系统](#14-记忆系统)
15. [工具、技能、插件与连接器](#15-工具技能插件与连接器)
16. [规则引擎](#16-规则引擎)
17. [执行平面与 Agent Bus](#17-执行平面与-agent-bus)
18. [安全、审计与可解释性](#18-安全审计与可解释性)
19. [基础设施与持久化](#19-基础设施与持久化)
20. [数据库模型](#20-数据库模型)
21. [配置项](#21-配置项)
22. [部署与运行](#22-部署与运行)
23. [测试体系](#23-测试体系)
24. [代码视角的关键判断](#24-代码视角的关键判断)
25. [排障入口](#25-排障入口)
26. [新增功能：自适应配置系统](#26-新增功能自适应配置系统2026-05)
27. [近期修复与前端更新](#27-近期修复与前端更新2026-05-09)

---

## 1. 项目定位

OpenTrace 是一个以 FastAPI 网关为外壳、以 Cognitive Kernel 为中枢的多能力 Agent 应用。它不是单纯聊天机器人，而是把用户问题路由到不同认知能力：普通问答、RAG 文档检索、数据库自然语言查询、联网搜索、工具调用、规则引擎、技能执行、视觉理解、多轮对话增强与审计追踪。

从代码关系看，系统核心目标是：

- 将所有用户请求统一进入 `kernel.cognitive_kernel.CognitiveKernel`。
- 通过分层路由和编排器判断是否走快速回答、规则命中、语义缓存或完整 Agent 管线。
- 通过 `PlanAgent` 把复杂问题拆为子任务，再由 `Dispatcher` 调度 Data/RAG/Web/Tool/Skills/Rule/Vision 等 Agent。
- 将执行结果交给融合、校验、审校、证据标注模块，生成前端可展示的答案、引用、推理步骤和执行图。
- 通过 PostgreSQL、pgvector、Redis、事件总线和审计表沉淀会话、文档、记忆、数据源、任务、反馈和追踪信息。

---

## 2. 技术栈

### 2.1 后端

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI |
| ASGI 服务 | Uvicorn |
| ORM | SQLAlchemy asyncio |
| 数据库迁移 | Alembic |
| 数据库 | PostgreSQL 16 |
| 向量能力 | pgvector |
| 缓存/队列 | Redis |
| LLM 适配 | OpenAI-compatible API，默认配置偏向 DashScope/Qwen |
| 配置 | pydantic-settings + `.env` |
| SQL 处理 | sqlglot、自研 Text2SQL pipeline |
| 可观测性 | OpenTelemetry、Prometheus、结构化日志 |
| 安全 | JWT、bcrypt、零信任工具令牌、PII 脱敏 |

### 2.2 前端

| 类别 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite |
| 路由 | react-router-dom |
| 状态 | Zustand |
| Markdown | react-markdown、remark-gfm、rehype-raw |
| 图表 | Recharts |
| 图标 | lucide-react |
| 测试 | Vitest + Testing Library |

### 2.3 运行环境

| 组件 | 默认端口/角色 |
|------|---------------|
| API | `14100` |
| Frontend | `14108` |
| PostgreSQL | 宿主映射默认 `5432` |
| Redis | 宿主映射默认 `6380` |
| Prometheus | `14190` |
| Jaeger | `14186`，OTLP gRPC `4317` |

---

## 3. 整体架构

```text
Frontend (React/Vite)
    |
    | HTTP / SSE
    v
API Gateway (FastAPI /api/v1)
    |
    | auth/session/context/attachment/audit
    v
CognitiveKernel
    |
    | L0 rules / semantic cache / tiny router / complexity / V4 orchestrator
    v
CognitiveOrchestratorV4
    |
    | plan -> dispatch -> execute -> fuse -> validate -> critic -> annotate
    v
Agent Cluster
    |
    +-- DataAgent      -> DataSource + schema + Text2SQL + SQL execution
    +-- RagAgent       -> documents + chunks + LLMWiki + user memories
    +-- WebAgent       -> external web search
    +-- ToolAgent      -> time/weather/calculator/code-like tools
    +-- SkillsAgent    -> installed/session-bound skills
    +-- RuleEngine     -> YAML business rules
    +-- VisionAgent    -> multimodal/vision model
    |
    v
ModelGateway / DB / Redis / Event Bus / Audit / XAI
```

该项目的实际分层可以理解为：

- **交互层**：前端页面和 API 路由。
- **控制层**：聊天路由、会话上下文、附件注入、权限令牌、SSE 生命周期。
- **认知层**：Cognitive Kernel、V5 路由、V4 编排、多轮增强、融合与审校。
- **能力层**：Agent、工具、技能、插件、数据查询、RAG、规则。
- **基础设施层**：模型网关、存储、Redis 影子存储、事件总线、审计、指标、追踪。

---

## 4. 目录结构

```text
opentrace/
├── gateway/                 # FastAPI 应用与 API routers
├── kernel/                  # 认知内核、路由、规划、调度、融合、数据认知
├── agents/                  # Data/RAG/Web/Tool/Skills/Rule/Vision 等 Agent
├── agent_runtime/           # Agent runtime、planner、executor、market、reflector
├── execution/               # DAG、workflow、sandbox、tool router、data executor
├── model/                   # LLM 网关、OpenAI-compatible adapter、embedding、rerank
├── memory/                  # working/semantic/episodic/procedural/evolution memory
├── infra/                   # config/storage/cache/message_bus/security/observability
├── safety/                  # guardrails、policy、masking、canary、xai、audit
├── plugins/                 # document/web/knowledge/memory/data/chart/code/tool plugins
├── skills/                  # skill runtime、loader、manifest、marketplace
├── connectors/              # connector SDK 与内置连接器
├── rules/                   # YAML 规则与版本目录
├── frontend/                # React/Vite 前端
├── tests/                   # 合同测试、回归测试、前端测试
├── alembic/                 # 数据库迁移
├── deploy/                  # Docker/Helm/K8s/Prometheus 配置
├── scripts/                 # 启停、验证、迁移、清理、LLM 测试脚本
├── docker-compose.yml       # 本地/容器编排入口
├── start.sh                 # 统一 Docker 启动脚本
└── stop.sh                  # 统一 Docker 停止脚本
```

---

## 5. 前端应用

前端入口是 `frontend/src/main.tsx` 和 `frontend/src/App.tsx`。路由层有登录保护，登录后默认进入 `/chat`。

主要页面：

| 页面 | 路径 | 作用 |
|------|------|------|
| ChatPage | `/chat` | 主聊天界面，承载同步/SSE、工具卡片、推理链、执行图 |
| DocumentsPage | `/documents` | 文档管理与检索入口 |
| DatabasesPage | `/databases` | 数据源管理、连接测试、schema 同步、语义映射 |
| RulesPage | `/rules` | 规则文件和规则版本管理 |
| SkillsPage | `/skills` | 技能安装、创建、测试、会话绑定 |
| TasksPage | `/tasks` | 任务定义、运行与通知 |
| MemoryPage | `/memories` | 用户记忆与记忆设置 |
| AuditPage | `/audit` | 审计日志 |
| IntegrationsPage | `/integrations` | 外部连接器 |
| SettingsPage | `/settings` | UI 与用户配置 |

关键前端模块：

- `frontend/src/api/client.ts`：后端 API 客户端。
- `frontend/src/store/auth.ts`：JWT 与用户态。
- `frontend/src/store/chat.ts`：聊天消息、会话、流式状态。
- `frontend/src/components/ChatInput.tsx`：输入区、快捷模式、附件/命令入口。
- `frontend/src/components/ChatMessage.tsx`：消息渲染、工具卡片、结构化结果。
- `frontend/src/components/DecisionTraceCard.tsx`、`ExecutionGraphPanel.tsx`、`DagTimeline.tsx`：推理/执行可视化。
- `frontend/src/components/DataTableChart.tsx`、`DataQueryResult.tsx`：数据查询结果与图表。

---

## 6. API 网关

FastAPI 应用入口是 `gateway/api_gateway/main.py`。

网关行为：

- 应用名 `OpenTrace API`，版本 `0.1.0`。
- 所有业务 router 统一挂载在 `/api/v1`。
- CORS 目前全放开。
- HTTP 中间件注入 `x-request-id` 和 `x-response-time-ms`。
- 统一处理 `AppException` 和未捕获异常。
- 启动时开启 `memory_event_subscriber`，关闭时停止。

主要 API 面：

| Router | 关键路径 | 作用 |
|--------|----------|------|
| health | `/health`, `/health/deps`, `/health/runtime`, `/ping` | 存活、依赖、运行态指标 |
| auth | `/auth/register`, `/auth/token`, `/auth/login`, `/auth/me` | 注册、登录、JWT 当前用户 |
| chat | `/chat`, `/chat/attachments`, `/chat/stop`, `/chat/graph-control`, `/chat/regenerate`, `/chat/edit-and-regenerate`, `/chat/feedback`, `/chat/resume` | 聊天主能力 |
| conversations | `/conversations`, `/messages/{id}`, `/conversations/{id}/branch` | 会话、消息编辑、分支 |
| documents | `/documents`, `/documents/search` | 文档 CRUD 与检索 |
| databases | `/databases`, `/test-connection`, `/sync-schema`, `/query`, `/analysis`, `/semantic` | 数据源与数据查询 |
| data | `/data/query`, `/data/schema/sync`, `/data/schema` | 数据查询兼容入口 |
| memories | `/memories`, `/memories/settings` | 用户记忆和开关 |
| skills | `/skills`, `/install`, `/create`, `/test`, `/session/bind` | 技能市场与会话绑定 |
| rules | `/rules`, `/versions`, `/grayscale`, `/promote`, `/rollback` | YAML 规则与版本发布 |
| tasks | `/tasks`, `/pause`, `/resume`, `/cancel`, `/events/trigger`, `/notifications` | 任务与通知 |
| audit | `/audit/logs`, `/audit/export` | 审计查询与导出 |
| cognitive | `/cognitive-events/replay` | 认知事件回放 |
| xai | `/xai/traces`, `/xai/sessions/{id}/trace` | 可解释追踪 |
| connectors | `/connectors`, `/authorize`, `/callback`, `/resources`, `/sync` | 外部连接器 |
| sandbox | `/sandbox/download` | 沙箱产物下载 |
| admin | `/admin/*` | 策略、工具、学习、bandit、market、自博弈 |
| ui_settings | `/users/ui-settings` | UI 展示偏好 |

---

## 7. 聊天主链路

聊天路由位于 `gateway/api_gateway/routers/chat.py`，它是代码中最重要的控制层模块。

请求模型 `ChatRequest` 支持：

- `query`、`session_id`、`stream`、`web_enabled`
- `graph_controls`
- `enabled_skills`、`disabled_skills`
- `tool_permission_token`、`confirmation_granted`
- `data_source_id`、`data_source_name`
- `force_database`、`force_mode`
- `clarify_context`、`clarify_question_id`
- `parent_message_id`
- `attachment_ids`

同步/流式聊天的主要处理意图：

1. 鉴权并建立用户、会话和 request context。
2. 处理附件上传或附件内容注入。
3. 读取会话历史、上一轮执行图、分支 checkpoint。
4. 判断 SQL 生成、SQL 查询、数据库强制模式等特殊路径。
5. 通过 `require_kernel_entrypoint` 约束所有回答进入内核。
6. 调用 `CognitiveKernel.run()` 或 `CognitiveKernel.stream()`。
7. 将返回内容、引用、标注、执行图、推理步骤写入 `TraceLog`、`ReasoningTrace`、事件总线和审计。
8. SSE 模式下发送 delta、reasoning_step、agent_start、agent_complete、final_answer 等事件。
9. 支持停止流、图节点剪枝/展开、重生成、编辑后重生成、反馈、resume。

这说明聊天层不是薄转发，它承担了上下文装配、权限、安全、持久化和前端协议适配。

---

## 8. 认知内核

`kernel/cognitive_kernel.py` 是系统认知入口。代码明确表达的原则是：所有输出都应由认知内核生成，插件、工具、RAG、Web 和数据库结果只是候选认知材料。

核心组件：

- `KernelRequest`：用户问题、会话、用户、历史、流式标记、联网标记、metadata、trace context。
- `KernelResponse`：内容、route、validation、hallucination risk、intent、latency、metadata。
- `CognitiveKernel.run()`：同步执行。
- `CognitiveKernel.stream()`：流式执行。
- lazy singleton：intent engine、policy engine、reasoning engine、meta cognition、memory router、prompt engine、model gateway。

内核中的快速路径与增强能力：

- 身份类问题工作记忆缓存。
- V5 Routing Tier：L0 规则、语义缓存、复杂度判断、Tiny Router。
- force mode 跳过部分自动路由，直接进入指定能力。
- 多问题检测。
- 上下文压缩与组合。
- 工作记忆、自我模型、身份响应约束。
- 最终回落到 V4 编排器进行完整 Agent 管线。

---

## 9. 编排器与路由

主编排器是 `kernel/orchestrator_v4.py`。

它的职责不是简单选择一个 Agent，而是完整组织一次认知执行：

1. 根据 query、history、metadata、用户画像生成 adaptive profile。
2. 做 PII masking、身份问题处理、澄清问题判断、纠错重规划判断。
3. 处理 force mode，包括 `rag`、`data_query`、`data_analysis`、`anomaly_tracking`、`product`、`rule_engine`、`tool`、`skills`、`web`、`vision`。
4. 调用 `PlanAgent` 生成 subtasks 与 DAG。
5. 用 `Dispatcher` 调度 Agent，必要时通过 DAG scheduler 或 Agent Bus。
6. 对 RAG 质量不足、数据失败、联网需要等场景进行补救。
7. 用 Fusion Engine 或 Sequence Fusion 合并多 Agent 结果。
8. 用 OutputValidator、CriticEngine、ContentAnnotator 做质量与证据层标注。
9. 输出执行图、agent_results、citations、annotations、multi-question metadata、trace 信息。

相关模块：

| 模块 | 作用 |
|------|------|
| `kernel/plan_agent.py` | 规划子任务、识别多子问题、生成 DAG |
| `kernel/dispatcher.py` | 并发调度、fallback、Agent Bus、DAG 调度 |
| `kernel/dag_scheduler.py` | 按依赖执行 DAG 节点 |
| `kernel/fusion_engine/*` | 结果融合、顺序融合、多子问题融合 |
| `kernel/critic_engine/*` | 输出审校 |
| `kernel/epistemology/*` | 证据、标注、验证、渲染提示 |
| `kernel/clarification_gate.py` | 主动澄清 |
| `kernel/refine_planner.py` | 用户纠正后的增量重规划 |
| `kernel/dialogue_state_tracker.py` | 多轮状态追踪 |

---

## 10. Agent 集群

Agent 标准接口位于 `agents/base.py`，核心模型是 `TaskMessage` 和 `AgentResult`。所有 Agent 接收任务，返回状态、内容、置信度、metadata 和可选 trace。

主要 Agent：

| Agent | 文件 | 职责 |
|-------|------|------|
| DataAgent | `agents/data_agent.py` | 自然语言到 SQL、执行数据库查询、返回 rows/sql/explanation |
| RagAgent | `agents/rag_agent.py` | 文档块、LLMWiki、用户记忆检索；只返回证据，不直接生成最终答案 |
| WebAgent | `agents/web_agent.py` | 联网搜索与实时信息 |
| ToolAgent | `agents/tool_agent.py` | 工具路由，时间、天气、计算等结构化工具结果 |
| SkillsAgent | `agents/skills_agent.py` | 已安装技能、会话绑定技能的调用 |
| RuleEngineAgent | `agents/rule_engine_agent.py` | YAML 业务规则查询和规则执行 |
| VisionAgent | `agents/vision_agent.py` | 图片、图表、视觉内容理解 |

`agents/worker.py` 提供独立 worker，可从 Redis pub/sub 或 stream 消费 Agent 任务。这使 Agent 可以在 API 进程内执行，也可以走异步 Agent Bus。

---

## 11. 模型网关

模型统一入口是 `model/model_gateway/gateway.py`。

代码中的模型角色：

| Role | 代码名 | 主要用途 |
|------|--------|----------|
| Query | `QUERY` | 主回答生成 |
| Compress | `COMPRESS` | 上下文压缩 |
| Planning | `PLANNING` | 规划与任务拆解 |
| Router | `ROUTER` | L1 小模型路由 |
| Fast | `FAST` | 简单快速回答 |
| Cheap Critic | `CHEAP_CRITIC` | 轻量审校 |
| Knowledge | `KNOWLEDGE` | 知识问答 |
| Identity | `IDENTITY` | 身份类回答 |
| Vision | `VISION` | 视觉理解 |

网关能力：

- 每个 role 构造独立 `LLMConfig`。
- 使用 `OpenAICompatibleAdapter`，因此可以接 OpenAI-compatible 服务。
- 每个 role 有 Circuit Breaker，失败多次后短暂熔断。
- 有重试策略和异常分类。
- 有离线 fallback，确保模型不可用时仍能给出受控回答。
- 身份类回答经过 canonical identity 约束，减少模型漂移。

默认配置在 `infra/config/settings.py`，当前默认 provider 文案指向 DashScope/Qwen 系列。

---

## 12. 数据认知与 Text2SQL

数据源 API 在 `gateway/api_gateway/routers/databases.py` 和 `gateway/api_gateway/routers/data.py`。数据执行核心在 `agents/data_agent.py`、`execution/data/*`、`kernel/data_cognition/*`。

Text2SQL pipeline：

1. 通过 `DataSource` 读取数据源连接。
2. 加载 schema inspection 与 `DataSourceSchema.semantic_mappings`。
3. 根据 `source_type` 检测 SQL dialect。
4. `SemanticParser` 解析实体、指标、时间、过滤、排序、limit。
5. `QueryPlanner` 生成 `LogicalPlan`。
6. `SQLBuilder` 生成 SQL。
7. `SQLValidator` 做只读/limit/语义校验。
8. `QueryExecutor` 执行，失败时通过 `SQLRewriter` 重写重试。
9. `SQLReflector` 验证结果是否符合意图。
10. `explanation` 输出表、字段、SQL 解释和 warnings。

相关能力：

- 支持 structured intent，如表数量、表列表、表结构查询。
- 支持 join 推断：`TableRelationshipGraph`、外键注册、启发式路径。
- 支持 PostgreSQL/MySQL 等 dialect 适配。
- 支持 semantic layer：指标、维度、时间宏、SQL fragments。
- 支持 `NL2SQL_MODE=pipeline` 或 `llm_direct` fallback。

---

## 13. RAG 与文档系统

文档 API 在 `gateway/api_gateway/routers/documents.py`，RAG Agent 在 `agents/rag_agent.py`。

持久化模型：

- `Document`
- `DocumentChunk`
- `DocumentLLMWiki`

RAG 代码特征：

- 文档上传后解析为文本并分块。
- chunk 有 `embedding_json`，可选 pgvector `embedding_vector`。
- RAG 检索同时考虑文档 chunk、LLMWiki 问答项和用户记忆。
- `RagAgent` 会进行 query normalize、rewrite、同义词扩展、定义类问题识别。
- `DocumentEvidenceGate` 用于控制证据质量。
- Rerank 默认可以用 heuristic，也可配置 DashScope/API reranker。
- RAG Agent 返回 evidence、citations、metadata，最终答案仍由编排器/模型融合生成。

这意味着项目把 RAG 当成证据检索层，而不是最终回答层。

---

## 14. 记忆系统

记忆模块分布在 `memory/` 与 `infra/storage/models.py`。

主要类型：

| 类型 | 模块 | 说明 |
|------|------|------|
| WorkingMemory | `memory/working_memory` | 会话内短期轮次、scratchpad、身份缓存 |
| SemanticMemory | `memory/semantic_memory` | 语义向量检索，当前有 in-memory store |
| EpisodicMemory | `memory/episodic_memory` | 情节记忆，按 session 记录和回忆 |
| ProceduralMemory | `memory/procedural_memory` | 程序/流程型记忆 |
| EvolutionMemoryRouter | `memory/evolution/router.py` | 记忆演化、反馈、压缩、skill retrieve |
| UserMemory | DB 表 | 用户级长期记忆、标签、score、pinned/enabled |

关键机制：

- `MemoryRouter.retrieve()` 聚合多类记忆。
- `MemoryRouter.store()` 写入记忆。
- `ValueScorer` 根据反馈、访问、时间衰减等计算记忆分数。
- `memory_event_subscriber` 订阅 feedback/learning 事件，异步影响记忆。
- 用户可通过 `/memories/settings` 控制记忆学习和偏好学习。

---

## 15. 工具、技能、插件与连接器

### 15.1 工具系统

工具代码分散在：

- `kernel/tools/*`
- `tools/builtin_tools/*`
- `tools/registry/*`
- `execution/tool_router/router.py`

已显式出现的工具包括时间、天气、计算器、内置分析工具等。`ToolAgent` 会根据 query 自动选择工具，并把结果归一化为前端易渲染的 payload。

### 15.2 技能系统

技能模块：

- `skills/runtime/loader.py`
- `skills/runtime/manifest.py`
- `skills/runtime/verifier.py`
- `skills/store/marketplace.py`
- `gateway/api_gateway/routers/skills.py`

技能能力包括安装、创建、测试、卸载、会话绑定和会话技能列表。

### 15.3 插件系统

插件目录：

- `plugins/document_plugin.py`
- `plugins/document_retrieval.py`
- `plugins/web_plugin.py`
- `plugins/knowledge_plugin.py`
- `plugins/memory_plugin.py`
- `plugins/data/analysis.py`
- `plugins/chart/generator.py`
- `plugins/code/*`
- `plugins/tool/*`

插件更像能力实现或辅助能力，最终由 Agent 或 Kernel 调用。

### 15.4 连接器

连接器目录：

- `connectors/sdk`
- `connectors/builtin`
- `gateway/api_gateway/routers/connectors.py`

API 提供授权、回调、资源列表和同步入口。

---

## 16. 规则引擎

规则相关代码和数据：

- `agents/rule_engine_agent.py`
- `gateway/api_gateway/routers/rules.py`
- `rules/*.yml`
- `rules/{rule_id}/_meta.yml`
- `rules/{rule_id}/v*.yml`

规则 API 支持：

- 规则文件列表、读取、创建、更新、删除。
- 通过 LLM 或模板生成规则。
- 规则版本列表和新增版本。
- 灰度比例配置。
- promote 与 rollback。

代码视角下，规则引擎承担两类任务：

- 对业务规则类问题直接匹配或执行。
- 对产品目录、奖励规则等结构化业务知识提供可版本化的规则来源。

---

## 17. 执行平面与 Agent Bus

执行平面包括：

- `execution/dag_engine/*`：DAG graph、state、events、scheduler、engine、cognitive_nodes。
- `execution/workflow_engine/workflow.py`：工作流抽象。
- `execution/sandbox/sandbox.py` 与 `sandbox_runtime/*`：沙箱执行。
- `execution/tool_router/router.py`：工具路由。
- `execution/tool_selector.py`、`tool_ranker.py`、`tool_feedback.py`：工具选择、排序与反馈。

Agent Bus：

- `infra/message_bus/agent_bus.py` 提供 Redis pub/sub 和 stream 两种模式。
- `agents/worker.py` 可独立消费任务，执行后发布结果。
- `kernel/dispatcher.py` 根据配置决定本地执行或发布到 bus。
- 配置项包括 namespace、group、consumer、pending reclaim、DLQ、max retry。

这套机制使系统可以从单进程开发模式扩展到 API + worker 分离执行。

---

## 18. 安全、审计与可解释性

### 18.1 安全

安全模块：

- `infra/security/zero_trust.py`
- `safety/guardrails/guardrails.py`
- `safety/policy_engine/engine.py`
- `safety/masking/ner_masker.py`
- `safety/canary/canary_guard.py`

已有能力：

- JWT 登录态。
- bcrypt 密码哈希。
- 工具调用风险评估、权限令牌、异常检测。
- NER PII masking/unmasking。
- Canary 自动回滚阈值配置。
- 数据库主机规范化和允许列表判断。

### 18.2 审计

审计入口：

- `infra/audit/logger.py`
- `safety/audit/audit_logger.py`
- `gateway/api_gateway/routers/audit.py`
- DB 表 `audit_logs`

审计记录用户、动作、资源类型、资源 ID 和 payload。

### 18.3 可解释性

可解释性入口：

- `safety/xai/cognitive_trace.py`
- `gateway/api_gateway/routers/xai.py`
- `kernel/protocol/events.py`
- `infra/message_bus/cognitive_event_bus.py`
- `infra/message_bus/event_store.py`

系统会输出 routing、planning、execution、evidence、fusion、critic、feedback、learning 等认知事件，并支持按 trace/session 回放。

---

## 19. 基础设施与持久化

### 19.1 配置

`infra/config/settings.py` 通过多个 `BaseSettings` 组合成统一 `Settings`：

- DatabaseSettings
- RedisSettings
- LLMSettings
- EmbeddingSettings
- RerankSettings
- JWTSettings
- SMTPSettings
- OTelSettings
- AppSettings

### 19.2 数据库

`infra/storage/database.py` 创建 async engine 和 `AsyncSessionLocal`。生产应走 Alembic，`init_db()` 只适合开发/测试。

### 19.3 Redis

`infra/cache/redis_client.py` 包装 Redis，并实现 ShadowRedis：

- session/cache/memory/queue/rate-limit/pubsub 分 DB。
- 对 string/hash/list/set/zset/pubsub/stream 提供统一异步方法。
- 部分写入同步到 `redis_shadow_kv`，并可在 Redis miss 时 fallback 到 PostgreSQL 影子表。

### 19.4 消息总线

`infra/message_bus/*` 提供：

- 认知事件发布订阅。
- 事件持久化与 replay。
- Agent task/result bus。
- memory event subscriber。

### 19.5 可观测性

`infra/observability/*` 提供：

- logger
- tracer
- request context
- runtime metrics

Docker profile 中可开启 Prometheus 和 Jaeger。

---

## 20. 数据库模型

核心 ORM 均在 `infra/storage/models.py`。

| 表 | 模型 | 作用 |
|----|------|------|
| `users` | User | 用户、密码、活跃状态、超级用户标记 |
| `chat_sessions` | ChatSession | 会话、标题、轮次、归档 |
| `trace_logs` | TraceLog | 每轮 query/response、决策、模型、token、执行图 |
| `documents` | Document | 文档元数据、状态、策略 |
| `document_chunks` | DocumentChunk | 文档块、embedding、metadata |
| `document_llmwiki` | DocumentLLMWiki | 文档衍生问答条目 |
| `redis_shadow_kv` | RedisShadowKV | Redis 影子持久化 |
| `reasoning_traces` | ReasoningTrace | 推理阶段内容和分数 |
| `tool_stats` | ToolStat | 工具成功/失败/延迟 |
| `feedback` | Feedback | 用户反馈、纠正、评分 |
| `user_memories` | UserMemory | 用户长期记忆 |
| `user_memory_settings` | UserMemorySettings | 记忆学习开关 |
| `user_ui_settings` | UserUiSettings | UI 默认展开设置 |
| `task_definitions` | TaskDefinition | 任务定义 |
| `task_runs` | TaskRun | 任务运行记录 |
| `task_notifications` | TaskNotification | 任务通知 |
| `audit_logs` | AuditLog | 审计日志 |
| `data_sources` | DataSource | 外部数据库连接 |
| `data_source_schemas` | DataSourceSchema | schema 与语义映射 |
| `data_query_logs` | DataQueryLog | 数据查询日志 |
| `system_settings` | SystemSetting | 系统级键值配置 |

---

## 21. 配置项


### 21.X 自适应配置（Adaptive Profiles）

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `KERNEL_ADAPTIVE_MODE_ENABLED` | bool | `true` | 是否启用自适应模式 |
| `KERNEL_ADAPTIVE_PROFILE_JSON` | str | `""` | JSON 格式的自定义 profile 配置，覆盖默认值 |

**Profile 类型**:
- `speed`: 快速响应模式，降低推理阈值，允许更长草稿
- `balanced`: 平衡模式（默认），兼顾质量与速度
- `quality`: 高质量模式，提高阈值，限制草稿长度
- `identity`: 身份问答专用模式，最高置信度要求

**用户标签映射**:
用户可通过偏好标签动态调整回答风格：
| 标签类别 | 标签示例 | 影响参数 |
|----------|----------|----------|
| 简洁度 | `concise`, `简洁`, `brief` | 降低 `draft_max_chars` |
| 详细度 | `detailed`, `详细`, `verbose` | 增加 `draft_max_chars` |
| 技术深度 | `technical`, `专业`, `expert` | 设置 `technical_level=technical` |
| 通俗易懂 | `plain`, `通俗`, `simple` | 设置 `technical_level=plain` |
| 结构化 | `structured`, `列表`, `report` | 设置 `structure=structured` |
| 对话式 | `conversational`, `口语`, `casual` | 设置 `structure=conversational` |
| 正式语气 | `formal`, `正式`, `professional` | 设置 `tone=formal` |
| 友好语气 | `warm`, `友好`, `friendly` | 设置 `tone=warm` |


### 21.1 服务与端口

| 配置 | 默认值 | 说明 |
|------|--------|------|
| `APP_HOST` | `0.0.0.0` | 应用监听 host |
| `APP_PORT` | `14100` | API 端口 |
| `GATEWAY_PORT` | `14100` | 网关端口 |
| `FRONTEND_PORT` | `14108` | 前端端口 |
| `VITE_API_URL` | `http://localhost:14100` | 前端 API 地址 |
| `VITE_WS_URL` | `ws://localhost:14100` | 前端 WS/SSE 相关地址 |

### 21.2 存储

| 配置 | 说明 |
|------|------|
| `DATABASE_URL` | 主 PostgreSQL DSN，会自动把 `postgresql://` 修正为 asyncpg |
| `TOKEN_DB_URL` | token DB DSN |
| `REDIS_URL` | Redis 地址 |
| `REDIS_SESSION_DB` | session DB |
| `REDIS_CACHE_DB` | cache DB |
| `REDIS_MEMORY_DB` | memory DB |
| `REDIS_QUEUE_DB` | queue DB |
| `REDIS_RATE_LIMIT_DB` | rate limit DB |
| `REDIS_PUBSUB_DB` | pub/sub DB |

### 21.3 模型

| 配置组 | 作用 |
|--------|------|
| `DEFAULT_LLM_QUERY_*` | 主回答模型 |
| `DEFAULT_LLM_COMPRESS_*` | 压缩模型 |
| `DEFAULT_LLM_PLANING_*` | 规划模型 |
| `DEFAULT_LLM_SENIORSHORT_*` | knowledge/critic |
| `DEFAULT_LLM_MIDDLESHORT_*` | fast answer |
| `DEFAULT_LLM_JUNIORSHORT_*` | tiny/router |
| `DEFAULT_LLM_MINSHORT_*` | identity |
| `DEFAULT_LLM_VISION_*` | vision |
| `EMBEDDING_*` | embedding provider/model/dims/api |
| `RERANK_*` | rerank provider/model/api |

### 21.4 内核开关

重点开关：

- `KERNEL_ORCHESTRATOR_VERSION`
- `KERNEL_AGENT_ENABLED`
- `KERNEL_AGENT_DATA_ENABLED`
- `KERNEL_AGENT_TOOL_ENABLED`
- `KERNEL_AGENT_WEB_ENABLED`
- `KERNEL_AGENT_RAG_ENABLED`
- `KERNEL_ADAPTIVE_MODE_ENABLED`
- `KERNEL_PLAN_MEMORY_ENABLED`
- `KERNEL_MEMORY_CONTEXT_ENABLED`
- `KERNEL_ENRICHED_IDENTITY_ENABLED`
- `KERNEL_AGENT_DAG_SCHEDULING_ENABLED`
- `KERNEL_AGENT_SPECULATIVE_EXECUTION_ENABLED`
- `KERNEL_AGENT_BUS_ENABLED`
- `KERNEL_V5_ROUTING_ENABLED`
- `KERNEL_L0_RULE_ROUTER_ENABLED`
- `KERNEL_L1_TINY_ROUTER_ENABLED`
- `KERNEL_SEMANTIC_CACHE_ENABLED`
- `KERNEL_CLARIFICATION_GATE_ENABLED`
- `KERNEL_REFINE_REPLAN_ENABLED`
- `KERNEL_CONTEXT_COMPOSER_ENABLED`
- `KERNEL_REVISE_LOOP_ENABLED`
- `KERNEL_USER_PROFILING_ENABLED`

### 21.5 数据查询

- `TEXT2SQL_ENABLED`
- `TEXT2SQL_MAX_RETRY`
- `TEXT2SQL_DEFAULT_LIMIT`
- `TEXT2SQL_JOIN_INFERENCE_ENABLED`
- `TEXT2SQL_MAX_JOIN_DEPTH`
- `DATA_SECRET_KEY`
- `DOCKER_HOST_ALIAS`

### 21.6 安全和附件

- `JWT_SECRET`
- `JWT_EXPIRE_MINUTES`
- `ATTACHMENT_UPLOAD_ENABLED`
- `ATTACHMENT_MAX_SIZE_MB`
- `ATTACHMENT_STORAGE_PATH`
- `ATTACHMENT_MAX_CHARS`
- `MULTIMODAL_ATTACHMENT_ENABLED`
- `KERNEL_NER_MASKING_ENABLED`
- `KERNEL_NER_MASKING_ENTITY_TYPES`
- `KERNEL_CANARY_AUTO_ROLLBACK_ENABLED`

---

## 22. 部署与运行

### 22.1 Docker Compose

`docker-compose.yml` 定义：

- `postgres`：`pgvector/pgvector:pg16`
- `redis`：`redis:7-alpine`
- `api`：构建 `deploy/docker/Dockerfile`，端口 `14100`
- `agent-worker`：命令 `python -m agents.worker`
- `prometheus`：profile `observability`
- `jaeger`：profile `observability`

API 与 worker 使用相同镜像，但命令不同。

### 22.2 启动

```bash
bash start.sh
```

带观测组件：

```bash
bash start.sh --with-observability
```

启动后脚本会检查：

- `http://127.0.0.1:14100/api/v1/health`
- `http://127.0.0.1:14100/api/v1/health/deps`
- PostgreSQL 中 `public.users` 表是否存在

### 22.3 停止

```bash
bash stop.sh
```

删除 volumes：

```bash
bash stop.sh --volumes
```

### 22.4 前端开发

```bash
cd frontend
npm install
npm run dev
```

默认端口是 `14108`。

### 22.5 后端本地运行

根据代码和依赖，后端 ASGI 入口是：

```bash
uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100
```

本地运行需要提前准备 `.env`、PostgreSQL、Redis 和 Alembic migration。

---

## 23. 测试体系

测试目录以合同测试为主，覆盖很多系统边界：

- API 合同：auth、chat、tasks、documents、databases、skills、memories、ui settings。
- Kernel/Orchestrator：V4、V5 routing、多子问题、DAG、stream fallback、critic、fusion。
- Data Cognition：Text2SQL、schema inspector、join planner、semantic layer、validator、ranker、postprocess。
- RAG：文档检索、LLMWiki、RAG fusion、web fallback。
- Safety：zero trust、NER masking、canary rollback、chain-of-thought contract。
- Frontend：tool cards、epistemic badge、structured render。
- Infra：Alembic 幂等、health runtime metrics、agent bus。

常用命令：

```bash
python -m pytest -q
```

前端：

```bash
cd frontend
npm test
```

项目也提供脚本：

```bash
bash scripts/verify_all.sh
bash scripts/verify_docker.sh
bash scripts/verify_all_docker.sh
bash scripts/preflight_release.sh
```

---

## 24. 代码视角的关键判断

1. **CognitiveKernel 是唯一中枢，不应绕过。**
   `chat.py` 注释、guard 和调用方式都表明直接 LLM 调用不是主设计。

2. **RAG 和 DataAgent 都是证据/材料生产者。**
   RagAgent 明确不生成最终答案；DataAgent 返回 SQL、rows、explanation。最终自然语言表达由编排器融合。

3. **项目已经从单 Agent 走向多 Agent 编排。**
   `PlanAgent`、`Dispatcher`、`DAG Scheduler`、`Agent Bus` 同时存在，说明系统目标是支持并发、依赖、worker 分离和复杂任务拆解。

4. **V5 路由是性能优化层。**
   L0 规则、语义缓存、Tiny Router、FAST/KNOWLEDGE role 的存在说明系统试图减少完整管线调用。

5. **前端不是普通聊天壳。**
   它渲染推理链、DAG、工具卡片、数据表图表、多子问题卡片、引用和认知标注，因此后端协议必须保持结构化。

6. **Redis 被设计为高速态，PostgreSQL 是长期态。**
   ShadowRedis 和 `redis_shadow_kv` 表说明关键 Redis 数据可以双写/回退。

7. **规则、技能、连接器是扩展面。**
   这些能力不是核心问答路径必须项，但为业务定制和外部资源接入提供可扩展接口。

8. **安全和审计不是事后附加。**
   工具权限令牌、PII masking、canary、XAI、审计日志都已经接入主要目录和测试。

---

## 25. 排障入口

### 25.1 API 不通

检查：

```bash
curl -f http://127.0.0.1:14100/api/v1/health
curl -f http://127.0.0.1:14100/api/v1/health/deps
docker compose logs --tail=200 api
```

### 25.2 数据库异常

检查：

```bash
docker compose ps postgres
docker compose logs --tail=200 postgres
docker compose exec -T api alembic upgrade head
```

重点关注：

- `DATABASE_URL`
- `TOKEN_DB_URL`
- asyncpg driver 是否正确
- `data_sources` 中 host 在容器内是否可达

### 25.3 Redis/事件异常

检查：

```bash
docker compose ps redis
docker compose logs --tail=200 redis
```

重点关注：

- Redis DB index 是否超出服务限制。
- Agent Bus 是 pubsub 还是 stream。
- worker 是否启动。

### 25.4 模型不可用

检查：

- `DEFAULT_LLM_*_API_KEY`
- `DEFAULT_LLM_*_BASE_URL`
- proxy/no_proxy 配置
- ModelGateway circuit breaker 是否进入 open 状态

系统有离线 fallback，但复杂任务质量会显著下降。

### 25.5 Text2SQL 结果异常

检查：

- 数据源连接是否成功。
- schema 是否已同步。
- `DataSourceSchema.semantic_mappings` 是否正确。
- `NL2SQL_MODE` 是 `pipeline` 还是 `llm_direct`。
- 生成 SQL 是否被 validator 改写或拒绝。

### 25.6 RAG 检索不到

检查：

- 文档状态是否 ready。
- chunk_count 是否大于 0。
- embedding dims 是否与配置一致。
- rerank provider 是否可用。
- query 是否被 rewrite 后偏离原意。

### 25.7 前端渲染异常

检查：

```bash
cd frontend
npm run build
npm test
```

重点关注：

- SSE final_answer 结构。
- `execution_graph`、`citations`、`annotations` 是否为前端预期 shape。
- 工具 payload 是否包含 `type` 和可渲染字段。

---


---

## 26. 新增功能：自适应配置系统（2026-05）

### 26.1 功能概述

自适应配置系统允许根据用户偏好动态调整回答风格，无需修改代码或重启服务。

### 26.2 核心模块

| 模块 | 路径 | 职责 |
|------|------|------|
| Profile 定义 | `kernel/adaptive_profiles.py` | 定义默认 profile 和标签映射规则 |
| 配置加载 | `infra/config/settings.py` | 从环境变量加载自定义 profile JSON |
| 标签应用 | `kernel/adaptive_profiles.py:apply_user_tags()` | 将用户标签转换为 profile 参数 |

### 26.3 使用方式

#### 方式1: 环境变量配置自定义 profile

```bash
# .env
KERNEL_ADAPTIVE_PROFILE_JSON='{
  "speed": {
    "draft_threshold": 0.60,
    "draft_max_chars": 500
  },
  "custom_mode": {
    "draft_threshold": 0.70,
    "rag_min_score": 0.45,
    "max_parallel": 4
  }
}'
```

#### 方式2: 用户偏好标签

前端在请求时传递用户标签：
```json
{
  "query": "解释量子计算",
  "user_preference_tags": ["technical", "structured", "concise"]
}
```

后端自动调整：
- 技术深度 → 使用专业术语和详细解释
- 结构化 → 使用列表/表格组织内容
- 简洁 → 控制回答长度在 200 字符内

### 26.4 扩展指南

添加新标签类别：
```python
# kernel/adaptive_profiles.py
_MY_NEW_TAGS = {"tag1", "tag2", "中文标签"}

def apply_user_tags(profile, user_tags):
    # ... 现有代码 ...
    if tags_lower & _MY_NEW_TAGS:
        p["my_new_param"] = "custom_value"
    return p
```

### 26.5 调试技巧

```bash
# 查看当前生效的 profile
curl -s http://localhost:14100/api/v1/health | jq '.adaptive_profile'

# 测试标签效果
python3 -c "
from kernel.adaptive_profiles import get_profile_defaults, apply_user_tags
p = get_profile_defaults('balanced')
p = apply_user_tags(p, ['technical', 'concise'])
print(p)
"
```



---

## 27. 近期修复与前端更新（2026-05-09）

### 27.1 删除会话外键约束修复

**问题**: 删除会话时因关联表残留数据导致 `服务内部错误`

**修复位置**: `gateway/api_gateway/routers/conversations.py:306-325`

**变更内容**:
```python
# 显式删除 TraceLog 关联记录
trace_result = await db.execute(
    select(TraceLog).where(TraceLog.session_id == conversation_id)
)
for trace in trace_result.scalars().all():
    await db.delete(trace)
if traces:
    await db.flush()

# 清理无外键约束的关联表（新增 Feedback）
for model in (ReasoningTrace, ToolStat, Feedback):  # ← 添加 Feedback
    orphan_result = await db.execute(
        select(model).where(model.session_id == conversation_id)
    )
    for row in orphan_result.scalars().all():
        await db.delete(row)
await db.flush()
```

**关联表清理清单**:
| 表名 | 外键约束 | 清理策略 |
|------|----------|----------|
| `ConversationState` | ✅ CASCADE (passive_deletes) | 优先删除 |
| `Attachment` | ✅ CASCADE | 显式删除兜底 |
| `TraceLog` | ✅ CASCADE | 显式删除兜底 |
| `ReasoningTrace` | ❌ 无 | 必须显式删除 |
| `ToolStat` | ❌ 无 | 必须显式删除 |
| `Feedback` | ❌ 无 | ✅ 已修复 |

### 27.2 前端聊天组件更新

**更新文件**:
- `frontend/src/components/ChatMessage.tsx`: 增强工具卡片渲染和错误处理
- `frontend/src/components/ChatInput.tsx`: 添加附件上传状态反馈
- `frontend/src/api/client.ts`: 优化 SSE 连接重试逻辑

**新功能**:
1. **工具卡片渲染**: 支持展示 DataAgent/ToolAgent 返回的结构化工具结果
2. **错误降级提示**: 当后端返回 `setup_error` 时，前端显示友好降级文案
3. **附件状态同步**: 上传中的附件显示进度，失败时可重试

### 27.3 配置项新增

**新增配置** (`infra/config/settings.py`):
```python
# 前端相关
FRONTEND_API_TIMEOUT: int = 30000  # 前端 API 请求超时(ms)
FRONTEND_SSE_RECONNECT: bool = True  # 是否启用 SSE 自动重连

# 聊天相关
CHAT_DEFAULT_STREAM: bool = True  # 默认启用流式响应
CHAT_FALLBACK_MESSAGE: str = "抱歉，服务暂时不可用，请稍后重试。"
```

### 27.4 排查建议

若仍遇到 `服务暂时不可用` 错误：

```bash
# 1. 查看网关日志
tail -f /Users/tuwan/work/code/agentos/opentrace/logs/app.log | grep "Chat endpoint setup failed"

# 2. 检查依赖服务
docker compose ps postgres redis api

# 3. 验证数据库连接
docker compose exec -T api python -c "
from infra.storage.database import AsyncSessionLocal
import asyncio
async def test():
    async with AsyncSessionLocal() as db:
        await db.execute('SELECT 1')
asyncio.run(test())
print('DB OK')
"

# 4. 检查模型配置
echo $DEFAULT_LLM_QUERY_API_KEY | head -c 10
curl -H "Authorization: Bearer $DEFAULT_LLM_QUERY_API_KEY" $DEFAULT_LLM_QUERY_BASE_URL/v1/models | head
```


## 结论

从代码看，OpenTrace 当前是一个“认知网关 + 多 Agent 执行平面 + 结构化证据融合”的系统。它的核心资产不是某一个模型调用，而是围绕用户请求建立的完整控制流：路由、规划、执行、证据、融合、审校、追踪、记忆和反馈。

维护该项目时，优先保证三条链路稳定：

- `/api/v1/chat` 到 `CognitiveKernel` 到 `OrchestratorV4` 的主链路。
- `DataAgent` 的 schema/Text2SQL/SQL 执行链路。
- `RagAgent` 的文档/记忆/引用证据链路。

只要这三条链路结构清晰，技能、规则、连接器、工具和可观测性都可以作为扩展层逐步增强。
