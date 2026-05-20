# OpenTrace 项目代码梳理（Codex 版）

> 本文档以当前仓库代码为事实来源，参考原 `docs/service/service_codex.md` 的组织方式重新梳理。
>
> 目标是提供一份比原文档更完整的项目说明，覆盖架构、入口、核心链路、配置、数据库模型、运行部署、测试与排障。
>
> 最后更新：2026-05-20

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
9. [认知内核](#9-认知内核)
10. [编排器、路由与多轮增强](#10-编排器路由与多轮增强)
11. [Agent 集群](#11-agent-集群)
12. [DataAgent V2 认知型数据智能体](#12-dataagent-v2-认知型数据智能体)
13. [数据源、Knowledge Assets 与 Text2SQL](#13-数据源knowledge-assets-与-text2sql)
14. [RAG 与文档系统](#14-rag-与文档系统)
15. [记忆系统](#15-记忆系统)
16. [工具、技能、插件与连接器](#16-工具技能插件与连接器)
17. [规则引擎与灰度发布](#17-规则引擎与灰度发布)
18. [执行平面与 Agent Bus](#18-执行平面与-agent-bus)
19. [模型网关](#19-模型网关)
20. [安全、审计与可解释性](#20-安全审计与可解释性)
21. [基础设施与持久化](#21-基础设施与持久化)
22. [数据库模型](#22-数据库模型)
23. [配置项](#23-配置项)
24. [部署与运行](#24-部署与运行)
25. [测试体系](#25-测试体系)
26. [开发规范与维护建议](#26-开发规范与维护建议)
27. [排障入口](#27-排障入口)
28. [已知风险与后续优化](#28-已知风险与后续优化)

---

## 1. 项目定位

OpenTrace 是一个以 **Cognitive Kernel** 为中枢的智能体操作系统。它不是单一聊天机器人，而是把用户请求统一接入后，按意图、复杂度、历史状态、数据源上下文和工具能力路由到不同认知模块。

当前代码体现出的核心目标：

- 统一入口：所有聊天请求进入 `gateway/api_gateway/routers/chat.py`，再进入 `kernel.cognitive_kernel.CognitiveKernel`。
- 分层路由：优先使用 L0 规则、语义缓存、TinyRouter、复杂度评分处理简单请求，复杂请求进入完整编排。
- V4 编排：`PlanAgent -> Dispatcher -> Agent Cluster -> Fusion -> Critic -> Epistemic Annotation`。
- 多 Agent 能力：Data、RAG、Web、Tool、Skills、Rule、Vision 等 Agent 可被规划器和调度器调用。
- 多轮增强：会话状态、引用消解、上下文压缩、纠正重规划、主动追问、记忆反馈共同工作。
- 数据认知：DataAgent V2 默认启用，将数据查询从“NL2SQL 工具”升级为“认知型数据中枢”。
- 可观测与审计：TraceLog、ReasoningTrace、CognitiveEvent、AuditLog、XAI trace 等记录运行过程。

---

## 2. 当前代码状态摘要

| 维度 | 当前状态 |
|------|----------|
| 后端入口 | FastAPI，默认端口 `14100` |
| 前端入口 | React/Vite，默认端口 `14108` |
| 编排版本 | `KERNEL_ORCHESTRATOR_VERSION=v4` |
| DataAgent | V2 默认启用，V1 fallback 默认关闭 |
| 数据源支持 | MySQL、Postgres、ClickHouse、Doris |
| RAG | 文档、chunk、LLMWiki、pgvector/embedding、rerank |
| Redis | 会话、缓存、记忆、队列、pubsub/stream bus |
| 数据库 | PostgreSQL 16 + pgvector |
| 测试现状 | 后端全量测试通过；前端 build 通过；前端 Vitest 存在若干 UI contract 失败 |

关键默认配置：

```env
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_ENABLED=true
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
KERNEL_V5_ROUTING_ENABLED=true
KERNEL_CONVERSATION_STATE_ENABLED=true
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
| 迁移 | Alembic |
| 数据库 | PostgreSQL 16 |
| 向量能力 | pgvector |
| 缓存/队列 | Redis 7 |
| LLM SDK | OpenAI-compatible API、DashScope |
| 配置 | pydantic-settings + `.env` |
| 序列化 | Pydantic、orjson |
| SQL | sqlglot、自研 data_cognition 管线 |
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
| Frontend | 本地 Vite `14108`，Docker compose 未单独定义前端服务 |
| PostgreSQL | `opentrace_postgres`, host `${POSTGRES_PORT:-5432}` |
| Redis | `opentrace_redis`, host `${REDIS_PORT:-6380}` |
| Prometheus | `opentrace_prometheus`, `14190` |
| Jaeger | `opentrace_jaeger`, UI `14186`, OTLP `4317` |

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
                                │ ChatRequest / KernelRequest
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ CognitiveKernel                                               │
│ L0 rules / semantic cache / tiny router / context composer    │
└───────────────────────────────┬─────────────────────────────┘
                                │ OrchestratorRequest
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ CognitiveOrchestratorV4                                      │
│ Plan -> Dispatch -> Agent Results -> Fusion -> Critic         │
└──────────────┬──────────────┬──────────────┬────────────────┘
               │              │              │
               ▼              ▼              ▼
       ┌─────────────┐ ┌─────────────┐ ┌──────────────┐
       │ Agent 集群   │ │ ModelGateway │ │ Execution    │
       │ Data/RAG/...│ │ LLM roles    │ │ SQL/Tools/DAG │
       └──────┬──────┘ └──────┬──────┘ └──────┬───────┘
              │               │               │
              ▼               ▼               ▼
       PostgreSQL       OpenAI-compatible     Redis / Bus
       pgvector         DashScope/Qwen        Audit / XAI
```

实际系统可以分为六层：

1. **交互层**：前端页面、API client、SSE 消息处理。
2. **网关层**：认证、会话、附件、权限、路由、错误封装。
3. **认知层**：路由、规划、对话状态、上下文压缩、引用消解。
4. **执行层**：Agent、工具、数据查询、RAG、规则、技能。
5. **模型层**：按角色调度 LLM/Embedding/Rerank。
6. **基础设施层**：PostgreSQL、Redis、审计、事件、可观测、部署脚本。

---

## 5. 目录结构

```text
opentrace/
├── agent_runtime/              # Agent runtime、planner、executor、critic、market、reflector
├── agents/                     # Data/RAG/Web/Tool/Skills/Rule/Vision Agent
│   └── data_agent_v2/           # DataAgent V2 认知数据智能体子系统
├── alembic/                    # Alembic 迁移
├── connectors/                 # connector SDK 与内置连接器
├── deploy/                     # Docker、Helm、K8s、Prometheus 配置
├── docs/                       # 项目文档与 catalog
├── evolution/                  # learning、feedback、self-play、meta-learning、data flywheel
├── execution/                  # DAG、workflow、sandbox、tool router、data executor
├── frontend/                   # React/Vite 前端
├── gateway/                    # FastAPI API gateway
├── infra/                      # config/storage/cache/security/observability/message bus
├── kernel/                     # Cognitive Kernel、V4 Orchestrator、routing、fusion、critic
├── memory/                     # working/semantic/episodic/procedural/evolution memory
├── model/                      # LLM gateway、adapter、embedding、rerank
├── plugins/                    # chart/code/data/file/tool 插件
├── safety/                     # guardrails、policy、masking、canary、xai、audit
├── sandbox_runtime/            # sandbox providers
├── scripts/                    # 启停、验证、迁移、schema 同步脚本
├── sdk/                        # plugin/python SDK
├── services/                   # 服务层辅助模块
├── skills/                     # skills runtime、store、installed
├── tests/                      # 后端合约与回归测试
├── tools/                      # tool registry 和内置工具
├── docker-compose.yml
├── pyproject.toml
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
| `DatabasesPage.tsx` | 数据源 CRUD、连接测试、schema 同步、语义配置、DataAgent V2 知识资产入口 |
| `KnowledgeAssetsPage.tsx` | 知识资产管理入口 |
| `DocumentsPage.tsx` | 文档上传、列表、预览、删除、检索 |
| `SkillsPage.tsx` | 技能市场、技能创建、安装、测试、会话绑定 |
| `RulesPage.tsx` | 规则管理、版本、灰度、发布/回滚 |
| `MemoryPage.tsx` | 用户记忆、记忆设置 |
| `TasksPage.tsx` | 任务定义、运行、事件触发、通知 |
| `AuditPage.tsx` | 审计日志查询 |
| `IntegrationsPage.tsx` | 外部连接器管理 |
| `PermissionsPage.tsx` | 权限相关页面 |
| `SettingsPage.tsx` | UI/用户设置 |
| `LoginPage.tsx` / `RegisterPage.tsx` | 登录注册 |

### 6.2 核心组件

| 组件 | 作用 |
|------|------|
| `ChatInput.tsx` | 输入框、快捷标签、附件、发送控制 |
| `ChatMessage.tsx` | 消息渲染、工具卡片、表格/JSON/Markdown 结构化显示 |
| `MessageList.tsx` | 消息列表 |
| `ReasoningChain.tsx` | 推理链展示 |
| `ExecutionGraphPanel.tsx` | 执行图展示 |
| `DagTimeline.tsx` | DAG 时间线 |
| `DecisionTraceCard.tsx` | 决策轨迹卡片 |
| `DataQueryResult.tsx` | 数据查询结果 |
| `DataTableChart.tsx` | 表格/图表切换 |
| `DatabaseTypeSelect.tsx` | 数据源类型选择 |
| `MetricDefinitionEditor.tsx` | 指标定义编辑 |
| `TableRelationGraph.tsx` | 表关系图 |
| `SkillTemplateEditor.tsx` | 技能模板编辑 |
| `MultiQuestionCards.tsx` | 多子问题渲染 |
| `MessageVersionTree.tsx` | 分支/版本历史 |

### 6.3 API Client

`frontend/src/api/client.ts` 统一封装后端调用：

- 默认相对路径：`/api/v1`
- fallback 直连：`${VITE_API_URL || http://localhost:14100}/api/v1`
- 包含 auth、documents、conversations、databases、chat、rules、skills、tasks、memories 等调用。
- `apiFetch()` 会在相对路径失败时 fallback 到 `BACKEND_DIRECT`。

### 6.4 前端验证状态

- `npm run build` 当前通过。
- `npm test -- --run` 当前仍有 UI contract 失败，集中在组件文案、DAG timeline 事件和 ChatMessage tool card 渲染，不属于 DataAgent V2 后端链路问题。

---

## 7. API 网关

FastAPI 应用入口：`gateway/api_gateway/main.py`。

主要职责：

- 创建 FastAPI app。
- 注册 `/api/v1` 下所有业务 router。
- 注入 request id、响应耗时。
- 统一异常处理。
- 管理 memory event subscriber 生命周期。

### 7.1 Router 清单

| 文件 | 作用 |
|------|------|
| `auth.py` | 注册、登录、token、当前用户 |
| `chat.py` | 聊天主路由，同步/SSE、附件、图控制、反馈、恢复 |
| `conversations.py` | 会话、消息、分支、归档 |
| `documents.py` | 文档上传、解析、chunk、检索 |
| `databases.py` | 数据源管理、连接测试、schema 同步、查询、分析、语义配置 |
| `data.py` | `/data/query` 兼容查询入口；V2 开启时走 `DataAgent` |
| `metrics.py` | DataAgent V2 指标定义管理 |
| `table_relationships.py` | 表关系管理 |
| `analytical_skills.py` | 分析技能资产管理 |
| `skills.py` | 技能市场、创建、安装、测试、会话绑定 |
| `rules.py` | 规则 CRUD、版本、灰度、发布、回滚 |
| `tasks.py` | 任务定义、运行、事件、通知 |
| `memories.py` | 记忆 CRUD、记忆设置 |
| `feedback.py` | 用户反馈 |
| `audit.py` | 审计日志 |
| `cognitive.py` | 认知事件回放 |
| `connectors.py` | 连接器授权、资源、同步 |
| `sandbox.py` | 沙箱产物下载 |
| `health.py` | liveness、deps、runtime |
| `admin.py` | 管理接口 |
| `ui_settings.py` | UI 设置 |

### 7.2 关键响应结构

聊天最终响应通常包含：

- `content`
- `decision_type`
- `reasoning_steps`
- `execution_graph`
- `citations`
- `annotations`
- `metadata`
- `state_patch`
- `result_refs`

`result_refs` 是前端和多轮引用消解的重要桥梁，DataAgent V2 已补齐 SQL/table 类型引用。

---

## 8. 聊天主链路

聊天主入口：`gateway/api_gateway/routers/chat.py`。

### 8.1 ChatRequest 关键字段

| 字段 | 含义 |
|------|------|
| `query` | 用户输入 |
| `session_id` | 会话 ID |
| `stream` | 是否 SSE |
| `web_enabled` | 是否允许 web search |
| `enabled_skills` / `disabled_skills` | 会话技能控制 |
| `tool_permission_token` | 工具权限 token |
| `confirmation_granted` | 危险/敏感动作确认 |
| `data_source_id` / `data_source_name` | 数据源上下文 |
| `force_database` | 强制数据库上下文 |
| `force_mode` | 快捷标签或强制模式 |
| `clarify_context` / `clarify_question_id` | 追问上下文 |
| `parent_message_id` | 分支/再生成依据 |
| `attachment_ids` | 附件注入 |

### 8.2 同步链路

```text
POST /api/v1/chat
  -> auth user
  -> create/load session
  -> assemble metadata: data source, memory, attachments, force mode
  -> CognitiveKernel.run()
  -> Orchestrator V4
  -> persist user/assistant messages
  -> trace/audit/state patch/result refs
  -> response
```

### 8.3 SSE 链路

流式模式负责输出：

- token/answer chunk
- reasoning step
- execution graph update
- tool/agent start/complete
- force mode event
- clarification event
- final answer

`frontend/src/store/chat.ts` 与 `frontend/src/api/client.ts` 负责消费事件并更新 UI 状态。

---

## 9. 认知内核

核心入口：`kernel/cognitive_kernel.py`。

职责：

- 接收 API 层整理后的 `KernelRequest`。
- 尝试 L0/L1/L2 分层路由。
- 管理 streaming 与同步输出。
- 注入 context composer、多轮状态、主动记忆。
- 调用 `CognitiveOrchestratorV4`。

关键模块：

| 模块 | 作用 |
|------|------|
| `query_router_v2.py` | L0 规则路由 |
| `semantic_cache.py` | 语义缓存 |
| `tiny_router.py` | L1 小模型分类 |
| `complexity_engine.py` | 复杂度评分 |
| `context_assembler.py` | 上下文装配 |
| `context_composer.py` | 长上下文压缩 |
| `turn_context.py` | 单轮上下文 |
| `token_counter.py` | token 预算估算 |
| `history_retriever.py` | 历史检索 |
| `identity/system_identity.py` | 系统身份回答 |

---

## 10. 编排器、路由与多轮增强

主编排器：`kernel/orchestrator_v4.py`。

### 10.1 V4 编排流程

```text
OrchestratorRequest
  -> PlanAgent 生成 subtasks
  -> Dispatcher 调度 Agent
  -> AgentResult 收集
  -> FusionEngine 融合
  -> CriticEngine 审校
  -> epistemology 标注
  -> OrchestratorResponse
```

### 10.2 PlanAgent

`kernel/plan_agent.py` 负责：

- 判断是否使用 data/rag/web/tool/skills/rule 等 Agent。
- 注入 `data_source_id`。
- 处理 force mode。
- 支持多子问题拆分。
- 支持对话状态、追问、纠正上下文。

### 10.3 DAG 与调度

| 模块 | 作用 |
|------|------|
| `dag_plan.py` | DAG 数据结构 |
| `dag_scheduler.py` | 依赖调度、并行执行 |
| `dispatcher.py` | Agent 并发、超时、降级 |
| `plan_memory.py` | 规划记忆 |

### 10.4 多轮增强

| 模块 | 功能 |
|------|------|
| `conversation_state.py` | 结构化会话状态，保存 active topic/entity/mode/data source/result refs |
| `reference_resolver.py` | “刚才那个”“第二个结果”等引用消解 |
| `clarification_gate.py` | 信息不足时主动追问 |
| `refine_planner.py` | 用户纠正后的增量重规划 |
| `dialogue_state_tracker.py` | 槽位与意图状态追踪 |
| `context_composer.py` | 历史压缩与摘要 |
| `preference_layers.py` | 用户偏好层 |

---

## 11. Agent 集群

Agent 抽象定义在 `agents/base.py`：

- 输入：`TaskMessage`
- 输出：`AgentResult`
- 支持 `metadata`、`evidence`、`agent_trace`

### 11.1 Agent 清单

| Agent | 文件 | 作用 |
|-------|------|------|
| DataAgent | `agents/data_agent.py` | 数据查询；默认委托 DataAgent V2 Supervisor |
| RagAgent | `agents/rag_agent.py` | 文档、chunk、LLMWiki、记忆检索 |
| WebAgent | `agents/web_agent.py` | Web 搜索 |
| ToolAgent | `agents/tool_agent.py` | 通用工具调用 |
| SkillsAgent | `agents/skills_agent.py` | 技能检索/执行 |
| RuleEngineAgent | `agents/rule_engine_agent.py` | YAML 规则匹配 |
| VisionAgent | `agents/vision_agent.py` | 视觉/多模态分析 |
| Worker | `agents/worker.py` | Redis Agent Bus worker |

### 11.2 注册方式

- `agents/__init__.py` 导出核心 Agent。
- `agents/registry.py` 提供注册与查找。
- `kernel/orchestrator_v4.py` 初始化时注册 `DataAgent()` 等能力。
- `agents/worker.py` 在 agent bus 模式下消费任务。

---

## 12. DataAgent V2 认知型数据智能体

DataAgent V2 是当前项目数据查询的默认主路径。入口仍然是 `agents/data_agent.py` 中的 `DataAgent`，但当 `DATA_AGENT_V2_ENABLED=true` 时会委托给 `agents/data_agent_v2/supervisor.py`。

### 12.1 默认配置

```env
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
DATA_AGENT_V2_KNOWLEDGE_RETRIEVER_ENABLED=true
DATA_AGENT_V2_INTENT_ENABLED=true
DATA_AGENT_V2_ENTITY_ENABLED=true
DATA_AGENT_V2_METRIC_ENABLED=true
DATA_AGENT_V2_TIME_ENABLED=true
DATA_AGENT_V2_JOIN_ENABLED=true
DATA_AGENT_V2_SEMANTIC_ENABLED=true
DATA_AGENT_V2_PLANNER_ENABLED=true
DATA_AGENT_V2_SQL_COMPILER_ENABLED=true
DATA_AGENT_V2_VERIFIER_ENABLED=true
DATA_AGENT_V2_REFLECTION_ENABLED=true
DATA_AGENT_V2_CRITIC_ENABLED=true
```

### 12.2 目标架构

```text
DataAgent
  -> DataAgentV2Supervisor
      -> KnowledgeRetrieverAgent
      -> DAG:
          IntentAgent
          EntityAgent
          MetricAgent
          TimeReasoningAgent
          JoinAgent
          SemanticAgent
          PlannerAgent
          SQLCompilerAgent
          VerificationAgent
      -> SQL execution
      -> ReflectionAgent
      -> StatisticalAgent / InsightAgent / VisualizationAgent
      -> DataCriticAdapter
      -> Learning pipeline
```

### 12.3 子 Agent 职责

| 子 Agent | 文件 | 职责 |
|----------|------|------|
| KnowledgeRetrieverAgent | `knowledge_retriever.py` | 读取指标定义、schema metadata、表关系、分析技能、query patterns |
| IntentAgent | `intent_agent.py` | 识别 aggregation、ranking、trend、metadata 等分析意图 |
| EntityAgent | `entity_agent.py` | 用户实体词到表/列的映射 |
| MetricAgent | `metric_agent.py` | 指标名到字段、公式、聚合方式的映射 |
| TimeReasoningAgent | `time_reasoning_agent.py` | 解析近 7 天、同比、环比等时间表达 |
| JoinAgent | `join_agent.py` | 推理 join path、cardinality、放大风险 |
| SemanticAgent | `semantic_agent.py` | 业务语义上下文 |
| PlannerAgent | `planner_agent.py` | 生成逻辑查询计划 |
| SQLCompilerAgent | `sql_compiler_agent.py` | 确定性编译 SQL |
| VerificationAgent | `verification_agent.py` | SQL 安全、语义、指标覆盖、实体覆盖验证 |
| ReflectionAgent | `reflection_agent.py` | 执行失败、空结果、异常结果后的修复 |
| StatisticalAgent | `statistical_agent.py` | 统计画像、异常、趋势 |
| InsightAgent | `insight_agent.py` | 自然语言洞察 |
| VisualizationAgent | `visualization_agent.py` | 图表建议 |
| DataCriticAdapter | `data_critic.py` | 质量评估与置信度解释 |
| FeedbackCollectorAgent | `feedback_collector.py` | 用户反馈分类 |
| PatternExtractorAgent | `pattern_extractor.py` | 成功模式抽取 |
| KnowledgeUpdaterAgent | `knowledge_updater.py` | 知识资产更新 |
| MetricRefinerAgent | `metric_refiner.py` | 指标精炼 |

### 12.4 CognitiveContext

`agents/data_agent_v2/types.py` 中的 `CognitiveContext` 是子 Agent 间共享状态，包含：

- 输入：query、data_source_id、dialect、schema_hint、table_names、table_columns、semantic_config
- 推理结果：intent、entities、metrics、time_window、join_paths、semantic_context、logical_plan、compiled_sql、verification_report
- 知识层：matched_metrics、matched_skills、matched_relationships、column_semantics、pattern_hit
- 执行结果：execution_rows、execution_row_count、execution_error、reflection_rounds
- 学习层：learning_signals、refined_metrics
- 分析层：statistical_report、insights、visualization_config

### 12.5 当前已补齐的主链路行为

- V2 默认启用，V1 fallback 默认关闭。
- `/api/v1/data/query` 在 V2 开启时也走 `DataAgent().execute()`。
- Supervisor 会加载 datasource/schema/dialect/DSN。
- Knowledge Layer 自动注入 DB session。
- DAG 分层执行时持续注入并合并 `CognitiveContext`。
- 子 Agent 返回 dict 或 `AgentResult` 都会在 Supervisor 边界归一化。
- direct SQL、dry-run、metadata fast path 已支持。
- verified `compiled_sql` 由 SQLExecutor 执行。
- Reflection 修复 SQL 后会重新执行。
- 最终 metadata 包含 `data_source_id`、`mode=data_agent_v2`、`sql`、`rows`、`row_count`、`result_refs`、`verification_report`。

### 12.6 返回协议

DataAgent V2 返回 `AgentResult`：

```json
{
  "agent_type": "data",
  "status": "success",
  "content": "查询返回 N 行数据...",
  "confidence": 0.85,
  "metadata": {
    "rows": [],
    "row_count": 0,
    "sql": "SELECT ...",
    "data_source_id": "...",
    "mode": "data_agent_v2",
    "verification_report": {},
    "intent": {},
    "metrics_used": [],
    "entities_used": [],
    "result_refs": []
  },
  "evidence": [],
  "agent_trace": {
    "pipeline": "data_agent_v2"
  }
}
```

---

## 13. 数据源、Knowledge Assets 与 Text2SQL

### 13.1 数据源管理

路由：`gateway/api_gateway/routers/databases.py`

支持能力：

- 创建/更新/删除数据源。
- host 校验，阻止 Docker 内部不可达主机名。
- 测试连接。
- 同步 schema。
- 查询数据库。
- 简单分析。
- 语义映射 CRUD。

支持数据库类型：

- `mysql`
- `postgres`
- `clickhouse`
- `doris`

### 13.2 `/data/query` 行为

路由：`gateway/api_gateway/routers/data.py`

- 当 `DATA_AGENT_V2_ENABLED=true`：走 `DataAgent` / V2 Supervisor。
- 当 `DATA_AGENT_V2_ENABLED=false`：保留旧 Text2SQL pipeline，用于兼容和回归。

### 13.3 Knowledge Assets

DataAgent V2 相关知识资产表：

| 表 | 作用 |
|----|------|
| `metric_definitions` | 指标目录，公式、别名、底层字段、审批状态 |
| `schema_metadata` | 列级业务语义，主外键、时间列、指标/维度标记 |
| `table_relationships` | 表连接关系、cardinality、放大风险、成功率 |
| `analytical_skills` | 可复用分析模式，如 cohort、funnel、ranking |
| `query_patterns` | 成功查询模式记忆 |
| `metric_lineage` | 指标血缘 |
| `cognitive_events` | DataAgent V2 管线事件 |

相关路由：

- `gateway/api_gateway/routers/metrics.py`
- `gateway/api_gateway/routers/table_relationships.py`
- `gateway/api_gateway/routers/analytical_skills.py`

### 13.4 旧 data_cognition 管线

目录：`kernel/data_cognition/`

关键模块：

- `semantic_parser.py`
- `schema_linker.py`
- `query_planner.py`
- `logical_plan.py`
- `sql_builder.py`
- `sql_validator.py`
- `sql_ranker.py`
- `sql_reflector.py`
- `sql_rewriter.py`
- `query_executor.py`
- `table_graph.py`
- `explanation.py`

虽然 V2 默认启用，但旧管线仍保留用于兼容测试、fallback 可选项和部分低层能力复用。

---

## 14. RAG 与文档系统

### 14.1 路由与模型

路由：`gateway/api_gateway/routers/documents.py`

核心表：

- `documents`
- `document_chunks`
- `document_llmwiki`

### 14.2 RAG Agent

文件：`agents/rag_agent.py`

职责：

- 根据 query 检索文档 chunk。
- 检索 LLMWiki 问答条目。
- 检索用户记忆。
- 应用动态阈值与 rerank。
- 输出 citations、chunks、vector_chunks、llmwiki_entries、quality metadata。

### 14.3 文档处理

支持：

- 文本上传。
- 文件 metadata。
- chunk strategy。
- embedding_json / embedding_vector 双字段。
- pgvector 可选。

---

## 15. 记忆系统

目录：`memory/`

| 子系统 | 作用 |
|--------|------|
| `working_memory` | 当前会话工作记忆、summary slot |
| `semantic_memory` | 长期语义记忆 |
| `episodic_memory` | 情节记忆 |
| `procedural_memory` | 程序性记忆 |
| `memory_router` | 多源记忆检索与路由 |
| `evolution` | 记忆演化、价值评分、衰减 |

数据库表：

- `user_memories`
- `user_memory_settings`
- `feedback`

聊天中会使用：

- 用户显式反馈。
- like/dislike 对记忆价值加权。
- active memory detection。
- context composer 对历史进行压缩。

---

## 16. 工具、技能、插件与连接器

### 16.1 工具

目录：

- `tools/`
- `kernel/tools/`
- `agents/tool_agent.py`

常见工具：

- 时间/日期。
- 天气。
- 计算。
- Web search。
- Python/code execution 相关能力。

### 16.2 技能系统

目录：

- `skills/`
- `agents/skills_agent.py`
- `gateway/api_gateway/routers/skills.py`

能力：

- 技能创建。
- 技能安装。
- 技能测试。
- 会话绑定。
- marketplace/store/installed/runtime 管理。

### 16.3 插件与连接器

目录：

- `plugins/`
- `connectors/`
- `gateway/api_gateway/routers/connectors.py`

插件类型：

- chart
- code
- data
- file
- tool

连接器支持授权、资源列举、同步等基本流程。

---

## 17. 规则引擎与灰度发布

路由：`gateway/api_gateway/routers/rules.py`

Agent：`agents/rule_engine_agent.py`

相关配置：

```env
KERNEL_RULE_GRAYSCALE_ENABLED=true
KERNEL_RULE_GRAYSCALE_DEFAULT_PERCENTAGE=100
KERNEL_CANARY_AUTO_ROLLBACK_ENABLED=true
KERNEL_CANARY_ERROR_RATE_THRESHOLD=0.10
KERNEL_CANARY_LATENCY_MULTIPLIER=2.0
KERNEL_CANARY_MIN_SAMPLES=100
```

支持能力：

- YAML 规则管理。
- 版本创建。
- 灰度发布。
- promote。
- rollback。
- 自动回滚阈值。

---

## 18. 执行平面与 Agent Bus

目录：`execution/`

| 模块 | 作用 |
|------|------|
| `dag_engine/` | DAG 执行引擎 |
| `workflow_engine/` | workflow 执行 |
| `sandbox/` | 沙箱执行 |
| `scheduler/` | 调度 |
| `tool_router/` | 工具路由 |
| `data/` | DBRouter、SQLExecutor、query intents |

Agent Bus：

- `infra/message_bus/agent_bus.py`
- `agents/worker.py`

配置：

```env
KERNEL_AGENT_BUS_ENABLED=false
KERNEL_AGENT_BUS_MODE=pubsub
KERNEL_AGENT_BUS_GROUP=agent-workers
KERNEL_AGENT_BUS_CONSUMER=worker-1
KERNEL_AGENT_BUS_MAX_RETRY=2
```

Bus 支持 pubsub 和 stream，两者用于不同可靠性要求的任务分发。

---

## 19. 模型网关

目录：`model/`

核心文件：`model/model_gateway/gateway.py`

### 19.1 LLM 角色

配置类中定义了多个模型角色：

| 角色 | 默认模型 |
|------|----------|
| query | `qwen3.6-plus` |
| planning | `qwen3.6-plus` |
| compress | `qwen3.5-27b` |
| seniorshort | `qwen3-14b` |
| middleshort | `qwen3-8b` |
| juniorshort | `qwen3-1.7b` |
| minshort | `qwen3-0.6b` |
| vision | `qwen3.6-vl-plus` |

### 19.2 Embedding 与 Rerank

Embedding：

```env
EMBEDDING_PROVIDER=dashscope
EMBEDDING_MODEL_NAME=text-embedding-v3
EMBEDDING_DIMS=1024
```

Rerank：

```env
RERANK_PROVIDER=heuristic
RERANK_MODEL_NAME=BAAI/bge-reranker-v2-m3
```

---

## 20. 安全、审计与可解释性

### 20.1 安全

相关目录：

- `infra/security/`
- `infra/guards/`
- `safety/`

能力：

- JWT。
- bcrypt 密码哈希。
- 注册开关和邮箱域限制。
- 数据库 host allowlist。
- SQL read-only 验证。
- tool permission token。
- NER PII masking。

### 20.2 审计

表：

- `audit_logs`
- `trace_logs`
- `reasoning_traces`
- `cognitive_events`

路由：

- `/api/v1/audit/*`
- `/api/v1/cognitive-events/replay`
- `/api/v1/xai/*`

### 20.3 可解释性

相关模块：

- `kernel/protocol/events.py`
- `kernel/protocol/mcp.py`
- `kernel/epistemology/*`
- `safety/xai/*`
- `infra/observability/tracer.py`

输出包括：

- reasoning steps。
- execution graph。
- evidence。
- confidence。
- critique。
- annotations。
- result refs。

---

## 21. 基础设施与持久化

### 21.1 配置

统一配置入口：

- `infra/config/settings.py`
- `.env.example`

`Settings` 聚合：

- DatabaseSettings
- RedisSettings
- LLMSettings
- EmbeddingSettings
- RerankSettings
- JWTSettings
- SMTPSettings
- RegistrationSettings
- OTelSettings
- AppSettings

### 21.2 存储

目录：`infra/storage/`

核心：

- `database.py`：engine、session、Base、初始化。
- `models.py`：ORM models。

### 21.3 Redis

用途：

- session。
- cache。
- memory。
- queue。
- rate limit。
- pubsub。

`redis_shadow_kv` 表提供 Redis shadow/fallback。

### 21.4 可观测性

目录：

- `infra/observability/`
- `deploy/docker/prometheus.yml`

组件：

- structlog。
- OpenTelemetry。
- Prometheus。
- Jaeger。

---

## 22. 数据库模型

主要模型位于 `infra/storage/models.py`。

### 22.1 用户与会话

| 表 | 说明 |
|----|------|
| `users` | 用户、角色、审批状态 |
| `chat_sessions` | 会话、标题、标签、归档 |
| `messages` | 每条消息，支持 tool call、多模态、版本 |
| `trace_logs` | 回合级追踪聚合 |
| `conversation_states` | 多轮状态、active topic/entity/result refs |
| `attachments` | 会话附件、文本/图片内容、hash 去重 |

### 22.2 文档/RAG

| 表 | 说明 |
|----|------|
| `documents` | 文档元数据与原文 |
| `document_chunks` | chunk、embedding、metadata |
| `document_llmwiki` | 文档生成式问答索引 |

### 22.3 数据源与 DataAgent V2

| 表 | 说明 |
|----|------|
| `data_sources` | 外部数据库连接配置 |
| `data_source_schemas` | schema_json、semantic_mappings、auto_metadata |
| `data_query_logs` | 数据查询日志 |
| `metric_definitions` | 指标目录 |
| `schema_metadata` | 列级业务语义 |
| `table_relationships` | 表关系 |
| `analytical_skills` | 分析技能模板 |
| `query_patterns` | 成功查询模式 |
| `metric_lineage` | 指标血缘 |
| `cognitive_events` | DataAgent V2 审计事件 |

### 22.4 记忆、任务、审计

| 表 | 说明 |
|----|------|
| `user_memories` | 用户记忆 |
| `user_memory_settings` | 记忆开关 |
| `feedback` | 用户反馈、DataAgent V2 学习字段 |
| `task_definitions` | 任务定义 |
| `task_runs` | 任务运行 |
| `task_notifications` | 任务通知 |
| `audit_logs` | 审计 |
| `reasoning_traces` | 推理阶段追踪 |
| `tool_stats` | 工具统计 |
| `system_settings` | 系统键值配置 |
| `redis_shadow_kv` | Redis 影子表 |

---

## 23. 配置项

### 23.1 服务基础

```env
APP_ENV=development
APP_HOST=0.0.0.0
APP_PORT=14100
GATEWAY_PORT=14100
FRONTEND_PORT=14108
VITE_API_URL=http://localhost:14100
VITE_WS_URL=ws://localhost:14100
```

### 23.2 数据库与 Redis

```env
DATABASE_URL=postgresql+asyncpg://postgres:password@localhost:5432/opentrace_v2
TOKEN_DB_URL=postgresql+asyncpg://postgres:password@localhost:5432/opentrace_v2
REDIS_URL=redis://localhost:6379/10
```

### 23.3 Kernel 与 Agent

```env
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_ENABLED=true
KERNEL_AGENT_DATA_ENABLED=true
KERNEL_AGENT_TOOL_ENABLED=true
KERNEL_AGENT_WEB_ENABLED=true
KERNEL_AGENT_RAG_ENABLED=true
KERNEL_AGENT_TIMEOUT_SEC=30
KERNEL_AGENT_MAX_PARALLEL=5
KERNEL_AGENT_RUNTIME_SUPERVISOR_ENABLED=true
```

### 23.4 V5 路由

```env
KERNEL_V5_ROUTING_ENABLED=true
KERNEL_L0_RULE_ROUTER_ENABLED=true
KERNEL_L1_TINY_ROUTER_ENABLED=true
KERNEL_SEMANTIC_CACHE_ENABLED=true
KERNEL_SEMANTIC_CACHE_THRESHOLD=0.92
```

### 23.5 多轮增强

```env
KERNEL_CONVERSATION_STATE_ENABLED=true
KERNEL_CLARIFICATION_GATE_ENABLED=true
KERNEL_CORRECTION_DETECTION_ENABLED=true
KERNEL_REFINE_REPLAN_ENABLED=true
KERNEL_DST_ENABLED=true
KERNEL_CONTEXT_COMPOSER_ENABLED=true
KERNEL_MEMORY_VALUE_SCORING_ENABLED=true
```

### 23.6 DataAgent V2

```env
DATA_AGENT_V2_ENABLED=true
DATA_AGENT_V2_FALLBACK_TO_V1=false
DATA_AGENT_V2_SUPERVISOR_MAX_RETRIES=2
DATA_AGENT_V2_CONFIDENCE_THRESHOLD=0.40
DATA_AGENT_V2_COGNITIVE_EVENTS_ENABLED=false
DATA_AGENT_V2_LEARNING_ENABLED=false
DATA_AGENT_V2_STATISTICAL_ENABLED=false
DATA_AGENT_V2_INSIGHT_ENABLED=false
DATA_AGENT_V2_VISUALIZATION_ENABLED=false
```

### 23.7 附件与 PII

```env
ATTACHMENT_UPLOAD_ENABLED=true
ATTACHMENT_MAX_SIZE_MB=20
ATTACHMENT_STORAGE_PATH=/tmp/opentrace_attachments
ATTACHMENT_MAX_CHARS=4000
MULTIMODAL_ATTACHMENT_ENABLED=true
KERNEL_NER_MASKING_ENABLED=true
```

### 23.8 LLM

```env
DEFAULT_LLM_QUERY_MODEL=qwen3.6-plus
DEFAULT_LLM_PLANING_MODEL=qwen3.6-plus
DEFAULT_LLM_COMPRESS_MODEL=qwen3.5-27b
DEFAULT_LLM_VISION_MODEL=qwen3.6-vl-plus
```

---

## 24. 部署与运行

### 24.1 Docker 启动

```bash
cp .env.example .env
bash start.sh
```

`start.sh` 会：

1. 检查 `14100` 端口是否被占用。
2. 调用 `scripts/docker_up.sh`。
3. 检查 `/api/v1/health`。
4. 检查 `/api/v1/health/deps`。
5. 检查核心表 `public.users` 是否存在。
6. `--verify` 时运行 Docker 验证脚本。

### 24.2 观测启动

```bash
bash start.sh --with-observability
```

会启用 Prometheus 和 Jaeger profile。

### 24.3 停止与重启

```bash
bash stop.sh
bash restart.sh
```

### 24.4 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m gateway.api_gateway.main

cd frontend
npm install
npm run dev
```

### 24.5 常用检查

```bash
curl http://localhost:14100/api/v1/health
curl http://localhost:14100/api/v1/health/deps
docker compose ps
docker logs opentrace_api
docker logs opentrace_agent_worker
```

---

## 25. 测试体系

### 25.1 后端

```bash
python -m pytest tests -q
```

当前后端全量测试状态：

```text
449 passed, 1 warning
```

警告来自 pytest 对 `asyncio_mode` 的配置识别，未影响测试结果。

关键测试类别：

| 类别 | 示例 |
|------|------|
| Orchestrator | `test_orchestrator_v4_contract.py` |
| Agent Bus | `test_agent_bus_e2e_contract.py` |
| DataAgent V2 | `test_data_agent_v2_*` |
| Text2SQL | `test_text2sql_regression.py` |
| Data API | `test_data_query_api_contract.py` |
| Database API | `test_databases_api_contract.py` |
| Force Mode | `test_force_mode_routing.py` |
| RAG | `test_rag_agent_contract.py` |
| Governance | `test_agent_bus_governance_contract.py` |

### 25.2 前端

```bash
cd frontend
npm run build
npm test -- --run
```

当前状态：

- `npm run build` 通过。
- `npm test -- --run` 存在若干 UI contract 失败，主要是文案和组件事件断言，与 DataAgent V2 后端链路无直接关系。

### 25.3 脚本验证

常见脚本：

```bash
bash scripts/verify_agent_cluster.sh
bash scripts/verify_agent_bus_e2e.sh
bash scripts/verify_migration_idempotent.sh
bash scripts/verify_error_envelope.sh
bash scripts/verify_e2e.sh
```

---

## 26. 开发规范与维护建议

### 26.1 后端

- 新增 API 路由时同步注册到 `gateway/api_gateway/main.py`。
- 新增 DB 字段应提供 Alembic migration，并确保幂等。
- 新增 Agent 应继承 `BaseAgent`，返回 `AgentResult` 或在调用边界归一化。
- SQL 生成必须经过 `SQLValidator`，只允许 read-only 查询。
- DataAgent V2 子 Agent 间传递状态统一使用 `CognitiveContext`。
- 涉及聊天返回结构时必须考虑 `result_refs`、`metadata`、`execution_graph`。

### 26.2 前端

- API 统一从 `frontend/src/api/client.ts` 调用。
- 新页面加入 `App.tsx` 路由和 `Sidebar.tsx` 导航。
- 使用 lucide-react 图标。
- 数据查询类 UI 优先复用 `DataQueryResult`、`DataTableChart`、`MetricDefinitionEditor`、`TableRelationGraph`。

### 26.3 测试

- 后端改动至少跑相关测试和 `python -m pytest tests -q`。
- 前端改动至少跑 `npm run build`。
- DataAgent V2 改动建议跑：

```bash
python -m pytest \
  tests/test_data_agent_v2_supervisor_contract.py \
  tests/test_data_agent_v2_agent_contract.py \
  tests/test_data_agent_v2_deterministic_agents_unit.py \
  tests/test_statistical_agent_unit.py \
  tests/test_text2sql_regression.py \
  tests/test_data_query_api_contract.py -q
```

---

## 27. 排障入口

### 27.1 API 不通

```bash
curl http://localhost:14100/api/v1/health
curl http://localhost:14100/api/v1/health/deps
lsof -i :14100
docker logs opentrace_api
```

### 27.2 数据库不可用

```bash
docker compose exec postgres pg_isready -U postgres
docker compose exec postgres psql -U postgres -d opentrace_v2 -c "\dt"
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

### 27.3 Redis / Agent Bus

```bash
docker compose exec redis redis-cli ping
docker logs opentrace_agent_worker
curl http://localhost:14100/api/v1/health/deps
```

### 27.4 LLM 调用失败

检查：

- `DEFAULT_LLM_QUERY_API_KEY`
- `DEFAULT_LLM_PLANING_API_KEY`
- provider base URL。
- proxy / no_proxy。
- API logs 中的 `LLM call`。

### 27.5 DataAgent V2 查询失败

优先检查：

1. `DATA_AGENT_V2_ENABLED=true`
2. 数据源是否连接成功。
3. schema 是否同步。
4. `data_source_schemas.schema_json` 是否有 tables/columns。
5. `metric_definitions`、`schema_metadata`、`table_relationships` 是否存在有效资产。
6. `cognitive_events` 是否开启并记录。
7. 返回 metadata 中的 `verification_report`、`agent_trace`、`sql`、`execution_error`。

### 27.6 前端连接 API 失败

检查：

- `VITE_API_URL`
- 浏览器控制台。
- CORS。
- `/api/v1/health` 是否可访问。

---

## 28. 已知风险与后续优化

### 28.1 当前已知风险

- 前端 Vitest 有 UI contract 失败，需要单独修复文案/事件/渲染断言。
- DataAgent V2 高级分析默认关闭：Statistical/Insight/Visualization/SkillExecution 需要按场景逐步启用。
- DataAgent V2 learning 默认关闭，反馈闭环需要产品化确认后开启。
- Knowledge Assets 的质量直接决定 V2 业务准确率，需要配套同步和治理流程。
- `infra/storage/models.py` 中模型数量较多，迁移与运行时 schema 需要持续保持一致。
- LLM provider/API key 缺失会影响规划、意图识别、SQL 修复、洞察生成等模块。

### 28.2 建议后续工作

1. 为 `/data/query` V2 路径增加 mock DB 的端到端集成测试。
2. 为 DataAgent V2 增加真实样例数据集回归：问题、期望 SQL、期望行数、期望解释。
3. 打开 `DATA_AGENT_V2_COGNITIVE_EVENTS_ENABLED` 后建设审计 UI。
4. 渐进开启 Statistical/Insight/Visualization，并在前端统一展示。
5. 补齐 Knowledge Assets 的导入、同步、审核、版本控制。
6. 修复前端 Vitest contract，恢复前端测试全绿。
7. 为 Redis shadow、Agent Bus stream mode、任务系统补更多运行态健康指标。

---

## 附录：最短启动与验证命令

```bash
# 后端测试
python -m pytest tests -q

# 前端构建
cd frontend && npm run build

# Docker 启动
cp .env.example .env
bash start.sh

# 健康检查
curl http://localhost:14100/api/v1/health
curl http://localhost:14100/api/v1/health/deps
```
