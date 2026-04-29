# OpenTrace 完整项目文档

> 本文档是 OpenTrace 项目的唯一权威技术参考，涵盖架构设计、API 接口、配置说明、数据流程、部署方案和开发指南。
>
> 最后更新：2026-04-29

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [系统架构](#3-系统架构)
4. [目录结构](#4-目录结构)
5. [前端应用](#5-前端应用)
6. [API 网关](#6-api-网关)
7. [认知内核（Cognitive Kernel）](#7-认知内核cognitive-kernel)
8. [V5 分层路由（L0/L1/L2 Routing Tier）](#8-v5-分层路由l0l1l2-routing-tier)
9. [V4 编排器（Orchestrator V4）](#9-v4-编排器orchestrator-v4)
10. [智能体集群（Agent Cluster）](#10-智能体集群agent-cluster)
11. [模型网关（Model Gateway）](#11-模型网关model-gateway)
12. [记忆系统（Memory System）](#12-记忆系统memory-system)
13. [执行平面（Execution Plane）](#13-执行平面execution-plane)
14. [数据认知层（Data Cognition）](#14-数据认知层data-cognition)
15. [基础设施层（Infrastructure）](#15-基础设施层infrastructure)
16. [安全与防护（Safety）](#16-安全与防护safety)
17. [技能系统（Skills）](#17-技能系统skills)
18. [规则引擎（Rule Engine）](#18-规则引擎rule-engine)
19. [消息总线（Message Bus）](#19-消息总线message-bus)
20. [快捷标签与强制模式路由](#20-快捷标签与强制模式路由)
21. [数据库模型与迁移](#21-数据库模型与迁移)
22. [配置说明](#22-配置说明)
23. [Docker 部署](#23-docker-部署)
24. [常用命令](#24-常用命令)
25. [测试体系](#25-测试体系)
26. [调试与排障](#26-调试与排障)
27. [开发规范](#27-开发规范)
28. [多子问题支持（Multi-Question）](#28-多子问题支持multi-question)

---

## 1. 项目概述

OpenTrace 是一个**认知内核驱动的 Agent 系统**，支持以下核心能力：

- **对话式问答**：同步和 SSE 流式两种模式
- **工具调用**：时间、天气、计算器、代码执行
- **RAG 文档问答**：基于 pgvector 的知识库检索
- **Text2SQL 数据查询**：自然语言转 SQL 并自动执行
- **联网搜索**：基于 Serper API 的实时 Web 检索
- **推理链可视化**：完整的推理步骤和 DAG 执行图展示
- **多层记忆**：工作记忆、语义记忆、情节记忆、程序记忆
- **V5 分层路由**：L0（零 LLM）+ L1（1.7B 单次分类）+ L2（全管线），30%+ 请求免 LLM
- **规则引擎**：YAML 驱动的产品查询与业务规则
- **多子问题编排**：语法 + LLM 双路径拆分，顺序融合

### 1.1 版本演进

| 阶段 | 版本 | 核心能力 |
|------|------|---------|
| V3 | legacy | 单线问答管线 |
| V4 | stable | Plan → Dispatcher → Agent Cluster → Fusion → Critic |
| V5 | current | V4 + L0 规则路由 + L1 小模型分类 + 语义缓存 |

---

## 2. 技术栈

### 2.1 后端

| 组件 | 技术 | 版本 |
|------|------|------|
| 语言 | Python | 3.11+ |
| Web 框架 | FastAPI | >=0.111.0 |
| 服务器 | Uvicorn | >=0.29.0 |
| 数据库 ORM | SQLAlchemy (async) | >=2.0.30 |
| 数据库迁移 | Alembic | >=1.13.1 |
| 向量扩展 | pgvector | >=0.2.5 |
| Redis 客户端 | redis[hiredis] | >=5.0.4 |
| LLM SDK | openai | >=1.30.0 |
| 数据验证 | Pydantic | >=2.7.0 |
| 配置管理 | pydantic-settings | >=2.2.1 |
| 序列化 | orjson | >=3.10.3 |
| SQL 解析 | sqlglot | >=25.0.0 |
| 链路追踪 | OpenTelemetry | >=1.24.0 |
| 指标 | prometheus-client | >=0.20.0 |
| 包管理 | pip (editable install) | — |

### 2.2 前端

| 组件 | 技术 |
|------|------|
| 框架 | React + TypeScript |
| 构建工具 | Vite |
| 状态管理 | Zustand |
| 测试 | Vitest |

### 2.3 基础设施

| 组件 | 技术 |
|------|------|
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存/队列 | Redis 7 |
| 容器编排 | Docker Compose |
| 指标 | Prometheus |
| 追踪 | Jaeger |

---

## 3. 系统架构

```
┌──────────────────────────────────────────────────────────────────┐
│                        Frontend (React/Vite)                      │
│                      http://localhost:14108                      │
└──────────────────────────────┬───────────────────────────────────┘
                               │ HTTP / SSE
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│                    API Gateway (FastAPI)                          │
│                    http://localhost:14100                        │
│  ├── /api/v1/chat       — 聊天（同步/流式）                      │
│  ├── /api/v1/auth       — 认证（注册/登录/Token）                │
│  ├── /api/v1/documents  — 文档管理                               │
│  ├── /api/v1/databases  — 数据源管理                             │
│  ├── /api/v1/data       — 数据查询                               │
│  ├── /api/v1/conversations — 会话管理                            │
│  ├── /api/v1/memories   — 记忆 CRUD                              │
│  ├── /api/v1/skills     — 技能管理                               │
│  ├── /api/v1/rules      — 规则管理（CRUD + YAML 生成）           │
│  ├── /api/v1/tasks      — 任务管理                               │
│  ├── /api/v1/health     — 健康检查                               │
│  ├── /api/v1/cognitive  — 认知事件回放                           │
│  ├── /api/v1/feedback   — 用户反馈                               │
│  ├── /api/v1/audit      — 审计日志                               │
│  ├── /api/v1/sandbox    — 沙箱                                   │
│  ├── /api/v1/admin      — 管理接口                               │
│  ├── /api/v1/connectors — 连接器                                 │
│  └── /api/v1/ui-settings — UI 设置                               │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                               ▼
┌──────────────────────────────────────────────────────────────────┐
│              Cognitive Kernel (kernel/)                           │
│  ├── V5 Routing Tier (L0 → L0.5 → L1 → L2)                      │
│  ├── Intent Engine — 意图域分类                                  │
│  ├── Self Model — 自我能力评估                                    │
│  └── Orchestrator V4 — 主编排器                                   │
│      ├── Plan Agent — 任务分解 (DAG)                              │
│      ├── Dispatcher — 并发调度                                    │
│      ├── DAG Scheduler — 依赖调度                                 │
│      ├── Fusion Engine — 证据融合                                 │
│      └── Critic Engine — 质量审校                                 │
└──────────────────────────────┬───────────────────────────────────┘
                               │
                ┌──────────────┼──────────────┐
                ▼              ▼              ▼
        ┌──────────┐  ┌──────────┐  ┌──────────┐
        │ Agent    │  │ Model    │  │ Execution│
        │ Cluster  │  │ Gateway  │  │ Plane    │
        └──────────┘  └──────────┘  └──────────┘
                │              │              │
        ┌───────┼───────┬──────┼──────┬───────┼───────┐
        ▼       ▼       ▼      ▼      ▼      ▼       ▼
     ┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐┌─────┐
     │Data ││RAG  ││Web  ││Tool ││Skills││Rule ││Mem  │
     │Agent││Agent││Agent││Agent││Agent││Eng  ││ory  │
     └─────┘└─────┘└─────┘└─────┘└─────┘└─────┘└─────┘
```

---

## 4. 目录结构

```
opentrace/
├── frontend/                    # React 前端应用
│   └── src/
│       ├── api/client.ts        # API 客户端（所有后端调用）
│       ├── components/          # UI 组件
│       │   ├── ChatInput.tsx    # 聊天输入（含快捷标签/斜杠命令）
│       │   ├── ChatMessage.tsx  # 消息渲染（含多子问题卡片）
│       │   ├── MultiQuestionCards.tsx  # 多子问题卡片渲染
│       │   ├── Sidebar.tsx      # 侧边栏导航
│       │   └── ...
│       ├── pages/
│       │   ├── ChatPage.tsx     # 主聊天页面
│       │   ├── DatabasesPage.tsx # 数据源管理页面
│       │   └── RulesPage.tsx    # 规则管理页面
│       ├── store/               # Zustand 状态管理
│       └── utils/
│           └── parseMultiQuestion.ts  # 多子问题 Markdown 解析器
├── gateway/                     # FastAPI 网关
│   └── api_gateway/
│       ├── main.py              # FastAPI 应用入口
│       └── routers/             # API 路由模块（19 个）
│           ├── chat.py          # 聊天（同步/流式/重生成/图控制）
│           ├── auth.py          # 认证
│           ├── conversations.py # 会话管理
│           ├── documents.py     # 文档管理
│           ├── databases.py     # 数据源管理
│           ├── data.py          # 数据查询
│           ├── memories.py      # 记忆 CRUD
│           ├── skills.py        # 技能管理
│           ├── rules.py         # 规则管理（CRUD + YAML 生成）
│           ├── tasks.py         # 任务管理
│           ├── health.py        # 健康检查
│           ├── cognitive.py     # 认知事件回放
│           ├── feedback.py      # 用户反馈
│           ├── audit.py         # 审计日志
│           ├── connectors.py    # 连接器
│           ├── sandbox.py       # 沙箱
│           ├── admin.py         # 管理接口
│           └── ui_settings.py   # 用户 UI 设置
├── kernel/                      # 认知内核（85 个文件）
│   ├── cognitive_kernel.py      # 唯一中枢入口（run/stream）
│   ├── orchestrator_v4.py       # V4 编排器（核心调度逻辑）
│   ├── plan_agent.py            # 任务规划 Agent（单/多问题）
│   ├── dispatcher.py            # 并发任务分发
│   ├── dag_scheduler.py         # DAG 依赖调度
│   ├── query_router_v2.py       # L0 规则路由器（零 LLM 模式匹配）
│   ├── tiny_router.py           # L1 Tiny Router（1.7B 单次分类）
│   ├── complexity_engine.py     # 规则复杂度评分引擎（0-100 分）
│   ├── semantic_cache.py        # Redis 语义缓存（SHA-256 精确匹配）
│   ├── context_pipeline.py      # 上下文处理管道
│   ├── adaptive_profiles.py     # 自适应配置（速度/质量/均衡）
│   ├── fusion_engine/           # 证据融合引擎
│   │   ├── engine.py            # FusionEngine（单问题加权融合）
│   │   ├── models.py            # 融合数据模型
│   │   ├── sequence_fusion.py   # SequenceFusionEngine（多子问题顺序融合）
│   │   └── sequence_models.py   # 顺序融合数据模型
│   ├── critic_engine/           # 质量审校引擎
│   ├── intent_engine/           # 意图识别
│   ├── meta_cognition/          # 元认知（质量门控）
│   ├── epistemology/            # 认识论（内容标注/验证）
│   ├── cognition/               # 认知模块
│   │   ├── sub_question.py      # 子问题数据模型
│   │   └── __init__.py          # 认知模块导出
│   ├── data_cognition/          # 数据认知（Text2SQL 管线）
│   │   ├── schema_linker.py     # Schema 链接
│   │   ├── sql_builder.py       # SQL 生成
│   │   ├── sql_validator.py     # SQL 验证
│   │   ├── sql_rewriter.py      # SQL 重写
│   │   ├── sql_ranker.py        # SQL 排序
│   │   ├── semantic_layer.py    # 语义层
│   │   ├── semantic_parser.py   # 语义解析
│   │   ├── query_executor.py    # 查询执行
│   │   ├── query_planner.py     # 查询规划
│   │   └── table_graph.py       # 表关系图
│   ├── context/                 # 查询重写
│   ├── identity/                # 系统身份
│   └── prompts/                 # Prompt 模板
├── agents/                      # 智能体集群（10 个文件）
│   ├── base.py                  # BaseAgent 抽象基类
│   ├── data_agent.py            # 数据查询 Agent（Text2SQL）
│   ├── rag_agent.py             # RAG 检索 Agent
│   ├── web_agent.py             # 联网搜索 Agent
│   ├── tool_agent.py            # 通用工具 Agent
│   ├── skills_agent.py          # 技能调用 Agent
│   ├── rule_engine_agent.py     # 规则引擎 Agent
│   ├── worker.py                # Agent Worker（消费 Redis 消息）
│   └── registry.py              # Agent 注册与发现
├── model/                       # 模型网关
│   ├── model_gateway/
│   │   └── gateway.py           # 模型路由 + 熔断 + 重试（7 个角色）
│   ├── llm_adapter/
│   │   ├── base.py              # 适配器接口
│   │   └── openai_adapter.py    # OpenAI 兼容适配器
│   ├── embedding/
│   │   └── base.py              # 嵌入模型接口
│   └── reranker/
│       └── base.py              # 重排接口
├── memory/                      # 记忆系统（14 个文件）
│   ├── working_memory/          # 工作记忆（环形缓冲区）
│   ├── semantic_memory/         # 语义记忆（向量检索）
│   ├── episodic_memory/         # 情节记忆（会话事件）
│   ├── procedural_memory/       # 程序记忆
│   ├── memory_router/           # 记忆路由
│   └── evolution/               # 记忆演化
├── execution/                   # 执行平面（23 个文件）
│   ├── dag_engine/              # DAG 执行引擎
│   ├── data/                    # 数据执行层
│   │   ├── db_router.py         # 多数据库路由
│   │   ├── sql_executor.py      # SQL 执行器
│   │   └── query_intents.py     # 查询意图识别
│   └── tool_router/             # 工具路由
├── infra/                       # 基础设施（34 个文件）
│   ├── config/settings.py       # 统一配置（Settings 单例）
│   ├── storage/
│   │   ├── database.py          # DB 连接管理
│   │   └── models.py            # SQLAlchemy ORM 模型
│   ├── cache/
│   │   └── redis_client.py      # Redis 多 DB 连接
│   ├── message_bus/
│   │   ├── events.py            # 认知事件模型
│   │   ├── cognitive_event_bus.py # 认知事件总线
│   │   ├── agent_bus.py         # Agent 消息总线
│   │   └── bus.py               # 通用消息总线
│   ├── observability/
│   │   ├── logger.py            # 结构化日志
│   │   ├── metrics.py           # Prometheus 指标
│   │   └── tracer.py            # OpenTelemetry 追踪
│   ├── security/
│   │   └── zero_trust.py        # 零信任风险评估
│   ├── guards/
│   │   └── kernel_guard.py      # 入口点守卫
│   ├── errors/
│   │   └── exceptions.py        # AppException + ErrorCodes
│   ├── audit/
│   │   └── logger.py            # 审计日志写入
│   └── metadata/
│       └── schema_inspector.py  # 数据库 Schema 检查
├── safety/                      # 安全防护
│   └── guardrails/              # 输入防护栏
├── rules/                       # YAML 规则存储
├── skills/                      # 技能系统
│   └── marketplace/
│       ├── store.py             # 技能存储
│       └── manifest.py          # 技能清单
├── alembic/                     # 数据库迁移
│   ├── env.py                   # Alembic 环境
│   └── versions/                # 迁移脚本
├── deploy/docker/               # Docker 配置
├── scripts/                     # 运维脚本
├── tests/                       # 测试（85 个测试文件，401 个测试方法）
├── docker-compose.yml           # Docker 编排
├── pyproject.toml               # Python 项目配置
├── alembic.ini                  # Alembic 配置
├── .env.example                 # 环境变量模板
├── CLAUDE.md                    # Claude Code 项目指引
├── RUNBOOK.md                   # 运维手册
├── next_work.md                 # 优化路线图
├── start.sh / stop.sh / restart.sh  # 启停脚本
└── SERVICE.md                   # 本文档
```

---

## 5. 前端应用

### 5.1 技术选型

| 组件 | 技术 |
|------|------|
| 框架 | React + TypeScript |
| 构建工具 | Vite |
| 状态管理 | Zustand |
| 测试 | Vitest |

### 5.2 API 客户端

**文件**：`frontend/src/api/client.ts`

所有后端调用通过 `apiFetch()` 统一处理，基础路径 `/api/v1`，支持 Vite 环境变量 `VITE_API_URL` 配置后端地址。

主要 API 函数（19 个）：

| 函数 | 说明 |
|------|------|
| `apiLogin(email, password)` | 登录获取 Token |
| `apiChatSync(token, sessionId, query, options)` | 同步聊天 |
| `apiChatStream(token, sessionId, query, callbacks, ...)` | SSE 流式聊天 |
| `apiCreateConversation(token)` | 创建会话 |
| `apiListConversations(token, filters?)` | 列出会话 |
| `apiGetMessages(token, conversationId)` | 获取历史消息 |
| `apiRenameConversation(token, id, title)` | 重命名会话 |
| `apiDeleteConversation(token, id)` | 删除会话 |
| `apiArchiveConversation(token, id, archived)` | 归档会话 |
| `apiBranchConversation(token, id, messageId)` | 分支会话 |
| `apiPatchMessage(token, id, payload)` | 编辑消息 |
| `apiListDocuments(token)` | 列出文档 |
| `apiUploadDocument(token, file, options?)` | 上传文档 |
| `apiDeleteDocument(token, id)` | 删除文档 |
| `apiListDatabases(token)` | 列出数据源 |
| `apiDatabaseQuery(token, dataSourceId, params)` | 执行数据查询 |
| `apiGetDatabaseSchema(token, dataSourceId)` | 获取数据库 Schema |
| `apiGraphControl(...)` | 图控制 |
| `apiGetSessionSkills(...)` | 获取会话技能 |

### 5.3 推理链前端类型

```typescript
type ReasoningStage = 'REASON' | 'DECIDE' | 'EXECUTE' | 'OBSERVE' | 'REFLECT' | 'PLAN' | 'ACT' | 'DRAFT' | 'CRITIC' | 'REWRITE' | 'FINAL'
type ReasoningStatus = 'pending' | 'running' | 'done'

interface ReasoningStep {
  id: string
  stage: ReasoningStage
  content: string
  status: ReasoningStatus
  node_id?: string
  tool?: { name: string; status: ToolRunStatus; preview?: string }
}
```

### 5.4 前端开发

- Dev server 运行在 `http://localhost:14108`，API 请求代理到 `http://localhost:14100`
- 安装依赖：`cd frontend && npm install`
- 启动开发：`npm run dev`
- 构建：`npm run build`
- 测试：`npm run test`

### 5.5 快捷标签与斜杠命令

输入 `/` 立即弹出候选下拉框，包含 6 个主要命令：

| 命令 | 标签 | force_mode | 说明 |
|------|------|------------|------|
| `/rag` | 知识库检索 | `rag` | 检索知识库中的文档 |
| `/data_query` | 数据查询 | `data_query` | 执行数据库 SQL 查询 |
| `/data_analysis` | 数据分析 | `data_analysis` | 数据库分析查询 |
| `/anomaly_tracking` | 异常追踪 | `anomaly_tracking` | 异常追踪与监控 |
| `/product` | 产品查询 | `product` | 触发 YAML 规则引擎 |
| `/rule_engine` | 规则引擎 | `rule_engine` | 规则引擎查询 |
| `/skills` | 技能调用 | `skills` | 调用已安装的技能 |
| `/web` | 联网搜索 | `web` | 联网搜索 |
| `/tool` | 工具调用 | `tool` | 通用工具调用 |

**别名映射**（后端 L0 处理）：
- `/data` → `data_query`
- `/doc`, `/document` → `rag`
- `/search` → `web`
- `/rule` → `rule_engine`

**交互规则**：
- 输入 `/` 立即弹出全部选项
- `↑/↓` 方向键导航，`Enter/Tab` 确认，`Escape` 关闭
- 选择后自动插入前缀 + 空格

---

## 6. API 网关

**基础路径**：`/api/v1`
**端口**：`14100`
**框架**：FastAPI
**中间件**：CORS、Request ID、异常处理、内存事件订阅生命周期

### 6.1 路由注册

19 个路由模块注册在 `gateway/api_gateway/main.py`：

```python
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(conversations.router, prefix="/api/v1", tags=["conversations"])
app.include_router(cognitive.router, prefix="/api/v1", tags=["cognitive"])
app.include_router(documents.router, prefix="/api/v1", tags=["documents"])
app.include_router(memories.router, prefix="/api/v1", tags=["memories"])
app.include_router(tasks.router, prefix="/api/v1", tags=["tasks"])
app.include_router(audit.router, prefix="/api/v1", tags=["audit"])
app.include_router(connectors.router, prefix="/api/v1", tags=["connectors"])
app.include_router(skills.router, prefix="/api/v1", tags=["skills"])
app.include_router(ui_settings.router, prefix="/api/v1", tags=["ui_settings"])
app.include_router(data.router, prefix="/api/v1", tags=["data"])
app.include_router(databases.router, prefix="/api/v1", tags=["databases"])
app.include_router(feedback.router, prefix="/api/v1", tags=["feedback"])
app.include_router(sandbox.router, prefix="/api/v1", tags=["sandbox"])
app.include_router(admin.router, prefix="/api/v1", tags=["admin"])
app.include_router(rules.router, prefix="/api/v1", tags=["rules"])
```

### 6.2 关键端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login` | 用户登录 |
| POST | `/chat` | 同步聊天 |
| POST | `/chat/stream` | SSE 流式聊天 |
| GET | `/chat/history/{session_id}` | 聊天历史 |
| POST | `/conversations` | 创建会话 |
| GET | `/conversations` | 列出会话 |
| DELETE | `/conversations/{id}` | 删除会话 |
| POST | `/conversations/{id}/archive` | 归档会话 |
| POST | `/conversations/{id}/branch` | 分支会话 |
| POST | `/documents` | 上传文档 |
| GET | `/documents` | 列出文档 |
| DELETE | `/documents/{id}` | 删除文档 |
| POST | `/data/query` | 数据查询 |
| GET | `/databases` | 列出数据源 |
| GET | `/health` | 基础健康检查 |
| GET | `/health/deps` | 依赖健康检查 |
| GET | `/health/runtime` | 运行时信息 |
| GET/POST | `/skills` | 技能 CRUD |
| GET/POST | `/rules` | 规则 CRUD |
| GET | `/rules/yaml` | 规则 YAML 生成 |
| GET/POST | `/memories` | 记忆 CRUD |
| POST | `/feedback` | 提交反馈 |
| GET | `/audit` | 审计日志 |
| GET/PATCH | `/ui-settings` | UI 设置 |

### 6.3 异常处理

- `AppException` → 统一 JSON 错误信封：`{code, message, details, request_id, timestamp}`
- `Exception` → 内部错误返回（`INTERNAL_ERROR` 错误码）
- 每个响应携带 `x-request-id` 和 `x-response-time-ms` 头

---

## 7. 认知内核（Cognitive Kernel）

**文件**：`kernel/cognitive_kernel.py`

认知内核是系统的**唯一中枢入口**，所有能力均通过内核调度，禁止绕过内核直接调用 LLM。

### 7.1 核心原则

1. 所有输出必须由认知内核生成
2. 所有插件返回的数据只是「候选认知材料」
3. LLM 不是回答器，而是「认知执行器」
4. Prompt 不是模板，而是「认知协议」

### 7.2 执行流程（V5）

```
Step 0: is_multi_question  — 多子问题检测（一次性计算）
Step 1: Working Memory     — 身份问答缓存检查（多子问题时跳过）
Step 2: V5 Routing Tier    —
  ├── L0: Rule Router      — 零 LLM 匹配（<1ms）：FAQ/身份/斜杠命令/工具触发/精确去重
  ├── L0.5: Semantic Cache — Redis SHA-256 精确缓存
  └── L1: Complexity + Tiny Router — 复杂度评分 + 1.7B 分类
      ├── identity/faq → 直接回答
      ├── knowledge → SeniorShort 14B 直答
      └── complex → 落入 L2
Step 3: intent_domain      — 意图域分类（仅 L2）
Step 4: SelfModel          — 自我能力评估（仅 L2）
Step 5: OrchestratorV4     — 全 V4 管线（L2）
Step 6: Semantic Cache Save — L2 成功后写入缓存
Step 7: Memory Save        — 异步保存对话记忆
```

### 7.3 入口方法

| 方法 | 签名 | 返回 |
|------|------|------|
| `run(request: KernelRequest)` | 同步执行 | `KernelResponse` |
| `stream(request: KernelRequest)` | SSE 流式 | `AsyncIterator[dict]` |

### 7.4 意图域分类

```python
def _classify_intent_domain(query) -> TaskDomain:
    # DATA_QUERY:      查询/统计/报表/销量/订单/sql/数据库
    # DOCUMENT_RETRIEVAL: 文档/手册/pdf/doc/附件/总结文档
    # WEB_SEARCH:      最新/新闻/今天/实时/联网/搜索/weather
    # TOOL_EXECUTION:  执行/工具/调用/计算/时间/天气
    # GENERAL_QA:      其他
```

### 7.5 身份问答保护

- 检测身份问题（"你是谁"）→ 优先 `working_memory` 缓存
- 命中 → 直接返回，不调用 LLM
- 未命中 → 走 V4 编排器，返回后写入缓存
- 系统身份响应：`CANONICAL_IDENTITY_RESPONSE`
- 多子问题查询永不触发身份快捷路径

### 7.6 V5 模块懒加载

```python
def _get_l0_router() -> L0RuleRouter      # L0 规则路由
def _get_semantic_cache() -> SemanticCache # 语义缓存
def _get_complexity_engine() -> ComplexityEngine  # 复杂度引擎
def _get_tiny_router() -> TinyRouter      # L1 分类路由
```

---

## 8. V5 分层路由（L0/L1/L2 Routing Tier）

### 8.1 设计动机

V4 架构对所有非平凡请求都走完整的 Plan → Dispatch → Agent Cluster → Fusion → Critic 管线，每次都至少调用 PLANNING LLM 和 QUERY LLM。但 30-50% 的用户请求是身份查询、FAQ、简单工具调用或近似重复问题，不需要完整 LLM 管线。

V5 在请求到达 V4 管线之前拦截，目标：**30%+ 请求延迟 <50ms，Token 成本降低 40%**。

### 8.2 架构图

```
User Query
    │
    ▼
┌─────────────────────────────────────────┐
│ L0: Rule Router (零 LLM, <1ms)           │
│  FAQ 固定回答 (13 条) / 身份问题 /       │
│  斜杠命令 (12→9) / 工具触发 / Redis 去重 │
│  HIT → 立即返回                          │
└──────┬──────────────────────────────────┘
       │ MISS
       ▼
┌─────────────────────────────────────────┐
│ L0.5: Semantic Cache (Redis SHA-256)     │
│  HIT → 返回缓存                          │
└──────┬──────────────────────────────────┘
       │ MISS
       ▼
┌─────────────────────────────────────────┐
│ L1: ComplexityEngine + TinyRouter        │
│  ComplexityEngine: 规则评分 0-100        │
│  TinyRouter: JuniorShort 1.7B 分类       │
│  → identity/faq: MiddleShort 8B 直接回答 │
│  → knowledge: SeniorShort 14B 知识回答   │
│  → complex: 落入 L2                      │
└──────┬──────────────────────────────────┘
       │ complex
       ▼
┌─────────────────────────────────────────┐
│ L2: Full V4 Pipeline                     │
│  Plan → Dispatch → Agents → Fusion →     │
│  Critic                                  │
└─────────────────────────────────────────┘
```

### 8.3 L0 规则路由器

**文件**：`kernel/query_router_v2.py`
**类**：`L0RuleRouter`
**特征**：零 LLM，纯字符串匹配和正则

**数据模型**：

```python
@dataclass
class L0Result:
    hit: bool           # True = 已处理，直接返回
    route: str          # identity|faq|tool|force_mode|duplicate
    answer: str | None  # 预设回答
    force_mode: str | None  # 强制模式
    metadata: dict
```

**FAQ 固定回答（13 条）**：你好/您好、hi/hello、谢谢/感谢、再见/bye、好的/ok、嗯、帮助/help、你能做什么/有什么功能

**工具触发模式**：

| 触发类别 | 正则 | 路由 |
|---------|------|------|
| `_TOOL_TIME` | `几点\|什么时间\|现在时间\|当前时间\|日期\|今天几号\|今天日期\|星期几` | force_mode=tool |
| `_TOOL_WEATHER` | `天气\|气温\|下雨\|刮风\|雾霾\|aqi\|pm2.5` | force_mode=tool |
| `_TOOL_CALC` | `^[\d\s+\-*/().^%]+$` | force_mode=tool |

**斜杠命令**：正则 `^/(\w[\w_]*)\s*`，支持 12 输入别名 → 9 个有效 force_mode

**精确去重**：Redis 缓存 Key（SHA-256 前 16 位），`v5:cache:exact:{hash}`

### 8.4 语义缓存

**文件**：`kernel/semantic_cache.py`
**类**：`SemanticCache`

```python
@dataclass
class CacheEntry:
    query: str
    answer: str
    embedding: list[float] | None
    timestamp: float
    hit_count: int
```

- `lookup(query)` → SHA-256 精确匹配
- `store(query, answer)` → L2 成功后写入
- `invalidate(query)` → 手动失效
- TTL 默认 3600s，最大 10000 条目

### 8.5 L1 Tiny Router

**文件**：`kernel/tiny_router.py`
**类**：`TinyRouter`
**模型**：JuniorShort 1.7B (LLMRole.ROUTER)

**分类 Prompt**（最小化设计，~80ms）：

```
分类用户查询，只输出一个JSON对象，不要额外内容。
{"route": "identity|faq|tool|knowledge|complex",
 "difficulty": "trivial|simple|moderate|complex",
 "needs_tool": bool, "needs_data": bool, "needs_web": bool}
查询: {query}
```

**路由矩阵**：

| 分类 | 处理 | 模型 |
|------|------|------|
| identity | CANONICAL_IDENTITY_RESPONSE | 无 LLM |
| faq | 直接回答 | MiddleShort 8B (FAST) |
| knowledge | 知识问答 | SeniorShort 14B (KNOWLEDGE) |
| tool | 工具分发 | 工具管线 |
| complex | 落入 L2 | 全管线 |

**JSON 解析降级策略**：
1. 正则提取 `\{[^{}]*\}`
2. `json.loads()` 解析
3. True/False → true/false 后重试
4. 降级为 `{"route": "complex"}`

### 8.6 复杂度引擎

**文件**：`kernel/complexity_engine.py`
**类**：`ComplexityEngine`
**特征**：基于规则，无 LLM，0-100 分

**评分因子**：

| 因子 | 权重 | 信号 |
|------|------|------|
| 查询长度 | 0-30 | <10=0, 10-30=10, 30-100=20, >100=30 |
| 歧义信号 | 0-25 | 模糊代词+15, 缺失实体+10 |
| 工具需求 | 0-20 | 工具关键词+10, 文件/代码+15 |
| 风险信号 | 0-30 | PII+40, SQL注入+50 |
| 多跳指示 | 0-25 | 跨表引用+20, 时间对比+20 |
| 领域特异性 | 0-20 | 数据查询+15, 文档检索+10 |
| L1 偏差 | ±15 | L1 结果可用的调整 |

**阈值**：

| 分数 | 级别 | 推荐管线 |
|------|------|---------|
| 0-20 | trivial | L0/L1 |
| 21-40 | simple | L1 |
| 41-60 | moderate | L1 或 L2 |
| 61-100 | complex | L2 |

### 8.7 功能开关

| 开关 | 默认值 | 说明 |
|------|--------|------|
| `kernel_v5_routing_enabled` | `True` | V5 主开关 |
| `kernel_l0_rule_router_enabled` | `True` | L0 规则路由 |
| `kernel_l1_tiny_router_enabled` | `True` | L1 Tiny Router |
| `kernel_semantic_cache_enabled` | `True` | 语义缓存 |
| `kernel_semantic_cache_threshold` | `0.92` | 相似度阈值 |
| `kernel_semantic_cache_ttl_seconds` | `3600` | 缓存 TTL |
| `kernel_semantic_cache_max_entries` | `10000` | 最大条目 |

### 8.8 kernel/__init__.py 导出

V5 模块已导出为内核公共 API：

```python
from kernel import L0RuleRouter, L0Result
from kernel import TinyRouter, L1Result
from kernel import ComplexityEngine, ComplexityScore
from kernel import SemanticCache, CacheEntry
```

---

## 9. V4 编排器（Orchestrator V4）

**文件**：`kernel/orchestrator_v4.py`（1000+ 行核心调度逻辑）

### 9.1 架构

```
OrchestratorV4Request
    │
    ▼
Process:
├── 1. force_mode 检测 → 跳过规划
├── 2. PlanAgent → TaskPlan（DAG 子任务图）
├── 3. Dispatcher → 并行调度子任务到 Agent Cluster
├── 4. DAG Scheduler → 依赖解析 + 拓扑排序
├── 5. 各 Agent 执行 → 返回候选结果
├── 6. FusionEngine → 加权融合多源证据
├── 7. CriticEngine → 质量审校 + 重写/拒答
└── 8. Final Answer → 结构化回答 + 引文 + 注释
```

### 9.2 有效强制模式

```python
VALID_FORCE_MODES = frozenset({
    "rag", "data_query", "data_analysis", "anomaly_tracking",
    "product", "rule_engine", "tool", "skills", "web",
})
```

### 9.3 Agent 映射

| force_mode | Agent 类型 |
|------------|------------|
| `rag` | `rag` |
| `data_query` | `data` |
| `data_analysis` | `data` |
| `anomaly_tracking` | `anomaly_tracking` |
| `product` | `product` |
| `rule_engine` | `rule_engine` |
| `tool` | `tool` |
| `skills` | `skills` |
| `web` | `web` |

### 9.4 PlanAgent

**文件**：`kernel/plan_agent.py`

```python
@dataclass
class TaskPlan:
    subtasks: list[SubTask]
    merge_strategy: str  # prioritized | parallel | sequential
    max_parallel: int
    is_multi_question: bool = False

@dataclass
class SubTask:
    agent_type: str
    query: str
    dependencies: list[str]
    sub_question_id: str = ""
    display_order: int = 0
    metadata: dict
```

关键方法：
- `generate_plan(query, context)` → 单问题规划
- `generate_multi_plan(questions, context)` → 多子问题规划
- `__attach_deps_multi(tasks)` → 跨问题依赖检测（15+ 模式）

### 9.5 Dispatcher

**文件**：`kernel/dispatcher.py`

- 并发任务分发，支持 `max_parallel` 限制
- 超时管理：每个 Agent 独立超时
- 降级：Agent 失败不阻塞其他 Agent

### 9.6 Fusion + Critic

- **FusionEngine**（`kernel/fusion_engine/engine.py`）：加权融合多 Agent 结果
- **SequenceFusionEngine**（`kernel/fusion_engine/sequence_fusion.py`）：多子问题顺序融合，含 `_generate_knowledge_answer()` 事实问题降级
- **CriticEngine**（`kernel/critic_engine/`）：质量审校 + 重写建议

---

## 10. 智能体集群（Agent Cluster）

### 10.1 BaseAgent

**文件**：`agents/base.py`

所有 Agent 继承 `BaseAgent`，需实现 `execute(task: SubTask) -> AgentResult`。

### 10.2 Agent 列表

| Agent | 文件 | 说明 | 启停开关 |
|-------|------|------|---------|
| DataAgent | `data_agent.py` | Text2SQL 数据查询 | `KERNEL_AGENT_DATA_ENABLED` |
| RAGAgent | `rag_agent.py` | 文档检索（pgvector） | `KERNEL_AGENT_RAG_ENABLED` |
| WebAgent | `web_agent.py` | 联网搜索（Serper API） | `KERNEL_AGENT_WEB_ENABLED` |
| ToolAgent | `tool_agent.py` | 通用工具（时间/天气/计算） | `KERNEL_AGENT_TOOL_ENABLED` |
| SkillsAgent | `skills_agent.py` | 技能调用 | — |
| RuleEngineAgent | `rule_engine_agent.py` | YAML 规则引擎 | — |

### 10.3 Agent Worker

**文件**：`agents/worker.py`

消费 Redis Bus 消息，支持两种模式：
- `pubsub`：发布/订阅，低延迟
- `stream`：消费者组 + ACK + 待处理消息回取

### 10.4 Agent 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `KERNEL_AGENT_TIMEOUT_SEC` | 25 | Agent 执行超时 |
| `KERNEL_AGENT_MAX_PARALLEL` | 5 | 最大并发数 |
| `KERNEL_AGENT_MAX_RETRY` | 1 | 最大重试次数 |
| `KERNEL_AGENT_RUNTIME_SUPERVISOR_ENABLED` | true | 运行时监督 |
| `KERNEL_AGENT_BUS_ENABLED` | false | Agent Bus 模式 |
| `KERNEL_AGENT_BUS_MODE` | pubsub | Bus 模式 |
| `KERNEL_AGENT_BUS_NAMESPACE` | opentrace:agent | Bus 命名空间 |

---

## 11. 模型网关（Model Gateway）

**文件**：`model/model_gateway/gateway.py`

### 11.1 角色路由（7 个角色）

| 角色 | 用途 | 默认模型 | 参数量 |
|------|------|----------|--------|
| `ROUTER` | L1 单次分类 | qwen3-1.7b | 1.7B |
| `FAST` | 简单 FAQ/问候回答 | qwen3-8b | 8B |
| `KNOWLEDGE` | 事实性知识问答 | qwen3-14b | 14B |
| `CHEAP_CRITIC` | 轻量级质量审校 | qwen3-14b | 14B |
| `PLANNING` | 意图识别、任务规划 | qwen3.5-flash | 8B |
| `COMPRESS` | 上下文压缩、总结 | qwen3.5-27b | 27B |
| `QUERY` | 用户查询回答 | qwen3.6-plus | 32B |

每个角色有独立的 CircuitBreaker 和重试策略。

### 11.2 Short 模型配置

| Short 名称 | LLMRole | 模型 | 用途 |
|-----------|---------|------|------|
| SeniorShort | KNOWLEDGE / CHEAP_CRITIC | qwen3-14b | 知识问答 + 轻量审校 |
| MiddleShort | FAST | qwen3-8b | 简单答案生成 |
| JuniorShort | ROUTER | qwen3-1.7b | L1 分类路由 |
| MinShort | — | qwen3-0.6b | 保留待用 |

### 11.3 错误分类与重试

- `transient`（瞬时错误）→ 重试
- `rate_limit`（限流）→ 指数退避重试
- `context_length`（上下文超长）→ 自动截断上下文后重试
- `model_error`（模型不可用）→ 切换备用 provider
- `offline`（服务离线）→ 降级到 `_offline_fallback_response()`

### 11.4 离线降级

`_offline_fallback_response()` 为所有 7 个角色提供角色特定的降级响应：
- ROUTER → `{"route": "complex", "difficulty": "simple"}`
- FAST → 用户友好降级消息
- KNOWLEDGE → 知识库不可用提示
- CHEAP_CRITIC → `{"verdict": "pass", "confidence": 0.5}`

### 11.5 嵌入与重排

| 组件 | 文件 | 默认实现 |
|------|------|----------|
| Embedder | `model/embedding/base.py` | Dashscope text-embedding-v3 |
| Reranker | `model/reranker/base.py` | 启发式重排 |

---

## 12. 记忆系统（Memory System）

| 层 | 模块 | 文件 | 说明 |
|----|------|------|------|
| L1 工作记忆 | `working_memory` | `memory/working_memory/` | 环形缓冲区（最大 32 轮对话）+ 身份缓存 |
| L2 语义记忆 | `semantic_memory` | `memory/semantic_memory/` | 向量检索（pgvector） |
| L3 情节记忆 | `episodic_memory` | `memory/episodic_memory/` | 会话事件序列 |
| L4 程序记忆 | `procedural_memory` | `memory/procedural_memory/` | 成功的流程和工具链 |
| 路由 | `memory_router` | `memory/memory_router/` | 分层检索路由 |
| 演化 | `evolution` | `memory/evolution/` | 经验版本和策略收益 |

---

## 13. 执行平面（Execution Plane）

### 13.1 DAG 引擎

**文件**：`execution/dag_engine/`

- DAG 任务执行引擎
- 拓扑排序 + 依赖解析
- 并行调度

### 13.2 数据执行层

**文件**：`execution/data/`

| 文件 | 说明 |
|------|------|
| `db_router.py` | 多数据库路由 |
| `sql_executor.py` | SQL 只读执行（自动限制） |
| `query_intents.py` | 查询意图识别 |

### 13.3 工具路由

**文件**：`execution/tool_router/`

- 时间工具：`get_current_time()`
- 天气工具：`get_weather(city)`
- 计算器：`calculate(expression)`

---

## 14. 数据认知层（Data Cognition）

**文件**：`kernel/data_cognition/`（10 个文件）

### 14.1 Text2SQL 管线

```
自然语言查询
    │
    ▼
┌───────────────────┐
│ SemanticLayer     │ 语义理解 + 指标映射
│ SemanticParser    │ 意图解析
└──────┬────────────┘
       ▼
┌───────────────────┐
│ SchemaLinker      │ Schema 链接 + 外键推断
│ TableGraph        │ 表关系图
└──────┬────────────┘
       ▼
┌───────────────────┐
│ QueryPlanner      │ 查询规划
│ SQLBuilder        │ SQL 生成
└──────┬────────────┘
       ▼
┌───────────────────┐
│ SQLValidator      │ SQL 验证（只读检查、注入检测）
│ SQLRewriter       │ SQL 重写优化
│ SQLRanker         │ 候选 SQL 排序
└──────┬────────────┘
       ▼
┌───────────────────┐
│ QueryExecutor     │ 查询执行（自动 LIMIT）
└───────────────────┘
```

### 14.2 SQL 安全

- 强制只读检测
- 多语句禁止
- SQL 注入模式检测
- 自动追加 LIMIT（默认 100）
- 字符串字面量保护（`*`、`-` 在引号内允许）

### 14.3 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `text2sql_enabled` | true | Text2SQL 开关 |
| `text2sql_max_retry` | 2 | SQL 重试次数 |
| `text2sql_default_limit` | 100 | 默认 LIMIT |
| `text2sql_join_inference_enabled` | true | JOIN 推断 |
| `text2sql_max_join_depth` | 3 | 最大 JOIN 深度 |

---

## 15. 基础设施层（Infrastructure）

### 15.1 配置

**文件**：`infra/config/settings.py`

`Settings` 单例整合所有配置块：

| 配置块 | 说明 | 字段数 |
|--------|------|--------|
| `DatabaseSettings` | 数据库连接 | 6 |
| `RedisSettings` | Redis 多 DB | 6 |
| `LLMSettings` | 7 个 LLM 角色 | 28 |
| `EmbeddingSettings` | 嵌入模型 | 9 |
| `RerankSettings` | 重排模型 | 8 |
| `JWTSettings` | JWT | 3 |
| `SMTPSettings` | SMTP | 5 |
| `OTelSettings` | 链路追踪 | 4 |
| `AppSettings` | 应用 + 内核 + V5 | 60+ |

### 15.2 Redis 分库

| DB | 用途 |
|----|------|
| 10 | Session |
| 11 | Cache（语义缓存 + 精确去重） |
| 12 | Memory |
| 13 | Queue |
| 14 | Rate Limit |
| 15 | Pub/Sub |

### 15.3 存储

**文件**：`infra/storage/database.py`、`infra/storage/models.py`

- 异步 SQLAlchemy 引擎
- ORM 模型：User、ChatSession、TraceLog 等
- pgvector 扩展支持

### 15.4 可观测性

| 组件 | 文件 | 说明 |
|------|------|------|
| Logger | `observability/logger.py` | 结构化日志（structlog） |
| Metrics | `observability/metrics.py` | Prometheus 指标 |
| Tracer | `observability/tracer.py` | OpenTelemetry 追踪 |

### 15.5 错误处理

**文件**：`infra/errors/exceptions.py`

```python
class AppException(Exception):
    code: int       # 错误码
    message: str    # 用户消息
    details: dict   # 详细信息
    http_status: int  # HTTP 状态码
```

---

## 16. 安全与防护（Safety）

- **零信任风险评估**（`infra/security/zero_trust.py`）：输入风险评分
- **输入防护栏**（`safety/guardrails/`）：PII/SQL 注入/有害内容检测
- **SQL 只读校验**：所有生成的 SQL 强制只读
- **JWT 认证**：所有 API 端点需 Bearer Token
- **CORS**：已配置跨域支持

---

## 17. 技能系统（Skills）

**文件**：`skills/marketplace/`

- **Skill Store**（`store.py`）：技能 CRUD + 持久化
- **Skill Manifest**（`manifest.py`）：技能清单验证
- **Skills API**（`gateway/api_gateway/routers/skills.py`）：REST API
- **SkillsAgent**（`agents/skills_agent.py`）：技能执行

---

## 18. 规则引擎（Rule Engine）

**文件**：`rules/`（YAML 规则存储）、`agents/rule_engine_agent.py`

### 18.1 架构

- YAML 驱动的产品查询与业务规则引擎
- `/product` 斜杠命令触发
- `force_mode=product` 或 `rule_engine` 直接路由

### 18.2 规则管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rules` | 列出规则 |
| POST | `/rules` | 创建规则 |
| PUT | `/rules/{id}` | 更新规则 |
| DELETE | `/rules/{id}` | 删除规则 |
| GET | `/rules/yaml` | 生成 YAML |

### 18.3 前端规则页面

**文件**：`frontend/src/pages/RulesPage.tsx`

- 在线 CRUD 操作
- YAML 预览与生成
- 规则启用/禁用控制

---

## 19. 消息总线（Message Bus）

### 19.1 认知事件总线

**文件**：`infra/message_bus/cognitive_event_bus.py`

- 统一事件模型：PlanningEvent、ExecutionEvent、RetrievalEvent、ToolEvent、ValidationEvent、CriticEvent、FeedbackEvent、LearningEvent
- 事件携带统一元信息：trace_id、session_id、request_id、actor、timestamp

### 19.2 Agent Bus

**文件**：`infra/message_bus/agent_bus.py`

- 支持 `pubsub`（发布/订阅）和 `stream`（消费者组）两种模式
- 待处理消息回收（Pending Reclaim）
- 死信队列（DLQ）：`opentrace:agent:stream:dlq`

### 19.3 内存事件订阅器

**文件**：`infra/message_bus/subscribers.py`

- 生命周期绑定 FastAPI 应用启动/关闭事件
- 异步任务管理

---

## 20. 快捷标签与强制模式路由

### 20.1 L0 斜杠命令处理

**文件**：`kernel/query_router_v2.py`

斜杠命令在 L0 规则路由器中通过正则 `^/(\w[\w_]*)\s*` 检测，经别名映射解析为 `force_mode`，**不消耗任何 LLM 调用**。

### 20.2 9 种有效 force_mode

`rag`, `data_query`, `data_analysis`, `anomaly_tracking`, `product`, `rule_engine`, `tool`, `skills`, `web`

### 20.3 别名映射

| 输入 | force_mode |
|------|------------|
| `/data` | `data_query` |
| `/doc`, `/document` | `rag` |
| `/search` | `web` |
| `/rule` | `rule_engine` |

### 20.4 工具触发词自动路由

| 类别 | 示例查询 | 路由 |
|------|---------|------|
| 时间 | "现在几点" | force_mode=tool → ToolAgent |
| 天气 | "北京天气" | force_mode=tool → ToolAgent |
| 计算 | "1+1" | force_mode=tool → ToolAgent |

### 20.5 失败隔离原则

使用快捷标签时，**不使用其他 Agent 兜底**：
- Data 查询失败 → 数据查询错误提示
- RAG 无结果 → 知识库未找到提示
- Skills 无匹配 → 无可用技能提示
- 无 force_mode 时才使用 LLM 兜底

---

## 21. 数据库模型与迁移

### 21.1 ORM 模型

**文件**：`infra/storage/models.py`

| 模型 | 说明 |
|------|------|
| `User` | 用户（邮箱/密码/角色） |
| `ChatSession` | 聊天会话 |
| `TraceLog` | 请求追踪日志 |
| 更多 | 文档、记忆、任务、审计等 |

### 21.2 迁移

**文件**：`alembic/versions/`

- 所有迁移脚本需幂等
- 验证：`bash scripts/verify_migration_idempotent.sh`
- 基线 Schema：`scripts/sql/provided_schema.sql`

---

## 22. 配置说明

### 22.1 环境变量

**模板文件**：`.env.example`

主要配置分组：

**数据库**：
```
DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@postgres:5432/opentrace_v2
TOKEN_DB_URL=postgresql+asyncpg://postgres:PASSWORD@postgres:5432/opentrace_v2
```

**Redis**：
```
REDIS_URL=redis://localhost:6379/10
REDIS_SESSION_DB=10 / REDIS_CACHE_DB=11 / REDIS_MEMORY_DB=12
REDIS_QUEUE_DB=13 / REDIS_RATE_LIMIT_DB=14 / REDIS_PUBSUB_DB=15
```

**7 个 LLM 角色**：
```
DEFAULT_LLM_QUERY_* (qwen3.6-plus, 32B)
DEFAULT_LLM_COMPRESS_* (qwen3.5-27b, 27B)
DEFAULT_LLM_PLANING_* (qwen3.5-flash, 8B)
DEFAULT_LLM_SENIORSHORT_* (qwen3-14b, 14B)  # KNOWLEDGE + CHEAP_CRITIC
DEFAULT_LLM_MIDDLESHORT_* (qwen3-8b, 8B)     # FAST
DEFAULT_LLM_JUNIORSHORT_* (qwen3-1.7b, 1.7B) # ROUTER
DEFAULT_LLM_MINSHORT_* (qwen3-0.6b, 0.6B)    # 保留
```

**V5 路由层**：
```
KERNEL_V5_ROUTING_ENABLED=true
KERNEL_L0_RULE_ROUTER_ENABLED=true
KERNEL_L1_TINY_ROUTER_ENABLED=true
KERNEL_SEMANTIC_CACHE_ENABLED=true
```

**内核 V4**：
```
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_TIMEOUT_SEC=25
KERNEL_AGENT_MAX_PARALLEL=5
KERNEL_AGENT_MAX_RETRY=1
KERNEL_ADAPTIVE_MODE_ENABLED=true
KERNEL_ANSWER_DRAFT_CONFIDENCE_THRESHOLD=0.75
KERNEL_ANSWER_DRAFT_MAX_CHARS=220
RAG_MIN_SCORE=0.25
```

---

## 23. Docker 部署

### 23.1 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `postgres` | 5432 | PostgreSQL 16 + pgvector |
| `redis` | 6380→6379 | Redis 7 (512MB 限制, allkeys-lru) |
| `api` | 14100 | FastAPI 网关 |
| `agent-worker` | — | Agent 消息消费者 |
| `prometheus` | 14190→9090 | 指标收集（可选，observability profile） |
| `jaeger` | 14186:16686, 4317 | 分布式追踪（可选，observability profile） |

### 23.2 常用 Docker 命令

- 启动所有服务：`bash start.sh`
- 停止服务：`bash stop.sh`
- 强制重启：`bash restart.sh`
- 启动 + 可观测性：`bash start.sh --with-observability`
- 启动 + 验证：`bash start.sh --verify`
- 查看 API 日志：`bash scripts/docker_logs.sh api`
- 查看 Worker 日志：`bash scripts/docker_logs.sh agent-worker`
- 完全重置：`bash stop.sh --volumes && bash start.sh`

---

## 24. 常用命令

### 24.1 服务管理

| 命令 | 说明 |
|------|------|
| `bash start.sh` | 启动所有服务 |
| `bash stop.sh` | 停止所有服务 |
| `bash restart.sh` | 强制重启 |
| `bash start.sh --with-observability` | 启动 + Prometheus + Jaeger |
| `bash stop.sh --volumes` | 停止 + 清理数据卷 |

### 24.2 测试

| 命令 | 说明 |
|------|------|
| `pytest` | 运行全部 401 个测试 |
| `pytest tests/path/to/test.py::test_name` | 运行特定测试 |
| `pytest -v` | 详细输出 |
| `pytest -q` | 安静模式 |

### 24.3 代码质量

| 命令 | 说明 |
|------|------|
| `black .` | 代码格式化 |
| `ruff check .` | Lint 检查 |
| `mypy .` | 类型检查 |

### 24.4 数据库

| 命令 | 说明 |
|------|------|
| `alembic upgrade head` | 执行迁移 |
| `alembic history --verbose` | 查看迁移历史 |
| `bash scripts/verify_migration_idempotent.sh` | 验证迁移幂等性 |

---

## 25. 测试体系

### 25.1 总览

- **测试文件**：85 个（不含 `__init__.py`）
- **测试方法**：401 个
- **框架**：pytest + unittest.TestCase
- **风格**：合约测试（Contract Tests），验证代码结构和关键路径存在

### 25.2 主要测试模块

| 测试文件 | 测试数 | 覆盖范围 |
|---------|--------|---------|
| `test_v5_routing_contract.py` | 50 | V5 L0/L1/缓存/复杂度/导出/降级/.env |
| `test_data_cognition_pipeline.py` | 36 | Text2SQL 完整管线 |
| `test_multi_question_orchestration_contract.py` | 27 | 多子问题编排全链路 |
| `test_force_mode_routing.py` | 20 | 强制模式/斜杠命令路由 |
| `test_kernel_agent_loop.py` | 15 | 内核 Agent 循环 |
| `test_rag_agent_contract.py` | 14 | RAG 检索 Agent |
| `test_rule_engine_agent_contract.py` | 13 | 规则引擎 Agent |
| `test_streaming_ttft_contract.py` | 10 | 流式输出 + TTFT |
| `test_skills_api_contract.py` | 9 | 技能 API |
| `test_analytics_plugins.py` | 7 | 分析插件 |

其余 75 个测试文件覆盖 orchestrator、fusion、critic、bus、memory、database、adapters 等。

### 25.3 测试命令

```bash
pytest                          # 全部
pytest -v                       # 详细
pytest tests/test_v5_routing_contract.py -v  # V5 专项
pytest -q                       # 安静
```

---

## 26. 调试与排障

### 26.1 日志查看

```bash
bash scripts/docker_logs.sh api           # API 日志
bash scripts/docker_logs.sh agent-worker  # Worker 日志
docker compose logs postgres              # 数据库日志
docker compose logs redis                 # Redis 日志
```

### 26.2 健康检查

```bash
curl http://localhost:14100/api/v1/health         # 基础
curl http://localhost:14100/api/v1/health/deps    # 依赖
curl http://localhost:14100/api/v1/health/runtime # 运行时
```

### 26.3 常见问题

| 问题 | 排查方法 |
|------|---------|
| API 启动失败 | `docker compose logs api` |
| 数据库连接失败 | 检查 `DATABASE_URL`，确认 postgres 健康 |
| Redis 连接失败 | 检查 `REDIS_URL`，确认端口映射 |
| Agent 超时 | 增大 `KERNEL_AGENT_TIMEOUT_SEC` |
| 模型调用失败 | 检查 API Key，Provider 配置 |
| 斜杠命令不工作 | 确认 L0 规则路由已启用 |
| V5 路由未生效 | 检查 `KERNEL_V5_ROUTING_ENABLED=true` |

---

## 27. 开发规范

### 27.1 代码风格

- 格式化：`black .`（行宽 100）
- Lint：`ruff check .`（select E, F, I, N, UP）
- 类型检查：`mypy .`（Python 3.11, ignore_missing_imports）

### 27.2 架构原则

1. **统一入口**：所有能力通过内核调度，不旁路
2. **懒加载**：V5 模块使用懒加载单例模式
3. **安全第一**：SQL 只读验证、PII 检测、零信任评估
4. **约定优先**：合约测试验证结构而非行为
5. **无注释原则**：默认不写注释，仅在 WHY 不清晰时写

### 27.3 .env 管理

- 模板（无敏感信息）→ `.env.example`
- 开发环境（含密钥）→ `.env`（已 gitignore）
- 新开发者复制 `.env.example` 为 `.env` 并填入 API Key

---

## 28. 多子问题支持（Multi-Question）

### 28.1 数据模型

**文件**：`kernel/cognition/sub_question.py`

```python
@dataclass
class SubQuestion:
    id: str           # q1, q2, ...
    text: str         # 问题文本
    domain: str       # data / rag / web / tool / knowledge / general_qa
    display_order: int
    is_factual: bool
```

### 28.2 检测路径

**文件**：`kernel/cognitive_kernel.py`

1. **语法拆分**（`_split_by_syntax`）：检测 `_MULTI_Q_HINTS`（第一个、并告诉我、另外 等 15+ 关键词）
2. **LLM 拆分**（`_split_by_llm`）：语法拆分无结果时降级

### 28.3 领域分类

```python
_DOMAIN_DATA_KW  # 查询/统计/销量/订单/sql
_DOMAIN_RAG_KW   # 文档/手册/pdf/附件
_DOMAIN_WEB_KW   # 最新/新闻/搜索/weather
_DOMAIN_TOOL_KW  # 时间/天气/计算/工具
_FACTUAL_Q_PATTERNS  # 首都/定义/什么是
```

### 28.4 顺序融合

**文件**：`kernel/fusion_engine/sequence_fusion.py`

`SequenceFusionEngine` 按 `display_order` 顺序处理每个子问题结果，生成编号回答（Q1/Q2/...），并附加来源标记（数据查询/文档检索/联网搜索/工具执行/知识问答）。

**降级策略**：
- WebAgent API 故障（401）→ 事实问题用 `_generate_knowledge_answer()` LLM 降级
- 无数据源 → 降级到 tool_execution
- 子问题 > 5 → 截断到前 5 个

### 28.5 前端渲染

**文件**：
- `frontend/src/utils/parseMultiQuestion.ts` — Markdown 解析器
- `frontend/src/components/MultiQuestionCards.tsx` — 卡片组件

每个子问题渲染为：
- 彩色左边框（3px，按来源类型）
- Q1/Q2 编号徽章 + 来源标签
- 错误态红色边框

### 28.6 多子问题与 V5 的交互

- `is_multi` 在 `run()` 顶部一次性计算
- 多子问题时，L0 身份/FAQ 快捷路径自动绕过
- L1 分类对多问题仍生效（整句分类为 complex → 落入 L2）

---

> 文档版本：SERVICE.md
>
> 维护原则：当核心能力、运行链路、配置项、API 端点发生变化时，优先追加或者修改或者更新本文档，使其始终代表当前项目状态的准确参考。
