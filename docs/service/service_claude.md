# OpenTrace 项目代码梳理

> 以当前仓库代码为唯一事实来源，从零梳理全项目架构与实现。
> 不参考历史文档，所有结论来自对代码、配置和测试的直接阅读。
>
> 最后更新：2026-05-28

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
10. [V5 路由层](#10-v5-路由层)
11. [V4 编排器与多轮增强](#11-v4-编排器与多轮增强)
12. [AI Runtime 统一运行时](#12-ai-runtime-统一运行时)
13. [Agent 集群](#13-agent-集群)
14. [DataAgent V2 认知型数据智能体](#14-dataagent-v2-认知型数据智能体)
15. [数据源、Knowledge Assets 与 Text2SQL](#15-数据源knowledge-assets-与-text2sql)
16. [RAG 与文档系统](#16-rag-与文档系统)
17. [记忆系统](#17-记忆系统)
18. [Capability Intelligence](#18-capability-intelligence)
19. [工具、技能、插件与连接器](#19-工具技能插件与连接器)
20. [规则引擎与灰度发布](#20-规则引擎与灰度发布)
21. [执行平面与 Agent Bus](#21-执行平面与-agent-bus)
22. [模型网关](#22-模型网关)
23. [安全、审计与可解释性](#23-安全审计与可解释性)
24. [基础设施与持久化](#24-基础设施与持久化)
25. [数据库模型](#25-数据库模型)
26. [配置项](#26-配置项)
27. [部署与运行](#27-部署与运行)
28. [测试体系](#28-测试体系)
29. [开发规范与维护建议](#29-开发规范与维护建议)
30. [已知风险与后续优化](#30-已知风险与后续优化)

---

## 1. 项目定位

OpenTrace 是一个以 **Cognitive Kernel** 为中枢的 Agent 操作系统（AgentOS）。核心特征：

- **统一认知入口**：所有对话经过 `kernel/cognitive_kernel.py` 的 `CognitiveKernel.run()` / `stream()` 方法。
- **意图锁定（Intent Lock）**：零 LLM 的确定性分类层 `kernel/cognitive_controls.py`，在请求进入任何编排器之前锁定允许/禁止的能力集合、认知预算和复杂度等级。
- **分层路由**：L0 规则（零 LLM）→ L0.5 语义缓存（embedding 相似度）→ L1 TinyRouter（1.7B 轻量 LLM）→ 复杂任务进入完整编排管线。
- **双运行时并存**：
  - **V4 编排器**（`kernel/orchestrator_v4.py`）：稳定默认路径，Plan → Dispatch → Fusion → Critic。
  - **Cognitive Runtime V2**（`kernel/runtime/`）：新一代统一管线，CognitiveExecutive → CognitivePlannerV2 → ExecutionRuntime → EvidenceBus → Fusion/Critic → ArtifactComposer。
- **多 Agent 集群**：Data（V1/V2）、RAG、Web、Tool、Skills、RuleEngine、Vision 七个 Agent，由 Dispatcher 或 ExecutionRuntime 调度。
- **Capability Intelligence**：从 "tool calling" 升级为 "capability cognition"，Planner 看到的是能力画像而非工具名。
- **证据优先**：RAG、Data、Web 的输出先作为 Evidence 进入融合/审校管线，经过 answerability gate 和 relevance anchor 后才形成最终回答。

---

## 2. 当前代码状态摘要

| 维度 | 状态 |
|------|------|
| 后端入口 | FastAPI，默认端口 `14100` |
| 前端入口 | React 18 + Vite + TypeScript，默认端口 `14108` |
| 主聊天端点 | `POST /api/v1/chat`，支持同步和 SSE 流式 |
| Kernel 主入口 | `kernel/cognitive_kernel.py` — `CognitiveKernel` 类 |
| 稳定编排器 | `kernel/orchestrator_v4.py` — `CognitiveOrchestratorV4`（~3340 行） |
| 新运行时 | `kernel/runtime/cognitive_executive.py` — `CognitiveExecutive` |
| 意图锁定 | `kernel/cognitive_controls.py` — `IntentLock` + `classify_intent()` |
| 分层路由 | `query_router_v2.py`（L0）、`tiny_router.py`（L1）、`complexity_engine.py`、`semantic_cache.py` |
| DataAgent | V2 默认启用，V1 保留作为 fallback |
| RAG | 文档 chunk + LLMWiki + memory，pgvector，可选的 neural rerank |
| 记忆 | working / episodic / semantic / procedural / temporal / evolution，六层记忆体系 |
| Capability Intelligence | Phase 1（profiler + adapter + feedback）+ Phase 2（KG + reasoner + execution/strategy memory + evolution） |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存/队列 | Redis 7，6 个逻辑 DB 分片 |
| 部署 | Docker Compose（4 核心服务 + 2 可选可观测性服务） |

关键默认配置（`infra/config/settings.py`）：

```text
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
```

---

## 3. 技术栈

### 3.1 后端

| 类别 | 技术 |
|------|------|
| 语言 | Python 3.11+ |
| Web 框架 | FastAPI + Uvicorn |
| ASGI | uvicorn[standard] |
| ORM | SQLAlchemy 2.0+ asyncio，asyncpg |
| 迁移 | Alembic |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存/队列 | Redis 7，hiredis |
| LLM SDK | OpenAI-compatible API、DashScope（阿里通义千问 qwen3 系列） |
| 配置 | pydantic-settings + `.env` |
| SQL 工具 | sqlglot、自研 `kernel/data_cognition/` |
| 可观测 | OpenTelemetry（API/SDK/FastAPI/SQLAlchemy/Redis/httpx 插桩 + OTLP-gRPC）、Prometheus、Jaeger、structlog |
| 安全 | JWT（python-jose）、bcrypt（passlib）、host guard、PII masking（NER）、tool permission token |
| 序列化 | pydantic v2、orjson |
| 任务队列 | Celery + Redis、aio-pika（RabbitMQ） |
| 数值计算 | numpy、scipy、networkx |

### 3.2 前端

| 类别 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite |
| 路由 | react-router-dom |
| 状态管理 | Zustand |
| Markdown | react-markdown + remark-gfm + rehype-raw + shiki |
| 图表 | Recharts |
| 图标 | lucide-react |
| 测试 | Vitest + Testing Library |

### 3.3 基础设施

| 组件 | 容器/端口 |
|------|-----------|
| API | `opentrace_api`，`14100` |
| Agent Worker | `opentrace_agent_worker` |
| PostgreSQL | `opentrace_postgres`，host `${POSTGRES_PORT:-5432}` |
| Redis | `opentrace_redis`，host `${REDIS_PORT:-6380}` |
| Prometheus | observability profile，`14190` |
| Jaeger | observability profile，UI `14186`，OTLP `4317` |

---

## 4. 整体架构

```text
┌──────────────────────────────────────────────────────────┐
│ Frontend: React/Vite                                      │
│ Chat / Databases / Documents / Skills / Rules / Memory    │
└─────────────────────────┬────────────────────────────────┘
                          │ HTTP / SSE
                          ▼
┌──────────────────────────────────────────────────────────┐
│ API Gateway: FastAPI /api/v1                              │
│ 21 routers: chat, auth, documents, databases, skills ...  │
└─────────────────────────┬────────────────────────────────┘
                          │ ChatRequest → KernelRequest
                          ▼
┌──────────────────────────────────────────────────────────┐
│ CognitiveKernel                                            │
│ classify_intent() → Intent Lock → L0 → Cache → L1 →       │
│ Context Assembly → CognitiveExecutive / OrchestratorV4     │
└─────────────────────────┬────────────────────────────────┘
                          │
        ┌─────────────────┴──────────────────┐
        ▼                                    ▼
┌───────────────────────┐      ┌──────────────────────────┐
│ CognitiveExecutive     │      │ CognitiveOrchestratorV4   │
│ (V2 Runtime)           │      │ (V4 Stable)               │
│ Rewrite → Understand → │      │ Plan → Dispatch →         │
│ Plan → Execute →       │      │ Agent Results →           │
│ Evidence → Fusion →    │      │ Fusion → Critic →         │
│ Critic → Artifact      │      │ Validator → Annotate      │
└───────────┬───────────┘      └───────────┬──────────────┘
            │                              │
            ▼                              ▼
┌──────────────────────────────────────────────────────────┐
│ Agent Cluster + Capability Intelligence                    │
│ Data / RAG / Web / Tool / Skills / Rule / Vision           │
│ CapabilityProfiler / KnowledgeGraph / ExecutionMemory      │
└─────────────────────────┬────────────────────────────────┘
                          │
                          ▼
┌──────────────────────────────────────────────────────────┐
│ PostgreSQL + pgvector / Redis / Model Gateway / Audit      │
└──────────────────────────────────────────────────────────┘
```

系统分为六个逻辑层：

1. **交互层**：React/Vite 前端，SSE 流式消费，推理链和执行图可视化。
2. **网关层**：FastAPI 路由、认证、会话、附件、权限、错误封装。
3. **认知层**：Intent Lock、Cognitive Budget、分层路由、规划、对话状态、上下文拼装。
4. **执行层**：Agent 集群、工具、数据查询、RAG、DAG 引擎、sandbox。
5. **模型层**：按 LLMRole 调度 LLM、Embedding、Rerank、Vision。
6. **基础设施层**：PostgreSQL、Redis、审计、事件、可观测、部署脚本。

---

## 5. 目录结构

```text
opentrace/
├── agent_runtime/              # Agent 运行时、planner、executor、critic、market、reflector
├── agents/                     # 7 个 Agent：Data/RAG/Web/Tool/Skills/Rule/Vision
│   ├── data_agent_v2/           # DataAgent V2 三层认知数据管道（14+ 子 agent）
│   └── worker.py                # Agent Bus worker 消费进程
├── alembic/                    # Alembic 迁移版本
├── connectors/                 # 连接器 SDK 与内置连接器
├── deploy/                     # Docker、Helm、K8s、Prometheus 配置
├── docs/                       # 项目文档
├── evolution/                  # 学习、反馈、self-play、meta-learning
├── execution/                  # DAG 引擎、workflow、sandbox、tool router、SQL executor
├── frontend/                   # React/Vite 前端
├── gateway/                    # 两层网关
│   ├── api_gateway/             # FastAPI REST 网关（21 个 router）
│   └── cognitive_gateway/       # 认知感知网关
├── infra/                      # 基础设施
│   ├── config/settings.py       # 约 250 个配置开关（pydantic-settings）
│   ├── storage/models.py        # 33 个 ORM 模型
│   ├── cache/                   # Redis 客户端
│   ├── security/                # JWT、PII masking
│   ├── audit/                   # 审计基础设施
│   ├── observability/           # structlog、Prometheus、OTel
│   └── message_bus/             # 进程间消息总线
├── kernel/                     # 认知内核（核心编排）
│   ├── cognitive_kernel.py      # 主入口
│   ├── cognitive_controls.py    # Intent Lock / CognitiveBudget / classify_intent
│   ├── orchestrator_v4.py       # V4 编排器（~3340 行）
│   ├── plan_agent.py            # 计划生成（标记为 DEPRECATED，被 V2 Runtime 取代）
│   ├── runtime/                 # Cognitive Runtime V2（~45 文件，~9900 行）
│   ├── capability_intelligence/ # 能力智能层（12 文件，~2500 行）
│   ├── data_cognition/          # SQL planning / validation / dialect / semantic layer
│   ├── fusion_engine/           # 融合引擎
│   ├── critic_engine/           # 审校引擎
│   ├── epistemology/            # 认识论标注
│   ├── identity/                # 系统身份与角色执行
│   └── policy/                  # 运行时策略引擎（bandit + RL）
├── memory/                     # 六层记忆体系（~15 文件）
│   ├── working_memory/          # 工作记忆（Redis ring-buffer）
│   ├── episodic_memory/         # 情景记忆（Redis 追加日志）
│   ├── semantic_memory/         # 语义记忆（内存向量存储）
│   ├── procedural_memory/       # 程序记忆
│   ├── temporal_memory/         # 时序索引（指数衰减）
│   ├── memory_router/           # 统一检索路由
│   └── evolution/               # 记忆演进、治理、路由增强
├── model/                      # 模型网关
│   ├── model_gateway/gateway.py  # LLMRole 枚举 + ModelGateway 单例
│   ├── llm_adapter/             # OpenAI-compatible adapter
│   ├── embedding/               # 多后端 embedder（DashScope/API/Local/Hash）
│   └── reranker/                # 多后端 reranker（DashScope/API/Heuristic BM25）
├── plugins/                    # 文档/Web/知识/记忆/工具/代码/图表插件
├── safety/                     # 安全防护：guardrails、PII masking、canary、XAI、audit
├── sandbox_runtime/            # 沙箱执行环境
├── scripts/                    # 启停、验证、迁移、schema 同步脚本
├── sdk/                        # 插件/Python SDK
├── services/                   # 文件解析等服务层辅助模块
├── skills/                     # 技能运行时、商店、已安装技能
├── tests/                      # 94 个测试文件，~10200 行，803 个用例
├── tools/                      # 工具注册表和内置工具
├── docker-compose.yml
├── requirements.txt
├── start.sh / stop.sh / restart.sh
└── CLAUDE.md
```

---

## 6. 前端应用

入口：`frontend/src/main.tsx` → `App.tsx` → `api/client.ts`

### 6.1 页面清单

| 页面 | 组件文件 | 功能 |
|------|----------|------|
| ChatPage | `ChatPage.tsx` | 主聊天界面，同步/SSE、推理链、执行图、附件、快捷模式 |
| DatabasesPage | `DatabasesPage.tsx` | 数据源 CRUD、连接测试、schema 同步、语义配置 |
| KnowledgeAssetsPage | `KnowledgeAssetsPage.tsx` | 知识资产管理 |
| DocumentsPage | `DocumentsPage.tsx` | 文档上传、列表、预览、删除、检索 |
| SkillsPage | `SkillsPage.tsx` | 技能市场、创建、安装、测试、会话绑定 |
| RulesPage | `RulesPage.tsx` | 规则管理、版本、灰度、发布/回滚 |
| MemoryPage | `MemoryPage.tsx` | 用户记忆、记忆设置 |
| TasksPage | `TasksPage.tsx` | 任务定义、运行、事件触发、通知 |
| AuditPage | `AuditPage.tsx` | 审计日志查询 |
| IntegrationsPage | `IntegrationsPage.tsx` | 外部连接器管理 |
| SettingsPage | `SettingsPage.tsx` | UI/用户设置 |
| LoginPage / RegisterPage | `LoginPage.tsx` / `RegisterPage.tsx` | 登录注册 |

### 6.2 核心组件

| 组件 | 功能 |
|------|------|
| `ChatInput.tsx` | 输入框、斜杠命令、附件上传、发送控制 |
| `ChatMessage.tsx` | 消息渲染、工具卡片、JSON/Markdown/表格结构化显示 |
| `MessageList.tsx` | 消息列表 |
| `ReasoningChain.tsx` | 推理链展示 |
| `ExecutionGraphPanel.tsx` | 执行图展示 |
| `DagTimeline.tsx` | DAG 时间线 |
| `DecisionTraceCard.tsx` | 决策轨迹卡片 |
| `DataQueryResult.tsx` | 数据查询结果展示 |
| `DataTableChart.tsx` | 表格/图表切换 |
| `MetricDefinitionEditor.tsx` | 指标定义编辑 |
| `TableRelationGraph.tsx` | 表关系图展示 |

### 6.3 数据流

```text
ChatInput
  → apiChatStream / apiChatSync
  → POST /api/v1/chat
  → SSE: delta / reasoning_step / tool_call / final_answer
  → Zustand chat store
  → ChatMessage / ReasoningChain / ExecutionGraphPanel
```

---

## 7. API 网关

入口：
- `gateway/api_gateway/main.py` — FastAPI 应用，版本 `0.1.0`
- `gateway/api_gateway/routers/chat.py` — 聊天主入口（~102KB）

### 7.1 中间件

- `CORSMiddleware` — 允许所有来源
- `request_context_middleware` — 注入 `x-request-id` 和 `x-response-time-ms`
- 异常处理器：`AppException`（业务异常）和 `Exception`（内部错误），均返回结构化错误 envelope

### 7.2 Router 清单（均位于 `/api/v1` 前缀）

| Router | Tag | 核心功能 |
|--------|-----|----------|
| `chat.py` | chat | 核心聊天（同步/流式）、附件、停止、反馈、再生成、编辑再生、图控制 |
| `auth.py` | auth | 注册、登录、JWT 令牌 |
| `conversations.py` | conversations | 会话 CRUD、分支、消息版本树 |
| `documents.py` | documents | 文档上传、搜索、详情、删除 |
| `databases.py` | databases | 数据源 CRUD、连接测试、schema 同步 |
| `data.py` | data | 数据查询 API |
| `metrics.py` | metrics | 指标定义 CRUD |
| `table_relationships.py` | table-relationships | 表关系管理 |
| `analytical_skills.py` | analytical-skills | 分析技能管理 |
| `memories.py` | memories | 记忆 CRUD 与设置 |
| `skills.py` | skills | 技能安装、测试、会话绑定 |
| `rules.py` | rules | 规则引擎管理 |
| `tasks.py` | tasks | 任务定义与运行 |
| `audit.py` | audit | 审计日志查询 |
| `feedback.py` | feedback | 用户反馈 |
| `connectors.py` | connectors | 连接器管理 |
| `sandbox.py` | sandbox | 沙箱执行 |
| `ui_settings.py` | ui_settings | UI 设置 |
| `health.py` | health | 基础/依赖/运行时三级健康检查 |
| `cognitive.py` | cognitive | 认知事件查询 |
| `admin.py` | admin | 管理面板 |

### 7.3 ChatRequest 关键字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | `str` (1-8192 chars) | 用户输入 |
| `session_id` | `str \| None` | 会话 ID，未提供则自动创建 |
| `stream` | `bool` | 是否 SSE 流式 |
| `web_enabled` | `bool` | 是否允许联网搜索 |
| `force_mode` | `string enum \| None` | 强制路由：rag/data_query/data_analysis/anomaly_tracking/product/rule_engine/vision |
| `data_source_id` | `str \| None` | 指定数据源 |
| `attachment_ids` | `list[str] \| None` | 附件上下文 |
| `parent_message_id` | `str \| None` | 对话分支的父消息 ID |
| `clarify_context` | `str \| None` | 主动追问补充信息 |
| `clarify_question_id` | `str \| None` | 澄清问题 ID |
| `enabled_skills` / `disabled_skills` | `list[str]` | 会话技能控制 |
| `tool_permission_token` | `str \| None` | 工具权限令牌 |
| `confirmation_granted` | `bool` | 高风险操作已确认 |

### 7.4 健康检查端点

| 端点 | 功能 |
|------|------|
| `GET /api/v1/health` | 基础 liveness：status、version、uptime |
| `GET /api/v1/health/deps` | 依赖健康：PostgreSQL（`SELECT 1`）、Redis（`PING`）、Agent Bus、Worker heartbeat |
| `GET /api/v1/health/runtime` | 运行时指标：WorldModel entity 数、avg agent latency、avg first token ms、supervisor retry 总数 |
| `GET /api/v1/ping` | 简单心跳 `{"pong": true}` |

---

## 8. 聊天主链路

### 8.1 同步路径

```text
POST /api/v1/chat
  → chat.py: chat()
  → 认证 / 会话确认 / 对话历史加载 / 分支检查点
  → Zero-Trust 风险评估 + permission token
  → 数据源解析 / 附件内容加载 / ConversationState 恢复
  → RuntimeContext 构建 → KernelRequest
  → CognitiveKernel.run()
      1. classify_intent() → IntentLock + CognitiveBudget
      2. direct_answer_for_intent() — capability_help/usage_help 短接
      3. WorkingMemory identity cache 检查
      4. 【V5 Routing Tier】
         L0: L0RuleRouter.route() — 零 LLM 正则匹配
         L0.5: SemanticCache.lookup() — embedding 相似度检查
         L1: ComplexityEngine.assess() + TinyRouter.route()
      5. memory context 注入（按 CognitiveBudget 预算）
      6. SelfModel.introspect() — 能力自省
      7. ContextAssembler.assemble() — 结构化上下文组装
      8. CognitiveExecutive.execute() — V2 Runtime 路径（优先）
         ↓ 异常则 fallback
      9. CognitiveOrchestratorV4.process() — V4 经典路径
      10. TraceLog / Message / Memory 写回
  → ChatResponse
```

### 8.2 流式路径

```text
POST /api/v1/chat (stream=true)
  → CognitiveKernel.stream()
  → 跳过 V2 CognitiveExecutive，始终走 V4 编排器
  → SSE 输出：
      {"type": "delta", "data": {"text": "..."}}           # 增量文本
      {"type": "reasoning_step", "data": {...}}             # 推理步骤
      {"type": "tool_call", "data": {...}}                  # 工具调用
      {"type": "final_answer", "data": {...}}               # 最终答案
```

### 8.3 关键特性

- 支持斜杠命令：`/rag`、`/data`、`/web`、`/tools`、`/skills`、`/vision`、`/anomaly`、`/rule`
- 支持附件上传（txt/md/csv/tsv/pdf/docx/xlsx/json/代码/图片），自动解析注入上下文
- 支持对话分支（`parent_message_id`）、消息版本历史
- 支持主动追问（ClarificationGate）、纠正重规划（RefinePlanner）
- 支持工具权限令牌和高风险操作确认
- 支持取消流（`POST /chat/stop`）和图动态控制（`POST /chat/graph-control`）

---

## 9. 认知内核与认知控制

### 9.1 CognitiveKernel

文件：`kernel/cognitive_kernel.py`

`CognitiveKernel` 是整个系统的唯一中枢，所有聊天请求必须经过它。对应方法：

- `async run(request: KernelRequest) → KernelResponse` — 同步路径
- `async stream(request: KernelRequest) → AsyncIterator[dict]` — 流式路径

核心职责：
1. 恢复 WorkingMemory（Redis 24h TTL）
2. 调用 `classify_intent()` 生成 Intent Lock
3. 执行 V5 路由层（L0 → L0.5 → L1）
4. 按 CognitiveBudget 决定是否注入 memory/context
5. 优先调用 CognitiveExecutive，失败则 fallback V4
6. 写回 WorkingMemory、EpisodicMemory、SemanticHistory

### 9.2 Intent Lock 与 Cognitive Budget

文件：`kernel/cognitive_controls.py`

这是系统最关键的稳定性控制层。

**核心数据结构**：

| 对象 | 字段 | 说明 |
|------|------|------|
| `IntentLock` | `raw_user_query`, `normalized_query`, `protected_intent`, `task_type`, `complexity_level` (L0/L1/L2), `allowed_capabilities`, `disallowed_capabilities`, `confidence`, `cognitive_budget`, `relevance_threshold` | 不可变的意图锁定，贯穿整个认知管线 |
| `CognitiveBudget` | `max_planning_depth` (1), `max_capabilities` (1), `max_replans` (0), `max_memory_tokens` (0), `max_context_expansion` (256), `max_reasoning_steps` (2), `memory_injection` (False), `workspace_context` (False), `critic` (False) | 认知预算，限制各阶段资源消耗 |

三种预算预设：
- **simple Lock** (L0)：greeting/identity/capability_help — 全部限制为 0/False
- **light Lock** (L1)：translation/summarization/weather/time — 放宽 context/reasoning
- **rich Lock** (L2)：document_qa/data_query/web_search — max_planning_depth=2, max_capabilities=2, max_replans=1，开启 memory/critic

**核心函数**：

| 函数 | 说明 |
|------|------|
| `classify_intent(query, force_mode, prior_intent, prior_domain, conversation_phase) → IntentLock` | 零 LLM 的确定性意图分类（正则匹配 + 关键词 + 黏性域继承），< 1ms |
| `direct_answer_for_intent(lock) → str\|None` | capability_help/usage_help 直接回答 |
| `apply_intent_lock_to_context(ctx, lock)` | 将 Lock 字段注入 RuntimeContext |
| `capability_allowed(capability, lock) → bool` | 检查单个能力是否被允许 |
| `relevance_score(query, text) → float` | 基于 token overlap（含 CJK bigram）的相关性评分 |
| `passes_relevance_anchor(query, text, threshold=0.35) → bool` | 相关性锚点门控 |

**分类规则优先级**：
1. `force_mode` → 直接构建 L2 Lock，仅允许该能力
2. 空查询 → simple Lock
3. 正则匹配：greeting → identity → capability_help → usage_help
4. 关键词：翻译/总结 → light Lock，文档/数据/联网 → rich Lock，天气/时间 → light Lock
5. **黏性域继承**：若上轮 intent 是 `data_query`/`document_qa`/`web_search` 且追问检测触发 → rich Lock（confidence=0.65）
6. 默认 fallback → L1 general_qa，仅允许 `model.answer`

**能力名称规范化**：

`kernel/cognitive_controls.py` 内置 `_CAPABILITY_NORMALIZE_MAP`，解决 intent_lock 使用的名称与实际注册名称不匹配的问题：

```text
tool.datetime → get_current_time
tool.weather  → get_weather
chart.generate → chart_generator
tool.execute   → tool.datetime（死引用映射到最近实有能力）
```

`normalize_capability_name()` 函数被 `constraint_layer.py` 调用，确保能力名称一致。

---

## 10. V5 路由层

### 10.1 L0 Rule Router

文件：`kernel/query_router_v2.py`

类：`L0RuleRouter`，零 LLM 调用，< 1ms 延迟。

处理顺序：
1. 斜杠命令 `/rag\|data\|web\|tool\|skills\|vision\|anomaly\|rule` → `force_mode` 路由
2. 身份查询 — `is_identity_user_query()` + 内置正则 → `CANONICAL_IDENTITY_RESPONSE`，若 `kernel_enriched_identity_enabled` 则标记为可 LLM 增强
3. 问候语 — 内置正则匹配 → 预设问候回复
4. FAQ 模式 — 匹配 "你能做什么""使用帮助""hello" 等 → 预设 FAQ 回复
5. 未命中 → `L0RouteResult(hit=False)`，向下传递

特征标志：`kernel_l0_rule_router_enabled`

### 10.2 L0.5 Semantic Cache

文件：`kernel/semantic_cache.py`

类：`SemanticCache`，embedding 相似度匹配。

参数：`threshold=0.92`（余弦相似度），`max_entries=10000`，`ttl_seconds=3600`。

方法：
- `lookup(query, ctx_hash) → CacheEntry | None`：计算 query embedding，遍历缓存找最佳匹配
- `store(query, content, ctx_hash)`：计算 embedding，去重（SHA256 key），LRU 淘汰

跳过缓存的 task_type：`weather`、`time`、`data_query`、`web_search`（这些是实时数据，不应缓存）。

降级方案：`_FallbackEmbedder` 用 SHA256 hash 作为伪 embedding，防止 embedding 服务不可用时崩溃。

特征标志：`kernel_semantic_cache_enabled`

### 10.3 L1 TinyRouter

文件：`kernel/tiny_router.py`

类：`TinyRouter`，用 LLMRole.ROUTER（qwen3-1.7b JuniorShort）做 query 复杂度分类。

路由优先级：
1. 身份查询 → `route="complex"`（交给编排器）
2. **intent_lock 确定性路由**（零 LLM）：
   - weather/time/data_query/web_search/document_qa → `route="complex"`
   - translation/summarization/general_qa（仅 model.answer）→ `route="simple"`
3. 明显短问候 → `route="simple"` + 预设回答
4. LLM 分类 → 返回 `"simple"` / `"knowledge"` / `"complex"`
   - simple → LLMRole.FAST（8B）生成直接回答（≤100 中文字符）
   - knowledge → 交给知识管道
   - complex → 交给编排器

特征标志：`kernel_l1_tiny_router_enabled`

### 10.4 Complexity Engine

文件：`kernel/complexity_engine.py`

类：`ComplexityEngine`，纯规则评分（无 LLM）。

评分公式：
```
score = length_score × 0.35 + entity_score × 0.25 + clause_score × 0.20
        + reasoning_bonus - factual_discount
```

阈值：
- score < 0.3 → L0 (simple)
- score < 0.6 → L1 (medium)
- score ≥ 0.6 → v4 (complex)

---

## 11. V4 编排器与多轮增强

### 11.1 CognitiveOrchestratorV4

文件：`kernel/orchestrator_v4.py`（~3340 行）

类：`CognitiveOrchestratorV4`，V4 稳定编排管线。

构造参数：`timeout_sec=30`, `max_parallel=5`

初始化组件：`PlanAgent`、`AgentRegistry`、`Dispatcher`、`FusionEngine`、`CriticEngine`、`ContentAnnotator`、`OutputValidator`

**完整管线** (`process()`)：

1. PII 脱敏（`kernel_pii_masking_enabled`）
2. XAI 认知追踪（`kernel_xai_trace_enabled`）
3. 身份查询快速通道 — `_handle_identity_query()`
4. TaskModel + WorldModel 初始化
5. 自适应画像 + 用户画像
6. Phase 2 统一路径（`kernel_orchestrator_unified_enabled`）
7. 对话状态追踪 (DST) + 指代消解 (ReferenceResolver)
8. 多问题检测与拆分 → `_process_multi_question()`
9. 纠正重规划 (RefinePlanner)
10. Plan 生成：`force_mode` → 单 subtask，否则 `PlanAgent.generate_plan()`
11. 硬守卫自动注入：即使 PlanAgent 遗漏，关键词检测也会注入 rag/data subtask
12. DAG 调度（`kernel_agent_dag_scheduling_enabled`）
13. `Dispatcher.dispatch()` — 并行执行 subtask
14. 低质量 RAG 重规划：chunk 数量为 0 或平均分 < 0.5 → QueryRewriter 重写 + 重新 RAG，仍低质量则注入 web subtask
15. 融合 — `FusionEngine.run()` + relevance anchor 检查
16. 内容标注 — `annotate_agent_result()` + `merge_responses()`
17. 答案生成（四条路径）：
    - 有文档证据 → `_llm_grounded_answer()` + `_format_rag_answer()`
    - 有数据结果 → `_format_data_answer()`
    - 有 web/tool/附件 → `_llm_grounded_answer()`
    - 否则 → 直接合并标注文本
18. 冲突标注 + 输出验证
19. `CriticEngine.run()` — 幻觉风险评估
20. 执行图构建（供前端展示）

**流式路径** (`stream()`)：
- 将 `process()` 包装为 asyncio.Queue 生产者-消费者模式
- 输出 `agent_start`、`agent_complete`、`reasoning_step`、`delta`（24 chars / 8ms）、`conflict_summary`、`answer_draft`、`final_answer`

### 11.2 PlanAgent（标记为 DEPRECATED）

文件：`kernel/plan_agent.py`

类：`PlanAgent`，被 `kernel.runtime.orchestrator.UnifiedOrchestrator` 取代，但 V4 编排器仍在使用。

核心方法：`generate_plan(user_query, context) → TaskPlan`
- 构建 PLANNING 角色 LLM prompt，描述可用 agent_type
- 注入上下文、自适应画像、对话历史、会话状态
- 调用 LLMRole.PLANNING（temperature=0.0, max_tokens=1200）
- 解析 JSON → `TaskPlan(subtasks, merge_strategy, max_parallel)`

关键数据结构：
- `SubTask`：agent_type（data/tool/web/memory/rag/rule_engine/vision）、query、params、depends_on、priority
- `TaskPlan`：subtasks 列表、merge_strategy（union/compare/prioritized）、max_parallel

**Intent Lock 集成**：`generate_plan()` 的 prompt 中注入意图约束块，LLM 返回后 `_filter_disallowed_subtasks()` 过滤使用被禁能力的 subtask。

### 11.3 多轮增强模块

| 模块 | 文件 | 功能 |
|------|------|------|
| ConversationState | `conversation_state.py` (385 loc) | 结构化多轮状态：active_topic、intent、phase、goal、entities、plan、results |
| ReferenceResolver | `reference_resolver.py` | LLM 驱动指代/引用/纠正消解 |
| ResultRefBuilder | `result_ref_builder.py` | 跨轮结果引用构建 |
| DialogueStateTracker | `dialogue_state_tracker.py` | 对话状态追踪（短追问消歧） |
| RefinePlanner | `refine_planner.py` (341 loc) | 局部纠正重规划：FailureType → RepairStrategy，最多 2 层 |
| ClarificationGate | `clarification_gate.py` (297 loc) | 主动追问：检测模糊查询 → 生成反问题 |
| ContextAssembler | `context_assembler.py` | 结构化上下文组装（历史/记忆/附件/状态四块） |
| ContextComposer | `context_composer.py` | 上下文压缩与摘要 |
| HistoryRetriever | `history_retriever.py` (117 loc) | 多轮历史检索 |
| PreferenceLayers | `preference_layers.py` | 用户偏好分层注入 |

### 11.4 融合与审校

| 模块 | 功能 |
|------|------|
| `fusion_engine/engine.py` | V1 加权融合 |
| `fusion_engine/sequence_fusion.py` | 多问题顺序融合 |
| `critic_engine/engine.py` | 候选答案评分、幻觉风险、低置信补充提示、质量审校 |
| `epistemology/` | 证据标注、输出验证、渲染 hint |

---

## 12. AI Runtime 统一运行时

目录：`kernel/runtime/`（~45 文件，~9900 行，全部真实实现）

AI Runtime 是新一代统一执行管线，目标是将分散的上下文拼装、规划、证据收集、融合收敛到 `RuntimeContext` 和 `CognitiveExecutive`。

### 12.1 核心管线

```text
RuntimeContext
  → RewriteEngine（查询规范化，受 Intent Lock 约束）
  → UnderstandingEngine（深度任务理解）
  → UnifiedPolicyEngine（策略检查）
  → ContextCompressor（上下文压缩）
  → CognitivePlannerV2（LLM-based 三层认知规划）
      ├── CognitivePlan（目标层级、信息缺口、推理链）
  → StrategyBuilder（能力分配：信息缺口 → capability assignments）
      ├── StrategyProjection（执行策略、并行组、预算约束）
  → ExecutionProjection（桥接：projection → ExecutionPlan + ExecutionNode）
  → PlannerConstraintLayer（5 维确定性守卫：budget/policy/risk/capability/historical）
  → CapabilityGraphBuilder（执行图构建）
  → ExecutionRuntime（DAG 执行）
  → EvidenceBus（pub/sub 证据总线）
  → FusionEngineV2（LLM 驱动语义证据融合）
  → CriticEngineV2（结构化质量评估）
  → ArtifactComposer（产物合成）
  → Workspace / MemoryFabric（状态写回）
```

### 12.2 RuntimeContext

文件：`kernel/runtime/context.py`

`RuntimeContext` 是统一、结构化的请求上下文，一次构建后通过引用传递至管线各层。关键字段分组：

| 域 | 字段 |
|---|---|
| 请求标识 | `request_id`, `session_id`, `user_id`, `query` |
| 意图锁定 | `raw_user_query`, `protected_intent`, `task_type`, `allowed_capabilities`, `disallowed_capabilities`, `intent_confidence`, `cognitive_budget`, `relevance_threshold` |
| 对话 | `conversation_history`, `conversation_state` |
| 记忆 | `memory_context`, `episodic_events` |
| 工作区 | `workspace_state` |
| 用户画像 | `user_preferences`, `user_style_hints`, `preference_context_block` |
| 数据源 | `data_source_context`, `available_data_sources` |
| 附件 | `attachment_contexts` |
| 强制/安全 | `force_mode`, `web_enabled`, `graph_controls`, `risk_assessment`, `tool_permission_token` |
| 分支 | `is_branch_request`, `branch_checkpoint`, `parent_message_id` |
| 流式 | `stream`, `trace_ctx` |
| 扩展 | `metadata`（通用 dict） |

### 12.3 关键模块

| 模块 | 文件 | 核心职责 |
|------|------|----------|
| CognitiveExecutive | `cognitive_executive.py` | V2 Runtime 单一入口，编排 9 个阶段管线 |
| CognitivePlannerV2 | `cognitive/cognitive_planner_v2.py` | LLM 单次调用生成 CognitivePlan（目标层级 + 信息缺口 + 推理链） |
| StrategyBuilder | `cognitive/strategy_builder.py` | 将认知计划转换为能力分配（`StrategyProjection`） |
| ExecutionProjection | `cognitive/execution_projection.py` | 桥接：projection → `ExecutionPlan` + `ExecutionNode` + `ExecutionEdge` |
| PlannerConstraintLayer | `constraint_layer.py` | 5 维确定性守卫，无 LLM |
| ExecutionRuntime | `executor.py` | DAG 执行引擎，接收 ExecutionPlan/ExecutionGraph |
| EvidenceBus | `evidence_bus.py` | 进程内 pub/sub 证据总线，完整生命周期状态机 |
| FusionEngineV2 | `fusion.py` | LLM 驱动语义融合（去重、矛盾检测、置信度合并） |
| CriticEngineV2 | `critic.py` | 结构化质量评估（factuality、completeness、evidence coverage、hallucination risk） |
| CapabilityRegistry | `capability.py` | 统一线程安全能力目录，收敛 agents/tools/skills/plugins |
| ArtifactComposer | `artifact_composer.py` | 多模态产物合成 |
| MemoryFabric | `memory_fabric.py` | Runtime 记忆写回 |

### 12.4 Runtime 子目录

| 子目录 | 功能 |
|--------|------|
| `cognitive/` | CognitivePlannerV2、StrategyBuilder、ExecutionProjection、DecompositionPolicy、CognitiveGraph 数据结构 |
| `context_runtime/` | ContextCompressor、ContextRanker、EvidenceSelector、MemorySelector、SemanticDistiller |
| `evidence/` | Evidence 生命周期、ranking、resolution、state machine |
| `memory/` | TruthMaintenance、ConfidenceDecay、ContradictionResolution、FactSupersession |
| `replay/` | PromptSnapshot、RuntimeSnapshot、DeterministicTrace、ExecutionReplay |

### 12.5 Intent Lock 贯穿 Runtime

V2 Runtime 是 Intent Lock 约束实现最完整的路径：

1. `CognitiveExecutive.execute()` — 从 metadata 中恢复 IntentLock 或重新 classify，注入 RuntimeContext
2. `CognitivePlannerV2._build_system_prompt()` — 注入意图约束块（`_build_intent_constraint_block()`），告知 LLM 可用/禁用能力
3. `PlannerConstraintLayer._check_intent_constraints()` — 能力名称规范化后做确定性校验
4. 约束拒绝后 → replan（强制 model.answer）→ 仍失败则 `_direct_answer_fallback()` 降级

---

## 13. Agent 集群

目录：`agents/`

### 13.1 核心抽象

| 类型 | 文件 | 说明 |
|------|------|------|
| `BaseAgent` | `base.py` | 抽象基类，定义 `execute(task: TaskMessage) → AgentResult` |
| `TaskMessage` | `base.py` | Pydantic 模型：task_id, agent_type, query, params, session_id, user_id |
| `AgentResult` | `base.py` | Pydantic 模型：task_id, agent_type, status, content, confidence, metadata, error, evidence |
| `AgentRegistry` | `registry.py` | 兼容包装器，同时注册到本地 dict 和 CapabilityRegistry |
| `AgentWorker` | `worker.py` | Agent Bus 消费者进程，无限循环消费 Redis pubsub/stream |

### 13.2 Agent 清单

| Agent | agent_type | 文件 | 功能 | 特征标志 |
|-------|-----------|------|------|----------|
| RagAgent | `rag` | `rag_agent.py` | 文档 chunk 检索、LLMWiki 搜索、memory 检索 | `kernel_agent_rag_enabled` |
| WebAgent | `web` | `web_agent.py` | 联网搜索（Serper API），ToolRouter 委托 | `kernel_agent_web_enabled` |
| ToolAgent | `tool` | `tool_agent.py` | 时间/日期、天气、计算器，ToolRouter 委托 | `kernel_agent_tool_enabled` |
| DataAgent | `data` | `data_agent.py` | V1 入口，V2 默认启用时路由到 V2 | `kernel_agent_data_enabled` |
| SkillsAgent | `skills` | `skills_agent.py` | 技能执行 | — |
| RuleEngineAgent | `rule_engine` | `rule_engine_agent.py` | 产品/业务规则匹配 + LLMRole.CHEAP_CRITIC 解释 | — |
| VisionAgent | `vision` | `vision_agent.py` | 图片/图表理解（LLMRole.VISION） | `kernel_agent_vision_enabled` |

### 13.3 RagAgent 详细流程

1. 查询规范化：去除中文指令前缀、重写常见模式（怎么做→如何做）
2. 查询分类：`definition/fact/procedure/comparison/memory/general`，附带检索策略 hints
3. 术语扩展 + 同义词映射 + 去重（上限 3 个搜索查询）
4. **并行检索**（`asyncio.gather`）：`DocumentPlugin.search_chunks()` + `DocumentPlugin.search_llmwiki()`
5. 组装证据，title bonus 评分
6. 记忆 fallback：无文档命中或 memory 意图 → 查询 UserMemory
7. 去重、排序、截断 top_k
8. 可选 neural re-rank（`rag_rerank_enabled`，qwen3-vl-rerank via DashScope）
9. 证据质量门控（`DocumentEvidenceGate`：最低分 + 分差检查）
10. Relevance anchor 评分
11. 延迟 fallback：初始结果为空时扩大搜索
12. 置信度加权计算：max_score(25%) + avg_score(15%) + source_diversity(12%) + score_spread(10%)

### 13.4 Agent Bus Worker

文件：`agents/worker.py`

类：`AgentWorker`，Agent Bus 消费端主进程。

- `run_forever()` — 启动心跳 + 所有 Agent 的消费循环
- 支持两种模式：Redis Stream（`XREADGROUP` + pending reclaim）和 Redis PubSub
- 错误重试（最多 `kernel_agent_bus_max_retry` 次）+ 死信队列
- 心跳：定期 `SETEX` 到 Redis，Worker 健康检查用 TTL 判断

---

## 14. DataAgent V2 认知型数据智能体

目录：`agents/data_agent_v2/`（~25+ 文件，~7500 行）

三层架构：

### 14.1 知识层 (Knowledge Layer)

| 模块 | 文件 | 功能 |
|------|------|------|
| KnowledgeRetriever | `knowledge_retriever.py` | 检索 schema metadata、指标定义、表关系、分析技能 |
| KnowledgeUpdater | `knowledge_updater.py` | 知识库更新 |
| PatternExtractor | `pattern_extractor.py` | 查询模式提取 |
| MetricRefiner | `metric_refiner.py` | 指标定义精炼 |

### 14.2 推理层 (Reasoning Layer)

14 个子 Agent 组成认知数据管线：

| Agent | 文件 | 功能 |
|-------|------|------|
| IntentAgent | `intent_agent.py` | NL → 结构化分析意图分类 |
| EntityAgent | `entity_agent.py` | 实体识别与消歧 |
| MetricAgent | `metric_agent.py` | 指标识别与计算 |
| TimeReasoningAgent | `time_reasoning_agent.py` | 时间范围推理 |
| JoinAgent | `join_agent.py` | 多表 join 路径推理 |
| SemanticAgent | `semantic_agent.py` | 语义列/表匹配 |
| PlannerAgent | `planner_agent.py` | 查询计划构建 |
| SQLCompilerAgent | `sql_compiler_agent.py` | SQL 生成 |
| VerificationAgent | `verification_agent.py` | SQL 安全验证 |
| ReflectionAgent | `reflection_agent.py` | 错误自反思与自动修复 |
| DataCritic | `data_critic.py` | 数据答案质量评估 |

### 14.3 高级分析层 (Phase 4)

| 模块 | 功能 |
|------|------|
| StatisticalAgent | 统计分析 |
| InsightAgent | 洞察生成 |
| VisualizationAgent | 可视化建议 |
| SkillsEngine | 分析技能执行 |

### 14.4 Supervisor 管线

文件：`supervisor.py`，10 步管道：

1. 初始化 CognitiveContext
2. 运行知识层
3. DagBuilder 从 CognitiveContext + feature flags 构建 DAG
4. 执行 DAG（`DagScheduler` + semaphore 并行）
5. 执行 SQL（验证通过后）
6. 自反思与自动修复（Phase 2.1）
7. 高级分析（Phase 4）
8. 构建 AgentResult（含 confidence + trace）
9. Critic 评估（Phase 2.2）
10. 置信度断路器 → 低质量回退 V1

### 14.5 配置

```text
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
DATA_AGENT_V2_CONFIDENCE_THRESHOLD=0.40
DATA_AGENT_V2_SUPERVISOR_MAX_RETRIES=2
DATA_AGENT_V2_USE_METRIC_DEFINITIONS=true
DATA_AGENT_V2_USE_SCHEMA_METADATA=true
DATA_AGENT_V2_USE_TABLE_RELATIONSHIPS=true
```

---

## 15. 数据源、Knowledge Assets 与 Text2SQL

### 15.1 数据源支持

| 类型 | 说明 |
|------|------|
| MySQL | 业务库查询 |
| PostgreSQL | 业务库查询 |
| ClickHouse | 分析型查询 |
| Doris | 分析型查询 |

### 15.2 Data Cognition 模块

目录：`kernel/data_cognition/`

| 模块 | 功能 |
|------|------|
| `semantic_layer.py` | 指标、维度、语义层管理 |
| `schema_linker.py` | Schema linking（问题→表/列） |
| `query_planner.py` | 查询计划 |
| `logical_plan.py` | 逻辑计划 |
| `sql_builder.py` | SQL 构造 |
| `sql_validator.py` | SQL 安全验证（只读检查） |
| `sql_rewriter.py` | SQL 修复 |
| `sql_reflector.py` | SQL 反思与优化 |
| `sql_dialect.py` | 方言适配 |
| `query_executor.py` | SQL 执行（只读） |
| `explanation.py` | 结果解释 |

### 15.3 语义资产

| 资产 | 文件 | 说明 |
|------|------|------|
| MetricDefinition | `models.py` | 业务指标定义（公式、别名、审批工作流） |
| SchemaMetadata | `models.py` | 每列业务语义（类型、生命周期、掩码规则） |
| TableRelationship | `models.py` | 预建模 join 图（基数、放大风险） |
| AnalyticalSkill | `models.py` | 可重用分析模式（队列、漏斗、RFM） |
| QueryPattern | `models.py` | 成功查询模式缓存（基于哈希的快速路径） |

### 15.4 相关 API

| Router | 功能 |
|--------|------|
| `databases.py` | 数据源 CRUD、连接测试、schema 同步 |
| `data.py` | 数据查询 API |
| `metrics.py` | 指标定义管理 |
| `table_relationships.py` | 表关系管理 |
| `analytical_skills.py` | 分析技能管理 |

---

## 16. RAG 与文档系统

### 16.1 检索流程

```text
query
  → normalize / rewrite（去除指令前缀、同义词扩展）
  → query type classify（definition/fact/procedure/comparison/memory/general）
  → query expansion（术语提取 + 同义词映射，上限 3 个查询）
  → DocumentPlugin.search_chunks（向量检索文档块）
  → DocumentPlugin.search_llmwiki（FAQ 检索）
  → Memory fallback（无文档命中时查询 UserMemory）
  → 去重 + 排序
  → 可选 neural rerank（rag_rerank_enabled）
  → evidence quality gate（min_score + score gap 检查）
  → relevance anchor（token overlap 评分）
  → AgentResult(metadata.chunks / citations / quality)
```

### 16.2 证据质量门控

RAG 输出包含质量元数据：
- `quality.answerable` — 是否有足够证据支撑回答
- `quality.gated` — 是否被门控拦截
- `quality.relevance_anchor` — 相关性评分
- 证据分级：`factual`（≥0.50）、`supporting`、`contextual`

低相关 supporting chunk 被降级，不直接作为最终答案。

### 16.3 关键配置

```text
RAG_MIN_SCORE=0.35              # 最低检索分数（env var，非 settings.py 定义）
RAG_MIN_EVIDENCE_SCORE=0.65     # settings.py 定义的最低证据分数
rag_rerank_enabled=true          # neural re-rank
llmwiki_enabled=true             # LLM 生成 FAQ 检索
llmwiki_top_k=3
ATTACHMENT_UPLOAD_ENABLED=true
ATTACHMENT_MAX_SIZE_MB=20
ATTACHMENT_MAX_CHARS=4000
```

### 16.4 附件系统

支持 txt、md、csv、tsv、pdf、docx、xlsx、json、代码文件、图片类型。
解析后内容注入 `attachment_contexts`，最大 50KB 自动加载。
附件持久化到 PostgreSQL（`Attachment` 模型），Redis 作为 fallback。

---

## 17. 记忆系统

目录：`memory/`（六层记忆体系）

### 17.1 各层职责

| 层 | 目录 | 存储 | TTL | 功能 |
|----|------|------|-----|------|
| WorkingMemory | `working_memory/` | Redis + deque(maxlen=N) | 24h | 会话对话窗口 + KV scratchpad + identity 缓存（5 轮过期） |
| EpisodicMemory | `episodic_memory/` | Redis 追加列表 | 7d | 轮次/事件时间线 |
| SemanticMemory | `semantic_memory/` | 内存向量存储（InMemorySemanticStore） | — | quer→answer 向量的余弦相似度检索 |
| ProceduralMemory | `procedural_memory/` | — | — | 程序性知识存储 |
| TemporalMemory | `temporal_memory/` | — | — | 指数衰减权重：`score × 2^(-age/half_life)` |
| MemoryRouter | `memory_router/` | — | — | 联合检索（vector/episodic/keyword/graph）+ rerank + value scoring |

### 17.2 记忆演化

目录：`memory/evolution/`

| 模块 | 功能 |
|------|------|
| `evolution.py` | MemoryCompressor（LLM 压缩）、MemoryEvolution（案例→模式→技能管道）、MemoryReinforcement（RL 权重调节） |
| `governance.py` | MemoryGovernance：指数置信度衰减（7 天半衰期，min=0.15）、矛盾检测（中文关键词对 + 数值比率 >3×）、来源追踪、陈腐块修剪 |
| `router.py` | EvolutionMemoryRouter：四层扩展（强化、自动演化、技能注入、治理集成），20 个案例触发演化，反馈驱动自动衰减 |

### 17.3 注入原则

- 简单问答（L0/L1）默认 `memory_injection=False`，不注入记忆上下文
- 仅记忆类、延续类、个性化类任务（rich Lock）才允许 memory 进入 planner
- Memory 作为候选上下文，不覆盖 `raw_user_query`

---

## 18. Capability Intelligence

目录：`kernel/capability_intelligence/`（12 文件，~2500 行）

核心目标：将系统从 "tool calling" 升级到 "capability cognition"。Planner 看到的不只是工具名，而是能力画像（可靠性、延迟、历史成功率、替代关系、策略记忆）。

### 18.1 数据模型

`CapabilityProfile`：每个能力的丰富语义元数据
- 描述、优势、劣势、理想查询、反模式
- 资源类型（CPU/GPU/IO/NETWORK）、平均延迟、可靠性评分
- 标签（中文 + 英文）、领域匹配

### 18.2 Phase 1（`kernel_capability_intelligence_enabled`）

| 模块 | 功能 |
|------|------|
| `profiler.py` (583 loc) | CapabilityProfiler：从注册表 + 14 个能力的硬编码种子数据构建画像；`match()` 基于标签/优势的文本匹配（含 CJK bigram）；`match_multi_objective()` 5 维复合评分（语义/历史/上下文/预算/风险）；`update_from_record()` 在线学习 |
| `adapter.py` | 将 CapabilityProfile 格式化为 LLM prompt |
| `feedback.py` | 执行反馈闭环：成功/失败计数、延迟 EMA 更新 |
| `failure_memory.py` (250 loc) | 失败记录/统计/模式识别（始终可用，无 feature flag 门控） |

### 18.3 Phase 2（`kernel_capability_intelligence_phase2_enabled`）

| 模块 | 功能 |
|------|------|
| `knowledge_graph.py` (273 loc) | CapabilityKnowledgeGraph：14 个能力节点的有向图；关系类型 `depends_on/complements/substitutes/conflicts_with`；Kahn 拓扑排序（含并行层）、BFS 最短路径、替代链解析（`find_substitute_path`）、LLM prompt 导出 |
| `reasoner.py` (170 loc) | CapabilityReasoner：包装 profiler match + KG 依赖惩罚（低可靠性前置条件 -0.15）+ 执行记忆退化惩罚（-0.20）+ 进化权重调整；`determine_execution_order()`（KG 拓扑）、`find_alternative()`、`get_execution_strategy_hint()` |
| `execution_memory.py` (195 loc) | 每个能力的结构化时间窗口执行统计：成功率、延迟分布、退化检测 |
| `strategy_memory.py` (222 loc) | 记住哪种策略对哪种能力集和领域有效（direct/parallel/sequential/compare） |
| `evolution.py` (252 loc) | EvolutionEngine：每 N 轮持续分析，退化→降低权重，改进→提升权重 |
| `ontology.py` | 能力本体定义 |

### 18.4 配置

```text
kernel_capability_intelligence_enabled=true          # Phase 1
kernel_capability_intelligence_phase2_enabled=true    # Phase 2
kernel_capability_knowledge_graph_enabled=true
kernel_capability_reasoner_enabled=true
kernel_capability_execution_memory_enabled=true
kernel_capability_strategy_memory_enabled=true
kernel_capability_evolution_enabled=true
kernel_capability_evolution_interval=10               # 每 N 轮触发演化
```

---

## 19. 工具、技能、插件与连接器

### 19.1 工具系统

目录：`kernel/tools/`、`tools/registry/`、`tools/builtin_tools/`、`execution/tool_router/`

内置能力：
- 时间/日期（`get_current_time`）
- 天气（`get_weather`）
- 计算器（`calculator`）
- Python/code sandbox（`python.execute`）
- Web search（`web.search`）
- 图表生成（`chart_generator`）

`ToolRouter`（`execution/tool_router/router.py`）统一工具调用路由，ToolAgent 和 WebAgent 均通过它委托。

`ToolSelector` / `ToolRanker` / `ToolFeedback` 支持工具选择、排序和反馈闭环。

### 19.2 插件系统

目录：`plugins/`

| 插件 | 功能 |
|------|------|
| `document_plugin.py` | 文档检索（chunk + LLMWiki） |
| `web_plugin.py` | Web 检索封装 |
| `knowledge_plugin.py` | 知识增强 |
| `memory_plugin.py` | 记忆访问 |
| `tool_plugin.py` | 工具封装 |
| `code/` | 安全代码解释器 |
| `chart/` | 图表生成 |
| `data/` | 数据分析插件 |

### 19.3 技能系统

目录：`skills/runtime/`、`skills/store/`、`skills/installed/`

支持 manifest 验证、技能加载、技能市场条目、会话启用/禁用和测试执行。

### 19.4 连接器

目录：`connectors/sdk/`、`connectors/builtin/`

用于外部系统集成的连接器 SDK 和内置连接器，由 `connectors.py` router 暴露管理 API。

---

## 20. 规则引擎与灰度发布

### 20.1 规则引擎

- `agents/rule_engine_agent.py`：关键词匹配 + LLMRole.CHEAP_CRITIC 规则解释
- `gateway/api_gateway/routers/rules.py`：规则 CRUD、版本化、灰度发布/回滚
- 规则以 YAML 格式定义，支持版本管理

### 20.2 灰度发布配置

```text
KERNEL_RULE_GRAYSCALE_ENABLED=true
KERNEL_RULE_GRAYSCALE_DEFAULT_PERCENTAGE=100
```

### 20.3 Force Mode 集成

`force_mode="product"` 或 `force_mode="rule_engine"` 强制路由到规则引擎 Agent。

---

## 21. 执行平面与 Agent Bus

### 21.1 执行方式

| 模式 | 说明 |
|------|------|
| 直接执行 | Dispatcher 本进程调用 Agent |
| DAG 调度 | 根据依赖拓扑 `DAGGraph`（networkx 包装）执行任务 |
| 推测执行 | Speculative Execution：并行候选执行 |
| Agent Bus（PubSub） | Redis PubSub 广播给 Worker |
| Agent Bus（Stream） | Redis Stream + consumer group + ack + pending reclaim |
| ExecutionRuntime | V2 Runtime 中的统一 DAG 执行器 |

### 21.2 DAG 引擎

目录：`execution/dag_engine/`

| 模块 | 功能 |
|------|------|
| `graph.py` | 核心数据结构：`Task`（fn/dependencies/resources/retry/dynamic inject）、`DAGGraph`（networkx 包装）、`TaskStatus/ResourceType/NodeType` 枚举 |
| `engine.py` | `DAGEngine`：主执行循环（`asyncio.gather` 并行）、`ResourceScheduler` 资源门控、`EventBus` 事件发布、`StateManager` 检查点、重试+回滚 |
| `scheduler.py` | `ResourceScheduler`：CPU/GPU/IO 槽限制 + 优先级排序 |
| `events.py` | `EventBus`：pub/sub 生命周期事件 |
| `state.py` | `StateManager`：基于 Redis 的检查点，支持执行恢复 |
| `cognitive_nodes.py` | 预构建任务工厂：reasoning/tool_call/agent_call |

### 21.3 Agent Bus 配置

```text
KERNEL_AGENT_BUS_ENABLED=true
KERNEL_AGENT_BUS_REQUIRE_WORKER=true
KERNEL_AGENT_BUS_NAMESPACE=opentrace:agent
KERNEL_AGENT_BUS_MODE=pubsub                                   # pubsub | stream
KERNEL_AGENT_BUS_GROUP=agent-workers
KERNEL_AGENT_BUS_MAX_RETRY=2
KERNEL_AGENT_BUS_RECLAIM_IDLE_MS=30000
KERNEL_AGENT_BUS_RECLAIM_COUNT=20
```

---

## 22. 模型网关

目录：`model/`

### 22.1 角色化模型路由

枚举：`LLMRole`（`model/model_gateway/gateway.py`）

| Role | 典型模型 | 用途 | temperature | max_tokens |
|------|----------|------|-------------|------------|
| `QUERY` | qwen3.6-plus (37B-max) | 主回答、复杂推理 | 默认 | 默认 |
| `PLANNING` | qwen3.6-plus | 任务分解、计划生成 | 0.0 | 1200 |
| `COMPRESS` | qwen3.5-27b | 上下文压缩与摘要 | 默认 | 默认 |
| `ROUTER` | qwen3-1.7b (JuniorShort) | L1 查询分类 | 默认 | 默认 |
| `FAST` | qwen3-8b (MiddleShort) | 简单回答（≤100 中文字符） | 默认 | 默认 |
| `CHEAP_CRITIC` | qwen3-14b (SeniorShort) | 轻量级批评/审校 | 默认 | 默认 |
| `KNOWLEDGE` | qwen3-14b (SeniorShort) | 知识库问答 | 默认 | 默认 |
| `IDENTITY` | qwen3-0.6b (MinShort) | 系统身份响应 | 0.7 | 256 |
| `VISION` | qwen3.6-vl-plus | 图像/图表解读 | 0.3 | 2048 |

### 22.2 ModelGateway

类：`ModelGateway`（单例 `get_model_gateway()`）

- Per-role 延迟初始化适配器 + 熔断器
- 三级熔断器（`CircuitBreaker`）：CLOSED → OPEN（failure_threshold=3）→ HALF_OPEN → CLOSED/OPEN
- 回退链：主角色失败 → fallback_roles 候选 → 离线降级响应
- 异常分类：auth/rate_limit/timeout/connectivity/model_not_found → 不同重试策略
- 重试：指数退避，auth 和 model_not_found 不重试
- 离线降级：按角色返回预设响应（ROUTER → `{"route":"complex"}`，IDENTITY → 规范身份文本，通用 → 中文离线消息）
- 身份增强：调用前 `merge_system_identity()`，调用后 `enforce_identity_output()`

### 22.3 LLM Adapter

`OpenAICompatibleAdapter(BaseLLMAdapter)`：

- 通过 `httpx.AsyncClient` + `openai.AsyncOpenAI` 调用任何 OpenAI 兼容 API
- 自动回退：先尝试系统代理 → 失败则直连
- qwen3 模型自动添加 `enable_thinking: False`
- Prometheus 指标：`LLM_CALLS_TOTAL`、`LLM_LATENCY`

### 22.4 Embedding

工厂函数 `get_embedder()` 根据 `settings.embedding_provider` 路由：

| Provider | 实现 | 降级 |
|----------|------|------|
| `dashscope` | DashScopeEmbedder | HashEmbedder |
| `api`/`openai` | APIEmbedder（多端点/代理探测） | HashEmbedder（按批次） |
| `local` | LocalEmbedder（sentence-transformers） | HashEmbedder |
| 默认 | HashEmbedder（SHA-256 seed → numpy RNG → 单位向量） | — |

### 22.5 Reranker

工厂函数 `get_reranker()` 根据 `settings.rerank_provider` 路由：

| Provider | 实现 | 降级 |
|----------|------|------|
| `dashscope` | DashScopeReranker（TextReRank） | HeuristicReranker |
| `api`/`openai` | APIReranker（多端点/代理探测） | HeuristicReranker |
| 默认 | HeuristicReranker（BM25 算法，k1=1.5, b=0.75） | — |

---

## 23. 安全、审计与可解释性

### 23.1 安全能力

| 能力 | 实现位置 | 说明 |
|------|----------|------|
| Zero Trust | `safety/` + `chat.py` | 查询风险评估 + 工具权限令牌 issue |
| PII Masking | `safety/` + `infra/security/` | NER PII 脱敏（9 种实体类型） |
| Guardrails | `safety/` | 输入和策略防护 |
| SQL Safety | `data_cognition/sql_validator.py` | 只读 SQL 检查、host guard |
| Tool Permission | `chat.py` | 高风险工具确认令牌机制 |
| Canary | `safety/` | 金丝雀测试与自动回滚（错误率阈值 10%，延迟倍增 2×，最小样本 100） |
| JWT Auth | `routers/auth.py` + `infra/security/` | HS256，默认 7 天过期 |
| Password | passlib[bcrypt] | bcrypt 哈希 |

### 23.2 审计与可解释性

| 对象 | 模型/文件 | 说明 |
|------|-----------|------|
| TraceLog | `models.py` | 每轮 query/response/graph/延迟/token 聚合 |
| ReasoningTrace | `models.py` | 分阶段推理审计（阶段、分数、迭代） |
| CognitiveEvent | `models.py` | DataAgent V2 管线步骤审计 |
| AuditLog | `models.py` | 操作审计（操作、资源、payload） |
| XAI CognitiveTrace | `safety/xai/` | 决策、fusion、critic、final 的可解释轨迹 |
| Runtime Snapshot | `runtime/replay/` | Prompt/runtime 确定性回放 |

---

## 24. 基础设施与持久化

### 24.1 PostgreSQL

默认数据库：`opentrace_v2`

Docker 容器地址：
```text
DATABASE_URL=postgresql://postgres:<password>@postgres:5432/opentrace_v2
```

宿主机本地运行后端时需改为：
```text
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2
```

`infra/config/settings.py` 自动将 `postgresql://` 转换为 `postgresql+asyncpg://`。

### 24.2 Redis

Docker 容器地址：
```text
REDIS_URL=redis://redis:6379/10
```

逻辑 DB 分片：

| DB | 用途 |
|----|------|
| 10 | session |
| 11 | cache |
| 12 | memory |
| 13 | queue |
| 14 | rate-limit |
| 15 | pubsub |

宿主机访问：`redis://127.0.0.1:6380/10`（注意端口映射为 6380）

### 24.3 可观测性

| 组件 | 实现 | 端点 |
|------|------|------|
| 日志 | structlog | Docker logs |
| 指标 | Prometheus client | `/metrics`（observability profile） |
| 追踪 | OpenTelemetry (API/SDK/插桩) | Jaeger OTLP `:4317`，UI `:14186` |
| 运行时指标 | RuntimeCognitionHealthResponse | `/api/v1/health/runtime` |

---

## 25. 数据库模型

文件：`infra/storage/models.py`，33 个 ORM 表（SQLAlchemy 2.0+ asyncio）。

| 类别 | 模型（表名） |
|------|-------------|
| 用户与认证 | `User` (`users`) |
| 会话与消息 | `ChatSession` (`chat_sessions`)、`Message` (`messages`)、`TraceLog` (`trace_logs`) |
| 文档与附件 | `Document` (`documents`)、`DocumentChunk` (`document_chunks`)、`DocumentLLMWiki` (`document_llmwiki`)、`Attachment` (`attachments`) |
| 数据源与语义资产 | `DataSource` (`data_sources`)、`DataSourceSchema` (`data_source_schemas`)、`MetricDefinition` (`metric_definitions`)、`SchemaMetadata` (`schema_metadata`)、`TableRelationship` (`table_relationships`)、`AnalyticalSkill` (`analytical_skills`)、`MetricLineage` (`metric_lineage`) |
| 数据查询 | `DataQueryLog` (`data_query_logs`)、`QueryPattern` (`query_patterns`) |
| 记忆 | `UserMemory` (`user_memories`)、`UserMemorySettings` (`user_memory_settings`) |
| 任务 | `TaskDefinition` (`task_definitions`)、`TaskRun` (`task_runs`)、`TaskNotification` (`task_notifications`) |
| 对话增强 | `ConversationState` (`conversation_states`) |
| 审计与推理 | `AuditLog` (`audit_logs`)、`ReasoningTrace` (`reasoning_traces`)、`CognitiveEvent` (`cognitive_events`) |
| 规则与技能 | 规则相关模型、技能安装/会话配置模型 |
| 工具统计 | `ToolStat` (`tool_stats`) |
| 用户反馈 | `Feedback` (`feedback`) |
| 系统配置 | `SystemSetting` (`system_settings`)、`UserUiSettings` (`user_ui_settings`) |
| Redis 影子 | `RedisShadowKV` (`redis_shadow_kv`) |

迁移目录：`alembic/versions/`

---

## 26. 配置项

配置入口：`infra/config/settings.py`（~440 行），采用 pydantic-settings 的多继承组合模式。

### 26.1 运行端口

```text
API_PORT=14100
FRONTEND_PORT=14108
VITE_API_URL=http://localhost:14100
```

### 26.2 Kernel / Runtime 核心开关

```text
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_ENABLED=true
KERNEL_V5_ROUTING_ENABLED=true
KERNEL_L0_RULE_ROUTER_ENABLED=true
KERNEL_L1_TINY_ROUTER_ENABLED=true
KERNEL_SEMANTIC_CACHE_ENABLED=true
KERNEL_MEMORY_CONTEXT_ENABLED=true
KERNEL_CONTEXT_COMPOSER_ENABLED=true
KERNEL_COGNITIVE_PLANNER_V2_ENABLED=true
```

### 26.3 Cognitive Runtime V2 开关（均默认 true）

```text
kernel_runtime_rewrite_enabled
kernel_runtime_understanding_enabled
kernel_runtime_cognitive_planner_enabled
kernel_runtime_capability_graph_enabled
kernel_runtime_evidence_fusion_critic_enabled
kernel_runtime_artifact_composer_enabled
kernel_runtime_workspace_enabled
kernel_runtime_replay_enabled
```

### 26.4 多轮增强开关（均默认 true）

```text
kernel_clarification_gate_enabled
kernel_correction_detection_enabled
kernel_refine_replan_enabled
kernel_dst_enabled
kernel_conversation_state_enabled
kernel_context_composer_enabled
kernel_memory_value_scoring_enabled
kernel_conversation_branching_enabled
kernel_revise_loop_enabled
kernel_user_profiling_enabled
```

### 26.5 RAG / 文档

```text
RAG_MIN_EVIDENCE_SCORE=0.65
RAG_AUTO_FALLBACK_TO_WEB=true
rag_rerank_enabled=true
llmwiki_enabled=true
ATTACHMENT_UPLOAD_ENABLED=true
ATTACHMENT_MAX_SIZE_MB=20
```

### 26.6 DataAgent V2

```text
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
DATA_AGENT_V2_CONFIDENCE_THRESHOLD=0.40
DATA_AGENT_V2_SUPERVISOR_MAX_RETRIES=2
```

### 26.7 安全

```text
KERNEL_NER_MASKING_ENABLED=true
KERNEL_CANARY_AUTO_ROLLBACK_ENABLED=true
KERNEL_RULE_GRAYSCALE_ENABLED=true
```

### 26.8 LLM 配置

8 种角色的 LLM 均可独立配置 provider/model/base_url/api_key：
```text
DEFAULT_LLM_QUERY_MODEL
DEFAULT_LLM_COMPRESS_MODEL
DEFAULT_LLM_PLANING_MODEL
DEFAULT_LLM_SENIORSHORT_MODEL
DEFAULT_LLM_MIDDLESHORT_MODEL
DEFAULT_LLM_JUNIORSHORT_MODEL
DEFAULT_LLM_MINSHORT_MODEL
DEFAULT_LLM_VISION_MODEL
```

每个角色有对应的 `_PROVIDER`、`_BASE_URL`、`_API_KEY` 后缀配置。

---

## 27. 部署与运行

### 27.1 Docker 启动

```bash
bash start.sh                     # 启动所有服务
bash start.sh --with-observability # 额外启动 Prometheus + Jaeger
bash start.sh --verify             # 启动后运行验证脚本
```

等价于：
```bash
docker compose up -d --build postgres redis api agent-worker
```

### 27.2 常用操作

```bash
bash restart.sh                   # 重启（stop + start）
bash stop.sh                      # 停止
bash stop.sh --volumes            # 停止并清空数据卷
bash scripts/docker_logs.sh api   # 查看 API 日志
```

### 27.3 健康检查

```bash
curl http://127.0.0.1:14100/api/v1/health
curl http://127.0.0.1:14100/api/v1/health/deps
curl http://127.0.0.1:14100/api/v1/health/runtime
```

### 27.4 本地后端

```bash
DATABASE_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
TOKEN_DB_URL=postgresql://postgres:<password>@127.0.0.1:5432/opentrace_v2 \
REDIS_URL=redis://127.0.0.1:6380/10 \
PYTHONPATH=. python -m uvicorn gateway.api_gateway.main:app --host 0.0.0.0 --port 14100 --reload
```

### 27.5 本地前端

```bash
cd frontend
npm install
npm run dev   # → http://localhost:14108
```

### 27.6 数据库迁移

```bash
docker compose exec -T api alembic upgrade head
docker compose exec -T api alembic history --verbose
```

### 27.7 重要提示

Docker 使用 `COPY . .`（非 volume mount），源代码在构建时打入镜像。修改源代码后需重建：
```bash
docker compose build --no-cache api agent-worker && bash restart.sh
```

---

## 28. 测试体系

### 28.1 后端测试

当前共 **94 个测试文件**，~10200 行测试代码，**803 个测试用例**。

运行命令：
```bash
PYTHONPATH=. pytest -q                        # 全量回归
PYTHONPATH=. pytest tests/path/to/test.py     # 指定文件
PYTHONPATH=. pytest tests/path/to/test.py::test_func  # 指定函数
```

重点测试文件：

| 测试文件 | 覆盖范围 |
|----------|----------|
| `test_intent_lock_full_pipeline.py` | Intent Lock 全链路契约（F1-F6 修复点） |
| `test_cognitive_controls_contract.py` | IntentLock、CognitiveBudget、Relevance Anchor |
| `test_v5_routing_contract.py` | L0/L1/语义缓存路由 |
| `test_runtime_cognitive_executive.py` | CognitiveExecutive 集成 |
| `test_cognitive_runtime_contract.py` | Runtime V2 合约 |
| `test_capability_intelligence.py` (1965 loc) | Capability Intelligence 全量 |
| `test_data_agent_v2_agent_contract.py` (500 loc) | DataAgent V2 agent 层 |
| `test_data_agent_v2_supervisor_contract.py` (208 loc) | DataAgent V2 supervisor |
| `test_rag_agent_contract.py` | RAG agent |
| `test_rag_fusion_output_contract.py` | RAG/fusion 输出 |
| `test_force_mode_routing.py` (636 loc) | 强制模式路由 |
| `test_multi_turn_intent_inheritance.py` | 多轮意图继承 |
| `test_clarification_gate.py` | 澄清门控 |
| `test_orchestrator_v4_contract.py` | V4 编排器 |
| `test_identity_guard.py` | 身份守护 |
| `test_entity_filter_regression.py` (423 loc) | 实体过滤回归 |

### 28.2 前端测试

```bash
cd frontend
npm run test      # Vitest + Testing Library
npm run build     # 生产构建
```

---

## 29. 开发规范与维护建议

1. **所有聊天请求必须经过 CognitiveKernel**：不可绕过 Kernel 直接调用 Agent。
2. **简单问题优先 L0 / Intent Lock**：不要让 "你好""你能做什么" 进入 RAG、memory、planner。Intent Lock 在 Kernel 入口已经做了分类，所有下游应尊重这个分类。
3. **不要覆盖 raw_user_query**：重写引擎生成 canonical query，但不能替代 `raw_user_query`。Intent Lock 的 `protected_intent` 字段保护用户原始意图。
4. **能力选择必须受 Intent Lock 约束**：Planner 输出需符合 `allowed_capabilities` / `disallowed_capabilities`。约束层是最后防线，但最好在 Planner prompt 中提前告知约束。
5. **RAG 只做证据，不做无条件答案**：低相关证据必须被 answerability gate 和 relevance anchor 拦截。
6. **Memory 按 CognitiveBudget 注入**：简单问答默认不注入记忆上下文，避免噪声污染。
7. **新增能力要补合约测试**：路由、配置、API、AgentResult metadata 都要覆盖。
8. **保持文档事实化**：不要把规划中的模块写成已完成，除非代码存在且测试通过。
9. **注意双运行时差异**：流式目前只走 V4，不走 V2 CognitiveExecutive。修改核心管线时注意两边对齐。

---

## 30. 已知风险与后续优化

### 30.1 当前风险

- **新旧运行时并存**：`CognitiveExecutive` 与 `OrchestratorV4` 融合/审校/规划逻辑有重复，职责边界需继续收敛。Streaming 路径完全不走 V2 Runtime，需要在两边维护一致的行为。
- **Capability Intelligence 退化风险**：Phase 1+2 默认全开，能力推荐受历史反馈影响，需要持续监控执行记忆中的退化信号。
- **Agent Bus 依赖**：Worker 依赖 Redis 和独立进程，部署不完整时可能产生执行等待或回退路径。
- **配置漂移风险**：约 250 个 feature flag，部分 flag 之间存在隐含依赖关系，需要在文档中保持同步。
- **命名不一致**：Intent Lock 使用点分命名空间（`tool.weather`），实际注册使用不同名称（`get_weather`），虽然已有 `_CAPABILITY_NORMALIZE_MAP` 补救，但新加能力时容易引入新的不一致。
- **PlanAgent 标记为 DEPRECATED** 但仍被 V4 编排器广泛使用，V2 Runtime 中也有 CognitivePlannerV2，两套规划器长期并存增加维护成本。

### 30.2 优先优化方向

1. **Intent Lock 贯穿所有路径**：将 Intent Lock 注入到 fusion、critic、memory selector 中，不仅在 planner 和 constraint layer。
2. **合并 V4 与 Runtime 的融合/审校逻辑**：FusionEngine、FusionEngineV2、CriticEngine、CriticEngineV2 存在重叠，应统一到 Evidence lifecycle。
3. **为复杂度分级建立评测集**：L0/L1/L2 的阈值需要更系统的评测数据支撑。
4. **建立能力命名规范**：统一 intent_lock 名称与实际注册名称，在注册时就做映射，而非后期 normalize。
5. **DataAgent V2 增加真实数据源集成回归**：当前测试以单元/合约测试为主，缺少对真实数据库的端到端回归。
6. **增强前端 Trace UI**：展示 raw query、protected intent、selected capabilities、relevance score 等 Intent Lock 相关信息，便于调试和排障。
7. **文档自动校验**：从代码中自动提取配置项、feature flags、router 列表，与文档对比防止漂移。

---

## 附录：推荐代码阅读顺序

1. `infra/config/settings.py` — 了解所有 feature flags 和配置项
2. `gateway/api_gateway/routers/chat.py` — 聊天入口，了解 ChatRequest → RuntimeContext 的构建过程
3. `kernel/cognitive_controls.py` — Intent Lock、CognitiveBudget、classify_intent() 分类规则
4. `kernel/cognitive_kernel.py` — CognitiveKernel.run() / stream() 主流程
5. `kernel/query_router_v2.py` — L0 规则路由
6. `kernel/tiny_router.py` + `kernel/complexity_engine.py` + `kernel/semantic_cache.py` — V5 路由层
7. `kernel/orchestrator_v4.py` — V4 编排器完整管线
8. `kernel/runtime/cognitive_executive.py` — V2 Runtime 入口
9. `kernel/runtime/cognitive/cognitive_planner_v2.py` — V2 认知规划器
10. `kernel/runtime/constraint_layer.py` — 约束层 5 维守卫
11. `agents/rag_agent.py` — RAG Agent 完整检索管线
12. `agents/data_agent_v2/supervisor.py` — DataAgent V2 Supervisor
13. `kernel/capability_intelligence/profiler.py` — Capability Intelligence 入口
14. `model/model_gateway/gateway.py` — 模型网关 LLMRole 枚举和 ModelGateway
15. `memory/evolution/router.py` — EvolutionMemoryRouter 记忆路由
