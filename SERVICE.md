# OpenTrace 完整项目文档

> 本文档是 OpenTrace 项目的唯一权威参考，涵盖架构设计、API 接口、配置说明、数据流程、部署方案和开发指南。

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [系统架构](#3-系统架构)
4. [目录结构](#4-目录结构)
5. [前端应用](#5-前端应用)
6. [API 网关](#6-api-网关)
7. [认知内核（Cognitive Kernel）](#7-认知内核cognitive-kernel)
8. [V4 编排器（Orchestrator V4）](#8-v4-编排器orchestrator-v4)
9. [智能体集群（Agent Cluster）](#9-智能体集群agent-cluster)
10. [模型网关（Model Gateway）](#10-模型网关model-gateway)
11. [记忆系统（Memory System）](#11-记忆系统memory-system)
12. [执行平面（Execution Plane）](#12-执行平面execution-plane)
13. [数据认知层（Data Cognition）](#13-数据认知层data-cognition)
14. [基础设施层（Infrastructure）](#14-基础设施层infrastructure)
15. [安全与防护（Safety）](#15-安全与防护safety)
16. [技能系统（Skills）](#16-技能系统skills)
17. [认知事件总线（Cognitive Event Bus）](#17-认知事件总线cognitive-event-bus)
18. [快捷标签与强制模式路由](#18-快捷标签与强制模式路由)
19. [数据库模型与迁移](#19-数据库模型与迁移)
20. [配置说明](#20-配置说明)
21. [Docker 部署](#21-docker-部署)
22. [常用命令](#22-常用命令)
23. [测试体系](#23-测试体系)
24. [调试与排障](#24-调试与排障)
25. [开发规范](#25-开发规范)

---

## 1. 项目概述

OpenTrace 是一个**认知内核驱动的 Agent 系统**，支持以下核心能力：

- **对话式问答**：同步和 SSE 流式两种模式
- **工具调用**：时间、天气、代码执行等
- **RAG 文档问答**：基于 pgvector 的知识库检索
- **Text2SQL 数据查询**：自然语言转 SQL 并自动执行
- **推理链可视化**：完整的推理步骤和 DAG 执行图展示
- **多层记忆**：工作记忆、语义记忆、情节记忆、程序记忆
- **记忆演化**：离线强化、剪枝、模式提取

**V4 架构核心理念**：Plan（规划）→ Dispatcher（调度）→ Agent Cluster（智能体集群）→ Fusion（融合）→ Critic（审校）

---

## 2. 技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **语言** | Python 3.11+ | 后端运行时 |
| **Web 框架** | FastAPI | 高性能异步 API 网关 |
| **前端** | React 18 + Vite + TypeScript | 用户界面 |
| **状态管理** | Zustand | 轻量级前端状态管理 |
| **数据库** | PostgreSQL 16 + pgvector | 业务数据 + 向量检索 |
| **缓存** | Redis 7 | 缓存、会话、消息队列、事件流 |
| **ORM** | SQLAlchemy (async) | 异步数据库操作 |
| **迁移** | Alembic | 数据库模式管理 |
| **LLM 协议** | OpenAI-compatible API | 兼容 Dashscope/Qwen 等 |
| **嵌入模型** | text-embedding-v3 (Dashscope) | 向量嵌入 |
| **可观测性** | OpenTelemetry + Prometheus + Jaeger | 指标、追踪、日志 |
| **部署** | Docker Compose | 容器化部署 |

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React/Vite)                     │
│  Port 14108 — ChatInput, ChatView, Documents, Skills, Memories  │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼──────────────────────────────────────┐
│                    API Gateway (FastAPI)                         │
│  Port 14100 — Auth, Chat, Documents, Databases, Memories, etc.  │
│                                                                  │
│  ├── Guardrails（输入校验）                                       │
│  ├── Zero-Trust（风险评估 + 权限令牌）                             │
│  ├── Data Source Context（数据源上下文加载）                       │
│  └── Cognitive Kernel 路由                                       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  Cognitive Kernel（认知内核）                      │
│                                                                  │
│  ├── CognitiveKernel.run() / .stream()                           │
│  └── OrchestratorV4.process()                                    │
│       ├── Adaptive Profile（自适应配置）                           │
│       ├── WorldModel（世界模型 grounding）                         │
│       ├── PlanAgent（任务规划）                                    │
│       ├── DAG Scheduler（依赖调度）                                │
│       ├── Dispatcher（并发分发）                                   │
│       │    └── Agent Bus（Redis pubsub/stream）                   │
│       ├── FusionEngine（证据融合）                                 │
│       ├── CriticEngine（质量审校）                                 │
│       └── ContentAnnotator（内容标注）                             │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                   Agent Cluster（智能体集群）                      │
│                                                                  │
│  ├── DataAgent（Text2SQL：语义解析 → 查询规划 → SQL 构建 → 执行）  │
│  ├── RagAgent（文档检索 + LLMWiki + 语义记忆）                     │
│  ├── WebAgent（联网搜索 via Serper）                               │
│  ├── ToolAgent（工具调度：时间/天气/代码）                          │
│  └── SkillsAgent（技能匹配执行）                                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    Infrastructure（基础设施）                      │
│                                                                  │
│  ├── PostgreSQL（pgvector）— 业务数据 + 向量存储                   │
│  ├── Redis（6 个 DB）— 缓存/会话/消息/队列/限流                    │
│  ├── Model Gateway — 多角色 LLM 路由（QUERY/PLANNING/COMPRESS）   │
│  ├── Memory System — 五层记忆架构                                 │
│  ├── Observability — 日志/指标/追踪                               │
│  └── Security — 零信任风险评估 + 权限令牌                         │
└──────────────────────────────────────────────────────────────────┘
```

---

## 4. 目录结构

```
opentrace/
├── frontend/                    # React 前端应用
│   ├── src/
│   │   ├── api/client.ts        # API 客户端（所有后端调用）
│   │   ├── components/          # UI 组件
│   │   │   └── ChatInput.tsx    # 聊天输入（含快捷标签/斜杠命令）
│   │   ├── store/               # Zustand 状态管理
│   │   ├── lib/                 # 工具库
│   │   └── utils/               # 辅助函数
│   └── package.json
├── gateway/                     # FastAPI 网关
│   └── api_gateway/
│       ├── main.py              # FastAPI 应用入口
│       └── routers/             # API 路由模块
│           ├── auth.py          # 认证（注册/登录/Token）
│           ├── chat.py          # 聊天（同步/流式/重生成/图控制）
│           ├── conversations.py # 会话管理
│           ├── documents.py     # 文档管理
│           ├── databases.py     # 数据源管理
│           ├── data.py          # 数据查询
│           ├── memories.py      # 记忆 CRUD
│           ├── skills.py        # 技能管理
│           ├── tasks.py         # 任务管理
│           ├── health.py        # 健康检查
│           ├── cognitive.py     # 认知事件回放
│           ├── feedback.py      # 用户反馈
│           ├── audit.py         # 审计日志
│           ├── connectors.py    # 连接器
│           ├── sandbox.py       # 沙箱
│           ├── admin.py         # 管理接口
│           └── ui_settings.py   # 用户 UI 设置
├── kernel/                      # 认知内核
│   ├── cognitive_kernel.py      # 唯一中枢入口（run/stream）
│   ├── orchestrator_v4.py       # V4 编排器（核心调度逻辑）
│   ├── plan_agent.py            # 任务规划 Agent
│   ├── dispatcher.py            # 并发任务分发
│   ├── dag_scheduler.py         # DAG 依赖调度
│   ├── fusion_engine/           # 证据融合引擎
│   ├── critic_engine/           # 质量审校引擎
│   ├── context_pipeline.py      # 上下文处理管道
│   ├── intent_engine/           # 意图识别
│   ├── meta_cognition/          # 元认知（质量门控）
│   ├── epistemology/            # 认识论（内容标注/验证）
│   ├── adaptive_profiles.py     # 自适应配置（速度/质量/均衡）
│   ├── cognition/               # 认知模块（世界模型/任务模型）
│   ├── data_cognition/          # 数据认知（Text2SQL 管线）
│   ├── context/                 # 查询重写
│   ├── identity/                # 系统身份
│   └── prompts/                 # Prompt 模板
├── agents/                      # 智能体集群
│   ├── base.py                  # BaseAgent 抽象基类
│   ├── data_agent.py            # 数据查询 Agent（Text2SQL）
│   ├── rag_agent.py             # RAG 检索 Agent
│   ├── web_agent.py             # 联网搜索 Agent
│   ├── tool_agent.py            # 通用工具 Agent
│   ├── skills_agent.py          # 技能调用 Agent
│   ├── worker.py                # Agent Worker（消费 Redis 消息）
│   └── registry.py              # Agent 注册与发现
├── model/                       # 模型网关
│   └── model_gateway/
│       └── gateway.py           # 模型路由 + 熔断 + 重试
│   └── llm_adapter/
│       └── openai_adapter.py    # OpenAI 兼容适配器
│   └── embedding/
│       └── base.py              # 嵌入模型接口
│   └── reranker/
│       └── base.py              # 重排接口
├── memory/                      # 记忆系统
│   ├── working_memory/          # 工作记忆（环形缓冲区）
│   ├── semantic_memory/         # 语义记忆（向量检索）
│   ├── episodic_memory/         # 情节记忆（会话事件）
│   ├── procedural_memory/       # 程序记忆
│   ├── memory_router/           # 记忆路由
│   └── evolution/               # 记忆演化
├── execution/                   # 执行平面
│   ├── dag_engine/              # DAG 执行引擎
│   ├── data/                    # 数据执行层
│   │   ├── db_router.py         # 多数据库路由
│   │   ├── sql_executor.py      # SQL 执行器
│   │   └── query_intents.py     # 查询意图识别
│   └── tool_router/             # 工具路由
├── infra/                       # 基础设施
│   ├── config/settings.py       # 统一配置
│   ├── storage/                 # 存储层
│   │   ├── database.py          # DB 连接管理
│   │   └── models.py            # SQLAlchemy ORM 模型
│   ├── cache/                   # 缓存层
│   │   └── redis_client.py      # Redis 多 DB 连接
│   ├── message_bus/             # 消息总线
│   │   ├── events.py            # 认知事件模型
│   │   ├── cognitive_event_bus.py # 认知事件总线
│   │   ├── agent_bus.py         # Agent 消息总线
│   │   └── bus.py               # 通用消息总线
│   ├── observability/           # 可观测性
│   │   ├── logger.py            # 结构化日志
│   │   ├── metrics.py           # Prometheus 指标
│   │   └── tracer.py            # OpenTelemetry 追踪
│   ├── security/                # 安全层
│   │   └── zero_trust.py        # 零信任风险评估
│   ├── guards/                  # 守卫
│   │   └── kernel_guard.py      # 入口点要求
│   ├── errors/                  # 错误处理
│   │   └── exceptions.py        # AppException + ErrorCodes
│   ├── audit/                   # 审计
│   │   └── logger.py            # 审计日志写入
│   └── metadata/                # 元数据
│       └── schema_inspector.py  # 数据库 Schema 检查
├── safety/                      # 安全防护
│   └── guardrails/              # 输入防护栏
├── skills/                      # 技能系统
│   └── marketplace/             # 技能市场
│       ├── store.py             # 技能存储
│       └── manifest.py          # 技能清单
├── alembic/                     # 数据库迁移
│   ├── env.py                   # Alembic 环境
│   └── versions/                # 迁移脚本
├── deploy/                      # 部署配置
│   └── docker/
│       ├── Dockerfile           # 后端镜像
│       └── prometheus.yml       # Prometheus 配置
├── scripts/                     # 运维脚本
├── tests/                       # 测试
├── docker-compose.yml           # Docker 编排
├── pyproject.toml               # Python 项目配置
├── alembic.ini                  # Alembic 配置
├── .env.example                 # 环境变量模板
├── CLAUDE.md                    # Claude Code 项目指引
├── RUNBOOK.md                   # 运维手册
├── start.sh / stop.sh           # 启停脚本
└── SERVICE.md                   # 本文档
```

---

## 5. 前端应用

### 5.1 技术选型

| 组件 | 技术 | 版本 |
|------|------|------|
| 框架 | React | 18.x |
| 构建 | Vite | 5.x |
| 语言 | TypeScript | 5.x |
| 状态 | Zustand | 4.x |
| 样式 | Tailwind CSS + clsx | — |
| 图标 | lucide-react | — |
| 代码高亮 | Shiki | — |
| 路由 | React Router | 6.x |

### 5.2 页面路由

| 路径 | 说明 |
|------|------|
| `/login` | 用户登录 |
| `/chat` | 主聊天页面（核心入口） |
| `/documents` | 知识库文档管理 |
| `/settings` | 系统设置 |
| `/tasks` | 任务管理 |
| `/audit` | 审计日志 |
| `/memories` | 记忆管理 |
| `/integrations` | 集成管理 |
| `/databases` | 数据源管理 |
| `/skills` | 技能市场 |

### 5.3 核心组件

- **ChatInput**：聊天输入框，支持快捷标签、`/` 斜杠命令、联网开关、数据源选择
- **ChatView**：消息列表，支持推理链、工具调用状态、DAG 执行图展示
- **ReasoningChain**：推理步骤可视化
- **ExecutionGraph**：DAG 执行图可视化
- **DocumentUploader**：文档上传与预览

### 5.4 API 客户端模式

所有后端调用统一通过 `frontend/src/api/client.ts`，使用 `apiFetch()` 基础函数：

```typescript
// 核心调用
apiChatStream(token, sessionId, query, callbacks, webEnabled, signal, mode, payload, graphControls)
apiChatSync(token, sessionId, query, options)
apiCreateConversation(token)
apiListDatabases(token)
apiDatabaseQuery(token, dataSourceId, params)
apiGetDatabaseSchema(token, dataSourceId)
```

前端 dev server 运行在 `http://localhost:14108`，API 请求代理到 `http://localhost:14100`。

### 5.5 快捷标签与斜杠命令

输入 `/` 立即弹出候选下拉框，包含 4 个命令：

| 命令 | 标签 | force_mode | 说明 |
|------|------|------------|------|
| `/rag` | 知识库检索 | `rag` | 检索知识库中的文档 |
| `/data_query` | 数据查询 | `data_query` | 执行数据库 SQL 查询 |
| `/data_analysis` | 数据分析 | `data_analysis` | 数据库分析查询 |
| `/skills` | 异常追踪 | `anomaly_tracking` | 调用已安装的技能 |

**交互规则**：
- 输入 `/` 立即弹出全部选项（无需额外字符）
- 输入 `/ra` 自动过滤匹配项
- `↑/↓` 方向键导航，`Enter/Tab` 确认选择，`Escape` 关闭
- 点击外部区域自动关闭
- 选择后自动插入前缀 + 空格，光标移至其后

---

## 6. API 网关

**基础路径**：`/api/v1`
**端口**：`14100`
**框架**：FastAPI
**中间件**：CORS、Request ID、异常处理、内存事件订阅生命周期

### 6.1 认证接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/token` | 获取 Token |
| POST | `/auth/login` | 用户登录 |
| GET | `/auth/me` | 获取当前用户信息 |

### 6.2 聊天接口

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 同步聊天 或 SSE 流式（`stream: true`） |
| POST | `/chat/stop` | 停止当前流式输出 |
| POST | `/chat/graph-control` | 实时图控制（裁剪/展开节点） |
| POST | `/chat/regenerate` | 重新生成最后一次回答 |
| POST | `/chat/edit-and-regenerate` | 编辑消息后重新生成 |
| POST | `/chat/resume` | 从历史步骤恢复 |

**ChatRequest 核心参数**：

| 参数 | 类型 | 说明 |
|------|------|------|
| `query` | string | 用户查询（必填，1-8192 字符） |
| `session_id` | string\|null | 会话 ID |
| `stream` | bool | 是否流式输出 |
| `web_enabled` | bool | 是否启用联网搜索 |
| `force_mode` | string\|null | 强制模式：`rag`、`data_query`、`data_analysis`、`anomaly_tracking` |
| `force_database` | bool | 强制走数据源查询 |
| `data_source_id` | string\|null | 指定数据源 ID |
| `enabled_skills` | string[] | 启用的技能白名单 |
| `disabled_skills` | string[] | 禁用的技能黑名单 |
| `tool_permission_token` | string\|null | 工具权限令牌 |
| `confirmation_granted` | bool | 是否已授权高风险操作 |
| `graph_controls` | object | 图控制：`{pruned_nodes: [], expanded_nodes: []}` |

**SSE 事件类型**：

| 事件类型 | data 字段 | 说明 |
|----------|-----------|------|
| `reasoning_step` | `{id, stage, content, node_id, status}` | 推理步骤 |
| `thinking` | `{content}` | 思考内容 |
| `delta` | `{text}` | 流式文本片段 |
| `agent_start` | `{agent_type, task_id, query}` | Agent 开始执行 |
| `agent_progress` | `{agent_type, task_id, progress, message}` | Agent 执行进度 |
| `agent_complete` | `{agent_type, task_id, status, preview}` | Agent 执行完成 |
| `dag_node_start` | `{node_id, agent_type, depends_on}` | DAG 节点开始 |
| `dag_node_complete` | `{node_id, agent_type, status, preview}` | DAG 节点完成 |
| `tool_call` | — | 工具调用 |
| `tool_result` | — | 工具返回结果 |
| `final_answer` | `{content, execution_graph, citations, annotations}` | 最终回答 |
| `error` | `{message}` | 错误信息 |
| `aborted` | `{message}` | 用户中止 |
| `adaptive_profile` | profile 对象 | 自适应配置信息 |
| `force_mode` | `{mode}` | 使用的强制模式 |
| `answer_draft` | `{content}` | 草稿预览 |
| `conflict_summary` | — | 证据冲突说明 |

### 6.3 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/conversations` | 获取会话列表（支持分页、搜索、归档过滤） |
| POST | `/conversations` | 创建新会话 |
| PATCH | `/conversations/{id}` | 更新会话标题 |
| POST | `/conversations/{id}/archive` | 归档会话 |
| DELETE | `/conversations/{id}` | 删除会话 |
| PATCH | `/messages/{id}` | 编辑消息 |
| POST | `/conversations/{id}/branch` | 从消息分支创建新会话 |
| GET | `/conversations/{id}/messages` | 获取会话消息列表 |

### 6.4 文档管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/documents` | 文档列表 |
| POST | `/documents` | 上传文档 |
| GET | `/documents/{doc_id}` | 获取文档详情 |
| DELETE | `/documents/{doc_id}` | 删除文档 |
| PUT | `/documents/{doc_id}` | 更新文档 |
| POST | `/documents/search` | 文档搜索 |

### 6.5 数据源管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/databases` | 数据源列表 |
| POST | `/databases` | 创建数据源 |
| GET | `/databases/{id}` | 获取数据源详情 |
| PATCH | `/databases/{id}` | 更新数据源 |
| DELETE | `/databases/{id}` | 删除数据源 |
| POST | `/databases/{id}/test-connection` | 测试连接 |
| POST | `/databases/{id}/sync-schema` | 同步数据库 Schema |
| GET | `/databases/{id}/schema` | 获取 Schema |
| POST | `/databases/{id}/query` | 执行查询 |
| POST | `/databases/{id}/analysis` | 数据分析 |
| GET | `/databases/{id}/semantic` | 获取语义映射 |
| PUT | `/databases/{id}/semantic` | 更新语义映射 |
| POST | `/databases/{id}/semantic/auto-extract` | 自动提取语义映射 |

### 6.6 数据查询

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/data/query` | 执行自然语言数据查询 |
| POST | `/data/schema/sync` | 同步数据源 Schema |
| GET | `/data/schema` | 获取 Schema 状态 |

### 6.7 记忆管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/memories` | 获取记忆列表 |
| POST | `/memories` | 创建记忆 |
| PATCH | `/memories/{id}` | 更新记忆 |
| DELETE | `/memories/{id}` | 删除记忆 |
| GET | `/memories/settings` | 获取记忆设置 |
| POST | `/memories/settings` | 更新记忆设置 |

### 6.8 技能管理

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/skills` | 获取已安装技能列表 |
| POST | `/skills/install` | 安装技能 |
| POST | `/skills/create` | 创建技能 |
| GET | `/skills/{id}` | 获取技能详情 |
| POST | `/skills/{id}/test` | 测试技能 |
| POST | `/skills/uninstall` | 卸载技能 |
| POST | `/skills/session/bind` | 绑定技能到会话 |
| GET | `/skills/session/{id}` | 获取会话技能配置 |

### 6.9 其他接口

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/health` | 基础健康检查 |
| GET | `/health/deps` | 依赖健康检查（DB、Redis、Agent Worker） |
| GET | `/health/runtime` | 运行时信息（版本、开关、词库大小） |
| GET | `/ping` | 简单连通性检查 |
| POST | `/tasks` | 创建任务 |
| GET | `/tasks` | 任务列表 |
| GET | `/tasks/{id}` | 任务详情 |
| POST | `/tasks/pause` | 暂停任务 |
| POST | `/tasks/resume` | 恢复任务 |
| POST | `/tasks/cancel` | 取消任务 |
| POST | `/tasks/events/trigger` | 触发任务事件 |
| GET | `/tasks/notifications` | 获取通知 |
| POST | `/tasks/notifications/read` | 标记通知已读 |
| GET | `/connectors` | 连接器列表 |
| POST | `/connectors/authorize` | 授权连接器 |
| POST | `/connectors/callback` | 连接器回调 |
| POST | `/connectors/sync` | 同步连接器 |
| POST | `/feedback` | 提交用户反馈 |
| GET | `/audit/logs` | 获取审计日志 |
| GET | `/audit/export` | 导出审计日志 |
| GET | `/sandbox/download` | 沙箱下载 |
| GET | `/cognitive-events/replay` | 按 trace_id 回放认知事件时间线 |
| GET | `/users/ui-settings` | 获取用户 UI 设置 |
| PATCH | `/users/ui-settings` | 更新用户 UI 设置 |
| GET | `/admin/tools` | 管理员工具列表 |
| GET | `/admin/strategy` | 策略信息 |
| GET | `/admin/gateway/health` | 网关健康检查 |

---

## 7. 认知内核（Cognitive Kernel）

**入口文件**：`kernel/cognitive_kernel.py`

认知内核是系统的**唯一中枢入口**，所有能力（记忆/文档/联网/工具/RAG）均通过内核调度，禁止绕过内核直接调用 LLM。

### 7.1 核心原则

1. 所有输出必须由认知内核生成
2. 所有插件返回的数据只是「候选认知材料」
3. LLM 不是回答器，而是「认知执行器」
4. Prompt 不是模板，而是「认知协议」

### 7.2 执行流程

```
Step 1: intent_domain  — 意图域分类（DATA_QUERY / DOCUMENT_RETRIEVAL / WEB_SEARCH / TOOL_EXECUTION / GENERAL_QA）
Step 2: SelfModel      — 自我能力评估（能力等级：AVAILABLE / DEGRADED / UNAVAILABLE）
Step 3: OrchestratorV4 — 统一走 V4 编排器
Step 4: Identity Guard — 身份问答缓存检查
Step 5: Memory Save    — 异步保存对话记忆（不阻塞响应）
```

### 7.3 两个入口方法

| 方法 | 说明 | 返回 |
|------|------|------|
| `run(request)` | 同步执行，一次性返回完整回答 | `KernelResponse` |
| `stream(request)` | SSE 流式输出，逐步推送事件 | `AsyncIterator[dict]` |

### 7.4 意图域分类

```python
def _classify_intent_domain(query) -> TaskDomain:
    # DATA_QUERY: 包含 "查询"、"统计"、"报表"、"销量"、"订单"、"sql"、"数据库"
    # DOCUMENT_RETRIEVAL: 包含 "文档"、"手册"、"pdf"、"doc"、"附件"、"总结文档"
    # WEB_SEARCH: 包含 "最新"、"新闻"、"今天"、"实时"、"联网"、"搜索"、"weather"
    # TOOL_EXECUTION: 包含 "执行"、"工具"、"调用"、"计算"、"时间"、"天气"
    # GENERAL_QA: 其他
```

### 7.5 身份问答保护

- 检测到身份问题（如 "你是谁"）时，优先检查 `working_memory` 缓存
- 缓存命中直接返回，不调用 LLM
- 未命中走 V4 编排器，返回后写入缓存
- 系统身份响应统一为：`CANONICAL_IDENTITY_RESPONSE`

---

## 8. V4 编排器（Orchestrator V4）

**入口文件**：`kernel/orchestrator_v4.py`（1000+ 行核心调度逻辑）

### 8.1 架构总览

```
OrchestratorV4Request
    │
    ▼
┌─ Adaptive Profile ──────────────────────────────────┐
│  根据查询类型选择 Speed/Balanced/Quality 配置         │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌─ WorldModel ────────────────────────────────────────┐
│  实体消歧、时间短语解析、词汇归一化                    │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌─ Force Mode 路由（快捷标签直接路由）                   │
│  /rag → rag Agent                                    │
│  /data_query → data Agent                            │
│  /data_analysis → data Agent                         │
│  /skills → skills Agent                              │
│  无 force_mode → PlanAgent 智能规划                  │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌─ Task Plan ─────────────────────────────────────────┐
│  SubTask 列表 + 依赖关系 + 合并策略                   │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌─ Dispatcher ────────────────────────────────────────┐
│  并行/串行分发到 Agent 集群                            │
│  支持 Agent Bus（Redis pubsub/stream）                │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌─ Fusion Engine ─────────────────────────────────────┐
│  加权证据融合：llmwiki(1.05) > document(0.72)       │
│  > sql(1.0) > search(0.6) > tool                    │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌─ Critic Engine ─────────────────────────────────────┐
│  后融合质量检查、一致性验证                           │
└──────────────────────────────────────────────────────┘
    │
    ▼
┌─ Content Annotation ────────────────────────────────┐
│  证据级别标注（FACT/DOCUMENT/SEARCH/MEMORY/INFERENCE）│
│  输出验证、冲突标注、备选证据                           │
└──────────────────────────────────────────────────────┘
    │
    ▼
OrchestratorV4Response（content + route + metadata）
```

### 8.2 自适应配置（Adaptive Profiles）

| Profile | 适用场景 | 特点 |
|---------|----------|------|
| `speed` | 联网搜索、实时查询 | 快速响应，降低证据要求 |
| `balanced` | 默认 | 速度与质量均衡 |
| `quality` | 数据库查询、文档总结、复杂分析 | 高质量要求，多轮反思 |

自动选择规则：
- 包含 "最新"、"新闻"、"实时"、"联网" → `speed`
- 包含 "文档"、"总结"、"归纳"、"pdf" → `quality`
- 包含 "查询"、"统计"、"报表"、"sql" → `quality`
- 其他 → `balanced`

### 8.3 Force Mode 路由

当用户通过快捷标签选择模式时，跳过 PlanAgent，直接创建对应的 Agent 子任务：

```python
agent_map = {
    "rag": "rag",
    "data_query": "data",
    "data_analysis": "data",
    "anomaly_tracking": "skills",
}
```

**Guard 规则**：
- `data` Agent 必须有 `data_source_id`，否则立即返回错误提示
- Force mode 下不使用其他 Agent 兜底
- Force mode 失败时返回模式相关的中文提示信息

### 8.4 回答格式化

#### 数据查询回答
- COUNT 结果 → `"查询结果：X 条记录。"`
- 多行结果 → `"查询已执行，共返回 X 行数据。结果预览：..."`
- 0 行结果 → 解释可能原因 + 建议检查数据源和表结构
- 仅有 SQL → 提供 SQL 代码块 + 指引

#### RAG 回答
- LLM 整理证据 → 自然流畅的完整回答
- 附带来源引用信息
- 证据不足时说明缺失点

### 8.5 失败处理策略

| 场景 | 处理方式 |
|------|----------|
| Force mode 缺少数据源 | 立即返回提示信息，不调用 LLM |
| Force mode 所有 Agent 失败 | 返回模式相关提示，不调用 LLM |
| Data Agent 返回 error | 返回错误提示 + 详情，不用其他 Agent 兜底 |
| Data Agent 返回 0 行 | 解释原因 + 建议 |
| 非 force_mode 全部失败 | 调用 LLM 兜底回答 |

### 8.6 输出净化（_sanitize_user_output）

- 移除内部标记：`[tool]`、`[web_search]`、`[sql]` 等
- 移除 Emoji：`📊📄🔗🧠💡⚠️ℹ️`
- 移除 JSON 内部结构
- 移除工具错误前缀行
- 空内容回退到默认提示

---

## 9. 智能体集群（Agent Cluster）

### 9.1 基类

**文件**：`agents/base.py`

- `BaseAgent`：抽象基类，定义 `agent_type` 和 `execute(task)` 接口
- `TaskMessage`：任务消息（task_id, agent_type, query, params, session_id, user_id）
- `AgentResult`：执行结果（task_id, agent_type, status, content, confidence, metadata, error）

### 9.2 Data Agent（数据查询 Agent）

**文件**：`agents/data_agent.py`

**模式**：
- `pipeline`（默认）：语义解析 → 查询规划 → SQL 构建 → 执行 + 自验证
- `llm_direct`（降级）：LLM 直接生成 SQL

**Pipeline 流程**：
1. 结构化意图检测（table_count、table_list、table_schema）
2. 语义解析（SemanticParser）
3. 查询规划（QueryPlanner → LogicalPlan）
4. SQL 执行 + 自验证重试（QueryExecutor，最多 2 次重试）
5. 构建解释（Explanation）

**LLM Direct 流程**：
1. 语义层解析（SemanticLayer）
2. SQL 生成（SQLPlanner）
3. 多候选生成（4 个候选）
4. 排序（SQLRanker）
5. 时间过滤器验证
6. 执行 + 反思循环（SQLReflector，最多 3 轮）

### 9.3 Rag Agent（RAG 检索 Agent）

**文件**：`agents/rag_agent.py`

**检索来源**：
- 文档向量检索（pgvector）
- LLMWiki 检索（结构化的 Q&A 知识库）
- 用户语义记忆
- 用户情节记忆

**特性**：
- 查询词展开（同义词扩展）
- 动态分数阈值（根据证据质量调整）
- 多源去重合并

### 9.4 Web Agent（联网搜索 Agent）

**文件**：`agents/web_agent.py`

- 使用 Serper API 进行网络搜索
- 结果提取和格式化
- 需要 `SERPER_API_KEY` 配置

### 9.5 Tool Agent（通用工具 Agent）

**文件**：`agents/tool_agent.py`（通过 `kernel/orchestrator_v4.py` 中的 `ToolAgent` 类实现）

- 通过 `ToolRouter` 路由到对应工具
- 支持工具：datetime（时间）、get_weather（天气）、code（代码执行）
- 工具名称自动识别（基于返回内容）

### 9.6 Skills Agent（技能调用 Agent）

**文件**：`agents/skills_agent.py`

- 列出已安装技能
- 按 enabled_skills 白名单过滤
- 按 force_mode 匹配最佳技能类型
- 执行技能测试，选择最佳匹配结果
- 无匹配技能时返回友好提示

### 9.7 Agent Worker

**文件**：`agents/worker.py`

- 消费 Redis 消息（pubsub 或 stream 模式）
- 接收任务消息 → 查找对应 Agent → 执行 → 发布结果
- 支持 pending 消息回收和死信队列（DLQ）
- 通过 `python -m agents.worker` 启动

### 9.8 Agent 注册表

**文件**：`agents/registry.py`

- `AgentRegistry`：管理 Agent 注册和查找
- `register(agent)` → 按 agent_type 注册
- `get_agent(agent_type)` → 获取 Agent 实例
- `has_agent(agent_type)` → 检查是否存在

---

## 10. 模型网关（Model Gateway）

**文件**：`model/model_gateway/gateway.py`

### 10.1 角色路由

| 角色 | 用途 | 默认模型 |
|------|------|----------|
| `QUERY` | 用户查询回答、回答生成 | qwen3-32b |
| `PLANNING` | 意图识别、任务规划、工具选择 | qwen3-8b |
| `COMPRESS` | 上下文压缩、对话总结 | qwen3-14b |

每个角色有独立的 CircuitBreaker（熔断器）和重试策略。

### 10.2 错误分类与重试

- `transient`（瞬时错误）→ 重试
- `rate_limit`（限流）→ 指数退避重试
- `context_length`（上下文超长）→ 自动截断上下文后重试
- `model_error`（模型不可用）→ 切换到备用 provider
- `offline`（服务离线）→ 降级到本地启发式方法

### 10.3 嵌入与重排

| 组件 | 文件 | 默认实现 |
|------|------|----------|
| Embedder | `model/embedding/base.py` | Dashscope text-embedding-v3 |
| Reranker | `model/reranker/base.py` | 启发式重排 |

---

## 11. 记忆系统（Memory System）

| 层 | 模块 | 文件 | 说明 |
|----|------|------|------|
| L1 工作记忆 | `working_memory` | `memory/working_memory/` | 环形缓冲区（最大 32 轮对话）+ 身份缓存 |
| L2 语义记忆 | `semantic_memory` | `memory/semantic_memory/` | 语义知识存储（内存 + pgvector 后备） |
| L3 情节记忆 | `episodic_memory` | `memory/episodic_memory/` | 历史交互（Redis 存储，7 天 TTL） |
| L4 程序记忆 | `procedural_memory` | `memory/procedural_memory/` | 操作指南、流程知识 |
| L5 记忆演化 | `evolution` | `memory/evolution/` | 离线作业：强化/剪枝/模式提取 |

### 11.1 记忆路由

`memory/memory_router/router.py` — 联邦检索：
1. 语义检索（向量相似度）
2. 情节检索（按会话/时间）
3. 关键词匹配
4. 图谱检索
5. 重排（Reranker）

### 11.2 记忆 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET/POST | `/memories` | 列表/创建 |
| PATCH/DELETE | `/memories/{id}` | 修改/删除 |
| GET/POST | `/memories/settings` | 学习设置 |

### 11.3 记忆演化

- **脚本**：`scripts/memory_evolve.py`
- **流程**：Case → Pattern → Skill
- **策略**：强化（使用频率 → 强度衰减）、剪枝（弱关联淘汰）

---

## 12. 执行平面（Execution Plane）

### 12.1 DAG 引擎

**文件**：`execution/dag_engine/engine.py`

- 依赖感知的有向无环图执行
- 支持拓扑排序和并行执行
- 检查点/恢复机制
- 重试 + 指数退避
- 推测性执行（可选）

### 12.2 数据库层

**文件**：`execution/data/`

| 文件 | 说明 |
|------|------|
| `db_router.py` | 多数据库路由（PostgreSQL/MySQL/ClickHouse/Doris） |
| `sql_executor.py` | SQL 执行器（SQLAlchemy async engine） |
| `query_intents.py` | 查询意图识别（table_count、table_list、table_schema） |

### 12.3 工具路由

**文件**：`execution/tool_router/`

- 基于意图的工具选择
- 参数自动提取和过滤
- 签名感知的 kwargs 过滤

---

## 13. 数据认知层（Data Cognition）

完整的 Text2SQL 管线，位于 `kernel/data_cognition/`。

| 模块 | 文件 | 说明 |
|------|------|------|
| 语义解析器 | `semantic_parser.py` | 自然语言 → 结构化意图（实体/指标/过滤/时间窗/分组/排序） |
| 语义层 | `semantic_layer.py` | 语义映射管理（维度/指标/同义词/时间宏） |
| Schema 链接器 | `schema_linker.py` | 实体 → 表/列映射 |
| 查询规划器 | `query_planner.py` | 语义结果 → LogicalPlan |
| SQL 构建器 | `sql_builder.py` | LogicalPlan → SQL |
| SQL 方言 | `sql_dialect.py` | PostgreSQL/MySQL 方言适配 |
| SQL 排序器 | `sql_ranker.py` | 多候选 SQL 排序 |
| SQL 验证器 | `sql_validator.py` | SQL 安全性检查（只读、LIMIT、时间过滤） |
| SQL 反思器 | `sql_reflector.py` | 执行结果验证 + 反思修正 |
| SQL 重写器 | `sql_rewriter.py` | 基于错误信息的 SQL 重写 |
| SQL 后处理 | `sql_postprocess.py` | 方言归一化 |
| 查询执行器 | `query_executor.py` | 带自验证的重试执行 |
| 解释生成器 | `explanation.py` | SQL → 自然语言解释 |

### 13.1 语义解析器特性

- **Redis 缓存**：相同查询 + 相同 Schema 版本 → 直接返回缓存结果
- **缓存键**：query + schema_version + table_names 的 SHA256 哈希
- **TTL**：默认 24 小时
- **Prometheus 指标**：缓存命中率、延迟分布
- **结构化意图检测**：table_count、table_list、table_schema 直接返回 SQL，跳过 LLM

### 13.2 查询意图识别（query_intents.py）

快速检测以下意图，直接返回 SQL：
- `table_count`：查询表数量
- `table_list`：查询表列表
- `table_schema`：查询表结构

### 13.3 SQL 验证规则

- 只允许 SELECT 语句
- 自动追加 LIMIT（默认 100）
- 时间范围过滤检查
- JOIN 深度限制（默认 3）
- 危险操作拦截（DELETE/UPDATE/DROP 等）

---

## 14. 基础设施层（Infrastructure）

### 14.1 统一配置

**文件**：`infra/config/settings.py`

基于 pydantic-settings 的统一配置，从 `.env` 文件加载，支持 9 个子配置块。

### 14.2 Redis 多 DB 设计

| DB | 用途 | 配置项 |
|----|------|--------|
| 10 | 会话管理 | `redis_session_db` |
| 11 | 缓存 | `redis_cache_db` |
| 12 | 记忆 | `redis_memory_db` |
| 13 | 队列 | `redis_queue_db` |
| 14 | 限流 | `redis_rate_limit_db` |
| 15 | 发布/订阅 | `redis_pubsub_db` |

### 14.3 消息总线

**文件**：`infra/message_bus/`

| 文件 | 说明 |
|------|------|
| `events.py` | 认知事件模型（CognitiveEvent + 6 种事件类型） |
| `cognitive_event_bus.py` | 认知事件总线（发布/订阅/回放） |
| `event_store.py` | 不可变事件日志（Redis Stream + trace 索引） |
| `agent_bus.py` | Agent 消息总线（pubsub + stream 双模式） |
| `bus.py` | 通用消息总线 |

**CognitiveEvent 字段**：
- `event_id`（UUID）、`event_type`、`trace_id`、`session_id`、`user_id`
- `request_id`、`timestamp`、`causation_id`、`source`、`actor`、`payload`

**事件类型**：
| 类型 | 说明 |
|------|------|
| `planning` | 规划生成、子任务拆解 |
| `execution` | Agent 执行、工具调用 |
| `evidence` | 证据到达、置信度变化 |
| `critic` | 审校结果、失败标签 |
| `feedback` | 用户反馈、人工修正 |
| `learning` | 策略更新、记忆强化 |

### 14.4 可观测性

| 模块 | 说明 |
|------|------|
| `observability/logger.py` | Structlog 结构化日志 |
| `observability/metrics.py` | Prometheus 指标（请求计数、延迟、缓存命中率） |
| `observability/tracer.py` | OpenTelemetry 分布式追踪 |
| `observability/request_context.py` | 请求上下文（trace_id、user_id、session_id） |
| `observability/runtime_metrics.py` | 运行时指标存储 |

### 14.5 错误处理

| 模块 | 说明 |
|------|------|
| `errors/exceptions.py` | `AppException` + `ErrorCodes` 枚举 |
| `infra/guards/kernel_guard.py` | `@require_kernel_entrypoint` 装饰器 |

### 14.6 安全层

**文件**：`infra/security/zero_trust.py`

- **查询风险评估**：分析查询需要的权限（读/写/管理）
- **权限令牌**：短期有效的 JWT 令牌
- **工具异常检测**：检测工具调用序列异常
- **高风险操作确认**：弹窗确认机制

### 14.7 审计日志

**文件**：`infra/audit/logger.py`

- 记录安全事件、权限变更、管理操作
- 可通过 `GET /api/v1/audit/logs` 查询
- 支持导出（`GET /api/v1/audit/export`）

### 14.8 元数据检查

**文件**：`infra/metadata/schema_inspector.py`

- 自动检查数据库 Schema
- 提取表名和列信息
- 构建 Schema 提示字符串

---

## 15. 安全与防护（Safety）

### 15.1 输入防护栏（Guardrails）

**文件**：`safety/guardrails/`

- 输入内容检查（敏感词、注入攻击检测）
- 长度限制（max 8192 字符）
- 在 chat router 入口处执行

### 15.2 零信任模型

**文件**：`infra/security/zero_trust.py`

```
查询到达 → 风险评估 → 需要权限？
    ├── 是 → 检查 token → 验证通过？
    │   ├── 通过 → 继续执行
    │   └── 失败 → 返回权限令牌
    └── 否 → 直接执行
```

---

## 16. 技能系统（Skills）

### 16.1 架构

| 文件 | 说明 |
|------|------|
| `skills/marketplace/store.py` | 技能存储（安装/卸载/列表） |
| `skills/marketplace/manifest.py` | 技能清单定义 |
| `skills/marketplace/verifier.py` | 技能验证器 |

### 16.2 技能生命周期

1. **创建**：`POST /skills/create` — 定义技能元数据和处理逻辑
2. **安装**：`POST /skills/install` — 从 Git 仓库安装
3. **测试**：`POST /skills/{id}/test` — 验证技能是否正常工作
4. **绑定**：`POST /skills/session/bind` — 绑定到特定会话
5. **卸载**：`POST /skills/uninstall` — 移除技能

### 16.3 技能匹配

SkillsAgent 通过 `_score_match()` 计算技能匹配度：
- 技能名称匹配查询关键词
- 技能类型与 force_mode 对齐
- 描述文本相似度

---

## 17. 认知事件总线（Cognitive Event Bus）

### 17.1 定位

认知事件总线是 OpenTrace 的**系统级事实流**，负责记录"发生了什么"，并把规划、执行、证据、审校、反馈、学习统一为可回放、可订阅、可追溯的不可变事件日志。

### 17.2 关键设计

- 所有事件统一携带 `trace_id`、`session_id`、`timestamp`、`causation_id`
- 事件按不可变日志存储，支持完整回放与审计复盘
- `Agent Bus` 负责任务调度，`Cognitive Event Bus` 负责系统认知状态演进
- `Fusion`、`Critic`、`Memory`、`Evolution` 统一消费事件流

### 17.3 当前落地状态

- 已接入 `chat router`、`orchestrator_v4`、`feedback`
- 提供 `GET /api/v1/cognitive-events/replay` 按 `trace_id` 回放事件时间线
- 支持按 `event_type` 过滤（planning/execution/evidence/critic/feedback/learning）
- 事件发布失败不影响主流程

---

## 18. 快捷标签与强制模式路由

### 18.1 前端实现

**文件**：`frontend/src/components/ChatInput.tsx`

用户输入 `/` 后立即弹出候选下拉框，可选择 4 个命令，选择后自动插入前缀 + 空格。

### 18.2 路由映射

| 快捷命令 | force_mode | Agent 类型 | 说明 |
|----------|------------|------------|------|
| `/rag` | `rag` | `rag` | 知识库检索 |
| `/data_query` | `data_query` | `data` | 数据库 SQL 查询 |
| `/data_analysis` | `data_analysis` | `data` | 数据库分析查询 |
| `/skills` | `anomaly_tracking` | `skills` | 技能调用 |

### 18.3 数据查询快查路径

**文件**：`gateway/api_gateway/routers/chat.py`

当 `force_database=true` 且有有效数据源时，直接调用 `/data/query` 端点，**不走完整的 kernel 编排流程**，大幅降低延迟。SSE 流式输出也走此快查路径。

### 18.4 失败隔离原则

使用快捷标签时，**不使用其他 Agent 兜底**：
- Data 查询失败 → 返回数据查询错误提示
- RAG 无结果 → 返回知识库未找到提示
- Skills 无匹配 → 返回无可用技能提示
- 仅在没有 force_mode 时才使用 LLM 兜底

---

## 19. 数据库模型与迁移

### 19.1 ORM 模型

**文件**：`infra/storage/models.py`

| 模型 | 说明 |
|------|------|
| `User` | 用户（邮箱/密码/角色） |
| `ChatSession` | 聊天会话 |
| `TraceLog` | 请求追踪日志 |
| `ReasoningTrace` | 推理步骤追踪 |
| `ToolStat` | 工具使用统计 |
| `Document` | 知识库文档 |
| `UserMemory` | 用户记忆 |
| `UserMemorySettings` | 用户记忆设置 |
| `DataSource` | 数据源配置 |
| `DataSourceSchema` | 数据源 Schema 缓存 + 语义映射 |
| `Task` | 任务 |
| `AuditLog` | 审计日志 |
| `Feedback` | 用户反馈 |
| `SkillInstall` | 技能安装记录 |
| `Connector` | 连接器配置 |
| `UISettings` | 用户 UI 设置 |

### 19.2 数据库迁移

**工具**：Alembic
**配置**：`alembic.ini` + `alembic/env.py`
**迁移脚本**：`alembic/versions/`

所有迁移设计为幂等，可通过 `bash scripts/verify_migration_idempotent.sh` 验证。

基线 Schema：`scripts/sql/provided_schema.sql`

---

## 20. 配置说明

### 20.1 环境变量

复制 `.env.example` 为 `.env` 后修改配置。以下为关键配置项：

#### 数据库

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_URL` | `postgresql+asyncpg://...` | PostgreSQL 连接串 |
| `TOKEN_DB_URL` | 同上 | Token 存储连接串 |

#### Redis

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `REDIS_URL` | `redis://localhost:6379/10` | Redis 连接串 |

#### LLM（3 角色各一组）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DEFAULT_LLM_QUERY_PROVIDER` | `openai` | 查询模型提供商 |
| `DEFAULT_LLM_QUERY_MODEL` | `qwen3-32b` | 查询模型 |
| `DEFAULT_LLM_QUERY_BASE_URL` | `https://dashscope...` | 查询模型 API 地址 |
| `DEFAULT_LLM_QUERY_API_KEY` | — | 查询模型 API 密钥 |
| `DEFAULT_LLM_PLANING_MODEL` | `qwen3-8b` | 规划模型 |
| `DEFAULT_LLM_COMPRESS_MODEL` | `qwen3-14b` | 压缩模型 |

#### 嵌入

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_PROVIDER` | `dashscope` | 嵌入提供商 |
| `EMBEDDING_MODEL_NAME` | `text-embedding-v3` | 嵌入模型 |
| `EMBEDDING_DIMS` | `1024` | 嵌入维度 |
| `EMBEDDING_API_KEY` | — | 嵌入 API 密钥 |

#### 内核

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `KERNEL_ORCHESTRATOR_VERSION` | `v4` | 编排器版本 |
| `KERNEL_AGENT_ENABLED` | `true` | 启用 Agent 集群 |
| `KERNEL_AGENT_DATA_ENABLED` | `true` | 启用数据 Agent |
| `KERNEL_AGENT_RAG_ENABLED` | `true` | 启用 RAG Agent |
| `KERNEL_AGENT_WEB_ENABLED` | `true` | 启用联网 Agent |
| `KERNEL_AGENT_TOOL_ENABLED` | `true` | 启用工具 Agent |
| `KERNEL_AGENT_TIMEOUT_SEC` | `30` | Agent 超时（秒） |
| `KERNEL_AGENT_MAX_PARALLEL` | `5` | 最大并行 Agent 数 |
| `KERNEL_ANSWER_DRAFT_CONFIDENCE_THRESHOLD` | `0.75` | 草稿置信度阈值 |
| `KERNEL_ANSWER_DRAFT_MAX_CHARS` | `220` | 草稿最大字符数 |
| `KERNEL_ADAPTIVE_MODE_ENABLED` | `true` | 自适应模式开关 |
| `KERNEL_AGENT_BUS_ENABLED` | `false` | Agent 消息总线开关 |
| `KERNEL_FUSION_ENABLED` | `false` | 融合引擎开关 |
| `KERNEL_CRITIC_ENABLED` | `false` | 审校引擎开关 |

#### 数据库/Text2SQL

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TEXT2SQL_ENABLED` | `true` | 启用 Text2SQL |
| `TEXT2SQL_DEFAULT_LIMIT` | `100` | 默认返回行数 |
| `TEXT2SQL_MAX_RETRY` | `2` | 最大重试次数 |
| `SERPER_API_KEY` | — | 联网搜索 API 密钥 |

#### RAG

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `RAG_MIN_EVIDENCE_SCORE` | `0.65` | 最低证据分数 |
| `LLMWIKI_ENABLED` | `true` | 启用 LLMWiki |

---

## 21. Docker 部署

### 21.1 服务清单

**文件**：`docker-compose.yml`

| 服务 | 镜像 | 端口 | 说明 |
|------|------|------|------|
| `postgres` | pgvector/pgvector:pg16 | 5432 | PostgreSQL + pgvector |
| `redis` | redis:7-alpine | 6380 | Redis（maxmemory 512mb） |
| `api` | 自定义构建 | 14100 | FastAPI 网关 |
| `agent-worker` | 自定义构建 | — | Agent Worker（消费 Redis 消息） |
| `prometheus` | prom/prometheus | 14190 | 指标收集（observability profile） |
| `jaeger` | jaegertracing/all-in-one | 14186 | 分布式追踪（observability profile） |

### 21.2 启动流程

```
start.sh
├── 检查 Docker 是否运行
├── 运行数据库迁移（alembic upgrade head）
│   ├── 迁移成功 → 启动服务
│   └── 迁移失败 → 询问用户是否强制启动
├── docker compose up -d
├── 等待 api 服务健康检查通过
├── 检查 agent-worker 是否运行
├── 显示服务状态和访问地址
└── 可选：运行验证脚本（--verify）
```

### 21.3 健康检查

- **PostgreSQL**：`pg_isready -U postgres`（每 10s）
- **Redis**：`redis-cli ping`（每 10s）
- **API**：`curl -f http://localhost:14100/api/v1/health`（每 30s）
- 服务启动依赖：api 和 agent-worker 依赖 postgres 和 redis 健康检查通过

---

## 22. 常用命令

### 22.1 服务管理

| 命令 | 说明 |
|------|------|
| `bash start.sh` | 启动所有服务（含迁移检查） |
| `bash start.sh --verify` | 启动后运行验证 |
| `bash start.sh --with-observability` | 启动 + Prometheus + Jaeger |
| `bash stop.sh` | 停止所有服务 |
| `bash stop.sh --volumes` | 停止并删除数据卷（彻底重置） |
| `bash restart.sh` | 强制重启 |
| `docker compose ps` | 查看服务状态 |

### 22.2 日志查看

| 命令 | 说明 |
|------|------|
| `bash scripts/docker_logs.sh api` | 查看 API 日志 |
| `bash scripts/docker_logs.sh agent-worker` | 查看 Agent Worker 日志 |
| `bash scripts/docker_logs.sh postgres` | 查看 PostgreSQL 日志 |
| `bash scripts/docker_logs.sh redis` | 查看 Redis 日志 |

### 22.3 验证脚本

| 命令 | 说明 |
|------|------|
| `bash scripts/verify_all_docker.sh` | 全量验证（Docker 环境） |
| `bash scripts/verify_all.sh` | 全量验证（本地环境） |
| `bash scripts/verify_e2e.sh` | E2E 验证（登录 → 聊天 → 文档） |
| `bash scripts/verify_agent_cluster.sh` | Agent 集群验证（V4 + RAG + Bus） |
| `bash scripts/verify_agent_bus_e2e.sh` | Agent Bus 端到端验证 |
| `bash scripts/verify_migration_idempotent.sh` | 迁移幂等性验证 |
| `bash scripts/verify_error_envelope.sh` | 错误信封验证 |
| `bash scripts/verify_code_plugin.sh` | 代码插件验证 |
| `bash scripts/verify_docker.sh` | Docker 环境验证 |
| `bash scripts/verify_kernel_loop.sh` | 内核循环验证 |

### 22.4 数据库维护

| 命令 | 说明 |
|------|------|
| `bash scripts/apply_provided_schema_to_docker.sh` | 应用基线 Schema |
| `bash scripts/migrate_local_pg_to_docker.sh` | 迁移本地 PostgreSQL 到 Docker |
| `bash scripts/clean_session.sh` | 清理会话数据 |
| `bash scripts/clean_info.sh` | 清理用户信息 |
| `docker compose exec -T api alembic history --verbose` | 查看迁移历史 |
| `docker compose exec -T api alembic upgrade head` | 执行迁移 |
| `python scripts/seed_user.py` | 种子用户创建 |
| `python scripts/cleanup_retention.py` | 数据保留清理 |

### 22.5 记忆系统

| 命令 | 说明 |
|------|------|
| `python scripts/memory_evolve.py` | 执行记忆演化 |

### 22.6 前端

| 命令 | 说明 |
|------|------|
| `cd frontend && npm install` | 安装依赖 |
| `cd frontend && npm run dev` | 启动开发服务器（14108） |
| `cd frontend && npm run build` | 生产构建 |
| `cd frontend && npm run test` | 运行测试 |

### 22.7 代码质量

| 命令 | 说明 |
|------|------|
| `black .` | 代码格式化 |
| `ruff check .` | 代码检查 |
| `mypy .` | 类型检查 |
| `pytest` | 运行测试 |
| `pre-commit install` | 安装 pre-commit 钩子 |

### 22.8 其他

| 命令 | 说明 |
|------|------|
| `bash scripts/test_llm.py` | LLM 连接测试 |
| `bash scripts/test_dashscope_clients.py` | Dashscope 客户端测试 |
| `bash scripts/opentrace_replay.py` | 事件回放 |
| `bash scripts/preflight_release.sh` | 发布前检查 |
| `bash scripts/verify_all_docker.sh` | Docker 全量验证 |

---

## 23. 测试体系

### 23.1 测试文件（84+ 个测试）

| 测试模块 | 说明 |
|----------|------|
| `test_orchestrator_v4_contract.py` | V4 编排器合约测试 |
| `test_rag_agent_contract.py` | RAG Agent 合约测试 |
| `test_agent_bus_e2e_contract.py` | Agent Bus E2E 测试 |
| `test_databases_api_contract.py` | 数据源 API 合约测试 |
| `test_text2sql_validator_contract.py` | Text2SQL 验证器合约测试 |
| `test_cognition_self_model_contract.py` | 自我认知模型测试 |
| `test_adaptive_profiles.py` | 自适应配置测试 |
| `test_dag_engine.py` | DAG 引擎测试 |
| `test_safety_guardrails.py` | 安全防护测试 |
| `test_zero_trust.py` | 零信任安全测试 |
| `test_sandbox.py` | 沙箱测试 |
| `test_skills.py` | 技能系统测试 |
| `test_memory.py` | 记忆系统测试 |
| `test_documents.py` | 文档管理测试 |
| `test_data_agent_cognitive.py` | 数据 Agent 认知测试 |

### 23.2 运行方式

```bash
# 运行所有测试
pytest

# 运行特定测试
pytest tests/path/to/test.py::test_function

# 运行特定模块
pytest tests/test_orchestrator_v4_contract.py -v
```

### 23.3 Stage-Gate 发布验证

| 阶段 | 内容 |
|------|------|
| Stage 0 | 代码提交和基本语法检查 |
| Stage 1 | 单元测试和合约测试 |
| Stage 2 | 集成测试和 E2E 测试 |
| Stage 3 | 性能测试和安全扫描 |
| Stage 4 | 发布验证和回滚计划 |

---

## 24. 调试与排障

### 24.1 聊天请求排障流程

1. **按 trace_id 回放**：`GET /api/v1/cognitive-events/replay?trace_id=xxx`
2. **过滤阶段**：追加 `event_type=planning|execution|evidence|critic|feedback|learning`
3. **查看摘要**：关注 `summary.stage_counts`、`summary.duration_ms`
4. **检查 Critic**：查看最后一个 `CriticEvent` 定位失败原因

### 24.2 日志查看

```bash
# API 服务日志（主要业务逻辑）
bash scripts/docker_logs.sh api

# Agent Worker 日志（Agent 执行过程）
bash scripts/docker_logs.sh agent-worker

# 数据库日志
bash scripts/docker_logs.sh postgres
```

### 24.3 健康检查端点

| 端点 | 检查内容 |
|------|----------|
| `GET /api/v1/health` | 基本存活 |
| `GET /api/v1/health/deps` | DB、Redis、Agent Worker、Bus、Orchestrator |
| `GET /api/v1/health/runtime` | 编排器版本、注释开关、词库大小 |
| `GET /ping` | 最简单连通性 |

### 24.4 可观测性面板

| 工具 | 地址 | 说明 |
|------|------|------|
| Prometheus | `http://localhost:14190` | 指标查询和告警 |
| Jaeger | `http://localhost:14186` | 分布式追踪 UI |

### 24.5 常见问题

| 问题 | 排查步骤 |
|------|----------|
| 数据库连接失败 | 检查 `DATABASE_URL`、端口、密码、pg_isready |
| Redis 连接失败 | 检查 `REDIS_URL`、端口、redis-cli ping |
| LLM 调用失败 | 检查 `*_API_KEY`、`*_BASE_URL` 网络连通性 |
| Agent Worker 不消费 | 检查 `KERNEL_AGENT_BUS_ENABLED` 和 Redis pubsub_db |
| 数据查询返回非预期 | 检查 `data_source_id` 是否已选择、Schema 是否同步 |
| RAG 无结果 | 检查是否有上传文档、`RAG_MIN_EVIDENCE_SCORE` 阈值 |
| 前端 404 | 检查 Vite dev server 代理配置 |

### 24.6 强制重启

```bash
# 完全重置（包括数据）
bash stop.sh --volumes && bash start.sh

# 仅重启服务
bash restart.sh
```

---

## 25. 开发规范

### 25.1 Python 代码规范

- **格式化**：Black
- **Lint**：Ruff
- **类型检查**：MyPy
- **配置**：`pyproject.toml`

### 25.2 命名约定

- 模块/包：snake_case
- 类名：PascalCase
- 函数/变量：snake_case
- 常量：UPPER_SNAKE_CASE
- 私有成员：前缀 `_`

### 25.3 错误处理模式

- 所有业务错误通过 `AppException(ErrorCodes.XXX, message="...")` 抛出
- 数据库操作使用 `try/except` + `logger.warning` 记录
- 外部 API 调用使用 `return_exceptions=True` 的 `asyncio.gather`
- 缓存/非核心操作失败不影响主流程（静默降级）

### 25.4 数据库规范

- 所有查询为只读 SELECT
- 结果自动绑定到 `data_source_id`
- 后处理验证（行数限制、数据类型）
- 迁移必须幂等

### 25.5 安全规则

- 禁止在代码中硬编码密钥/密码
- 所有 LLM 调用必须通过 Model Gateway
- 敏感操作需要 Zero-Trust 权限令牌
- 审计日志记录所有安全事件

### 25.6 Git 工作流

- 功能分支：`feature/xxx`
- 修复分支：`fix/xxx`
- 提交信息：简洁描述变更内容
- 提交前：`black . && ruff check . && pytest`

### 25.7 默认开发账号

| 邮箱 | 密码 |
|------|------|
| `songts@tuwan.com` | `123456` |

### 25.8 端口汇总

| 服务 | 端口 | 协议 |
|------|------|------|
| Frontend (dev) | 14108 | HTTP |
| API Gateway | 14100 | HTTP |
| PostgreSQL | 5432 | TCP |
| Redis | 6380 | TCP |
| Prometheus | 14190 | HTTP |
| Jaeger UI | 14186 | HTTP |
| Jaeger OTLP | 4317 | gRPC |

---

> 文档最后更新：2026-04-24
> 维护者：OpenTrace 团队

---

## 26. 运行时生命周期与请求链路

### 26.1 系统启动顺序

OpenTrace 在完整启动时遵循以下顺序：

1. 读取 `.env` / 环境变量并初始化统一配置
2. 建立数据库、Redis、消息总线与可观测性组件连接
3. 执行数据库迁移和基础 Schema 检查
4. 启动 FastAPI 网关
5. 初始化认知内核、模型网关、记忆系统与安全守卫
6. 启动 Agent Worker 消费队列
7. 对外提供健康检查与业务接口

### 26.2 典型聊天请求链路

```text
前端输入 → ChatInput → /api/v1/chat → Guardrails → Zero-Trust 风险评估
→ 认知内核 → V4 编排器 → Agent Cluster / Tool Router / Data Plane
→ 证据融合 → Critic 审校 → 内容净化 → SSE/同步返回 → 前端渲染
```

### 26.3 关键运行时对象

| 对象 | 作用 |
|------|------|
| `RequestContext` | 维护 `trace_id`、`request_id`、`user_id`、`session_id` |
| `KernelRequest` | 认知内核统一输入对象 |
| `KernelResponse` | 认知内核统一输出对象 |
| `OrchestratorV4Request` | V4 编排器输入 |
| `AgentResult` | Agent 执行结果 |
| `CognitiveEvent` | 认知事件总线标准事件 |

### 26.4 并发与超时原则

- Agent 执行采用异步并发，默认并行上限由 `KERNEL_AGENT_MAX_PARALLEL` 控制
- 所有外部调用必须设置超时，避免请求链路无限等待
- 非核心能力失败应尽量降级，不阻塞主回答
- 流式输出优先保证首包速度，后续证据可逐步补齐

---

## 27. 接口契约与错误规范

### 27.1 API 约定

- 网关统一前缀为 `/api/v1`
- 所有写操作应支持幂等或可恢复设计
- 所有请求应携带上下文标识（如 `trace_id` / `request_id`）
- 列表接口优先提供分页、过滤、排序能力
- SSE 接口用于长耗时、分步可视化或流式回答场景

### 27.2 错误信封

项目统一使用结构化错误返回，核心字段包括：

| 字段 | 说明 |
|------|------|
| `code` | 错误码 |
| `message` | 面向用户的错误描述 |
| `details` | 可选的结构化错误详情 |
| `request_id` | 关联请求 ID |
| `trace_id` | 关联追踪 ID |

### 27.3 常见错误类别

| 类别 | 含义 | 处理建议 |
|------|------|----------|
| 参数错误 | 请求缺少字段或格式不合法 | 前端校验 + 服务端校验 |
| 权限错误 | Token 无效或权限不足 | 重新登录或申请权限 |
| 资源缺失 | 数据源、文档、技能不存在 | 检查对象 ID 和同步状态 |
| 外部依赖错误 | DB/Redis/LLM/搜索服务不可用 | 检查依赖健康状态 |
| 运行时失败 | Agent、编排器、执行器出错 | 查看 trace 回放与日志 |

### 27.4 前端交互原则

- 错误信息应尽量可操作，避免仅返回内部堆栈
- 流式接口中断后应允许用户重新生成或继续
- 用户取消应被视为正常中止，而非错误

---

## 28. 配置项补充说明

### 28.1 配置分层

配置通常分为以下几类：

1. **基础设施配置**：数据库、Redis、日志、追踪
2. **模型配置**：查询、规划、压缩、嵌入、重排
3. **内核配置**：编排器版本、开关、超时、并发
4. **业务配置**：RAG、Text2SQL、技能、记忆、连接器
5. **安全配置**：Zero-Trust、审计、权限令牌、输入防护

### 28.2 建议补全的环境变量类别

以下类别应在 `.env.example` 中保持同步维护：

| 类别 | 示例 |
|------|------|
| 基础服务地址 | `DATABASE_URL`、`REDIS_URL` |
| 模型提供商 | `*_PROVIDER`、`*_MODEL`、`*_BASE_URL`、`*_API_KEY` |
| 内核开关 | `KERNEL_*` |
| 记忆与检索 | `RAG_*`、`LLMWIKI_*` |
| 数据查询 | `TEXT2SQL_*`、`SERPER_API_KEY` |
| 安全与审计 | `ZERO_TRUST_*`、`AUDIT_*` |
| 可观测性 | `OTEL_*`、`PROMETHEUS_*`、`JAEGER_*` |
| 功能实验开关 | `*_ENABLED`、`*_TIMEOUT_SEC`、`*_MAX_*` |

### 28.3 配置变更原则

- 所有新配置项必须补充默认值、说明和适用范围
- 破坏性配置变更需在文档与启动脚本中同步说明
- 关键配置改动后应补充回归测试或验证脚本

---

## 29. 可扩展性与新增能力接入

### 29.1 新 Agent 接入流程

新增 Agent 时建议遵循以下步骤：

1. 继承 `BaseAgent`
2. 定义唯一 `agent_type`
3. 在 `agents/registry.py` 完成注册
4. 在 `orchestrator_v4` 中补充路由或规划策略
5. 如需异步消费，接入 `agents/worker.py`
6. 补充合约测试与 E2E 验证脚本

### 29.2 新工具接入流程

1. 在 `execution/tool_router/` 或对应工具模块实现工具
2. 增加参数校验、超时和错误处理
3. 通过 Model Gateway 或 Tool Agent 调用，不允许绕过统一入口
4. 如涉及高风险操作，必须接入 Zero-Trust 校验与审计日志

### 29.3 新数据源接入流程

1. 在 `databases` 维度完成连接器配置
2. 同步 Schema 并建立语义映射
3. 通过 `data_source_id` 绑定到查询请求
4. 完成只读验证、LIMIT 策略和 SQL 安全检查
5. 为常见意图补充数据查询示例与测试

### 29.4 新技能接入流程

1. 定义技能清单与元数据
2. 编写测试入口与说明
3. 上传或安装后通过 Skills Market 管理
4. 将技能纳入 `enabled_skills` / `disabled_skills` 过滤逻辑

---

## 30. 维护约定与文档治理

### 30.1 文档维护原则

- `SERVICE.md` 作为项目级事实总览，应优先保持“系统性、准确性、可维护性”
- 新增能力应先补文档，再补实现细节引用
- 若功能已弃用，应明确标注弃用状态与替代方案
- 章节应按系统层次组织，避免重复定义同一概念

### 30.2 更新检查清单

每次更新 `SERVICE.md` 时建议检查：

- 架构图与目录结构是否匹配当前代码
- API 路由是否新增、删除或更名
- 环境变量是否与 `settings.py` 和 `.env.example` 一致
- 默认端口、服务名、启动脚本是否准确
- 测试、排障与部署说明是否仍有效

### 30.3 版本演进建议

- 当核心编排器、消息总线或数据路径发生结构性变化时，应同步更新系统概览与请求链路
- 当新增外部依赖时，应补充健康检查、降级策略和错误处理说明
- 当删除旧模块时，应在文档中标记“已迁移/已弃用”并说明替代路径

---

## 31. 近期关键更新（补充自 SERVICE1）

### 31.1 2026-04-23：DataAgent 分阶段确定性推理管线 & 文档上下文感知分块

- DataAgent NL2SQL 管线从“黑盒生成”升级为“白盒推理 + 多重校验 + 执行反馈”的五阶段管线
- 文档分块升级为上下文感知分块，支持多种策略，中文/多语言更友好
- `kernel/data_cognition/` 新增语义解析、逻辑计划、SQL 构造、执行器、解释器等核心模块
- 增加 `sqlglot` 依赖用于 SQL 语法解析与验证

### 31.2 2026-04-22：历史基线补充

- 全量 API 路由继续补全，涵盖 admin / feedback / sandbox 等路由
- Evolution 进化系统完善为 learning / meta_learning / self_play / feedback / data_flywheel / evaluation
- Agent Runtime 运行时涵盖 agent_core / critic / executor / market / planner / reflector
- Kernel 内部模块持续细化为 identity / tools / reasoning / web_engine
- Execution 执行平面扩展为 dag_engine / sandbox / workflow_engine / scheduler
- Plugin 体系完整化，包含 chart / code / data / document / file / knowledge / memory / tool / web / structured_tool

---

## 32. 代码结构与职责映射补充

### 32.1 Gateway 路由补充

- `gateway/api_gateway/routers/health.py`：基础健康、依赖健康、运行态健康、`/ping`
- `gateway/api_gateway/routers/data.py`：统一数据查询入口，绑定 `data_source_id`
- `gateway/api_gateway/routers/feedback.py`：用户反馈收集，进入数据飞轮
- `gateway/api_gateway/routers/sandbox.py`：沙箱文件下载，需会话归属校验
- `gateway/api_gateway/routers/admin.py`：工具、学习、策略、Bandit、记忆、元学习、Agent 市场、自博弈

### 32.2 Kernel 关键模块补充

- `kernel/cognition/`：SelfModel / TaskModel / WorldModel / EntityRegistry / Types
- `kernel/epistemology/`：Annotator / Validator / Evidence / RenderHints
- `kernel/policy/`：策略引擎、Bandit、RL 策略
- `kernel/prompt_engine/`：Prompt 组装与版本化
- `kernel/context/`：上下文压缩、排序、查询重写
- `kernel/web_engine/`：搜索、重写、排序、引用构建

### 32.3 Frontend 交互补充

- `frontend/src/components/DecisionTraceCard.tsx`：决策追溯卡，展示事实、假设、置信度、重规划
- `frontend/src/components/DataQueryResult.tsx`：数据查询结果展示
- `frontend/src/components/DatabaseTypeSelect.tsx`：数据库类型选择器
- `frontend/src/components/ErrorBoundary.tsx`：前端错误边界
- `frontend/src/api/client.ts`：SSE 消费与 API 客户端

---

## 33. 运行时与请求链路补充

### 33.1 同步问答链路补充

1. 前端发送 `/api/v1/chat`
2. Chat Router 校验用户与会话归属
3. 若 `force_database=true` 且非流式，走数据查询快查路径
4. Kernel 进入 `OrchestratorV4`
5. 执行 SelfModel 能力评估
6. PlanAgent 生成子任务和 `depends_on` DAG
7. Dispatcher 并发调度，受最大并行与超时控制
8. Agent Cluster 并行执行
9. Fusion 汇聚结果，Critic 审校输出
10. 返回最终回答，并记录 trace / audit / metrics

### 33.2 流式问答事件补充

- `adaptive_profile`
- `dag_node_start` / `dag_node_complete`
- `agent_start` / `agent_progress` / `agent_complete`
- `conflict_summary`
- `reasoning_step`
- `answer_draft`
- `delta`
- `final_answer`
- `error`

### 33.3 失败与降级原则补充

- 非核心能力失败不阻塞主回答
- 流式失败可降级为同步请求
- `RAG` 无 chunk 时不泄露内部结构化 payload
- 身份类问题优先命中工作记忆缓存

---

## 34. API 全景补充

### 34.1 认证与会话

- `POST /auth/login`
- `POST /auth/register`
- `GET /auth/me`
- `GET/POST /conversations`
- `PATCH/DELETE /conversations/{id}`
- `POST /conversations/{id}/archive`
- `POST /conversations/{id}/branch`
- `GET /conversations/{id}/messages`
- `PATCH /messages/{message_id}`

### 34.2 文档、记忆、任务

- `GET/POST /documents`
- `GET/DELETE /documents/{id}`
- `POST /documents/search`
- `GET/POST /memories`
- `PATCH/DELETE /memories/{memory_id}`
- `GET/POST /memories/settings`
- `POST /tasks`
- `GET /tasks`
- `GET /tasks/{task_id}`
- `POST /tasks/{task_id}/pause|resume|cancel`
- `GET /tasks/notifications`
- `POST /tasks/notifications/read`
- `POST /tasks/events/trigger`

### 34.3 数据、连接器、技能

- `POST /databases`
- `GET /databases`
- `GET /databases/{id}`
- `DELETE /databases/{id}`
- `POST /databases/{id}/test-connection`
- `POST /databases/{id}/sync-schema`
- `GET /databases/{id}/schema`
- `POST /databases/{id}/query`
- `POST /databases/{id}/analysis`
- `POST /data/query`
- `GET /connectors`
- `POST /connectors/authorize`
- `POST /connectors/callback`
- `POST /connectors/resources`
- `POST /connectors/sync`
- `GET /skills`
- `POST /skills/install`
- `POST /skills/uninstall`
- `POST /skills/session/bind`
- `GET /skills/session/{session_id}`

---

## 35. 数据模型与 Redis 运行态补充

### 35.1 PostgreSQL 重点模型补充

- `reasoning_traces`：推理产物
- `document_chunks`：文档分块，支持 pgvector
- `task_definitions` / `task_runs` / `task_notifications`：主动任务系统
- `data_sources` / `data_source_schemas` / `data_query_logs`：数据源与查询审计
- `user_ui_settings`：UI 偏好同步
- `audit_logs`：审计日志

### 35.2 Redis 用途补充

- session / cache / memory / queue / rate limit / pubsub 分库隔离
- 支持 checkpoint、resume、stream 状态控制
- 支持 zero-trust 权限 token 与运行态缓存
- Agent Bus stream 模式支持 consumer-group、ack、pending reclaim、DLQ

---

## 36. 配置体系补充

### 36.1 LLM 三角色默认值说明

- `QUERY` 使用 `DEFAULT_LLM_QUERY_MODEL`
- `PLANNING` 使用 `DEFAULT_LLM_PLANING_MODEL`
- `COMPRESS` 使用 `DEFAULT_LLM_COMPRESS_MODEL`

### 36.2 关键环境变量类别

- 基础服务地址：`DATABASE_URL`、`REDIS_URL`
- 模型配置：`*_PROVIDER`、`*_MODEL`、`*_BASE_URL`、`*_API_KEY`
- 内核开关：`KERNEL_*`
- 数据查询：`TEXT2SQL_*`
- 可观测性：`OTEL_*`、`PROMETHEUS_*`、`JAEGER_*`
- 安全审计：`ZERO_TRUST_*`、`AUDIT_*`

---

## 37. 测试、CI 与门禁补充

### 37.1 CI 工作流

- `ci-fast.yml`：快速合同验证
- `ci.yml`：全量验证与 E2E

### 37.2 推荐门禁

- `verify_e2e.sh`
- `verify_agent_cluster.sh`
- `verify_agent_bus_e2e.sh`
- `verify_all_docker.sh`
- 迁移幂等性、RAG 输出合同、Text2SQL 只读约束、结构化 annotations 透传

---

## 38. 安全、治理与运维补充

### 38.1 安全

- Kernel 入口守卫防止绕过主链路调用模型
- SQL 仅允许只读操作并自动补 LIMIT
- 数据源密码使用 Fernet 加密
- 沙箱与文件系统隔离按 session 约束

### 38.2 运维

- `bash start.sh` / `bash stop.sh` / `bash restart.sh` 为统一入口
- 支持健康检查：`/health`、`/health/deps`、`/health/runtime`、`/ping`
- 支持日志查看、镜像预拉、迁移排障、文档上传排障、RAG 排障

---

## 39. 扩展路线与结论补充

### 39.1 近期扩展方向

- UI 偏好统一进全局状态
- Connectors 运营化页面增强
- 更多行为级契约测试
- TableRelationshipGraph 自动读取外键关系

### 39.2 中长期方向

- gVisor / Firecracker 强隔离
- 成本优化与 token budget 策略
- Tool 反馈闭环强化
- 记忆演化自动化
- NL2SQL 管线安全增强

### 39.3 结论

OpenTrace 当前已经形成“认知内核 + Agent 集群 + 数据认知 + 记忆演化 + 安全治理 + 可观测性”的完整闭环。`SERVICE.md` 作为总览文档，应持续与代码同步更新。
