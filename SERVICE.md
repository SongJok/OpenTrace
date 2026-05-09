# OpenTrace 完整项目文档

> 本文档是 OpenTrace 项目的唯一权威技术参考，涵盖架构设计、API 接口、配置说明、数据流程、部署方案和开发指南。
>
> 最后更新：2026-05-09

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
29. [协议层（Protocol Layer）](#29-协议层protocol-layer)
30. [V6 多轮对话增强（Multi-Turn Enhancement）](#30-v6-多轮对话增强multi-turn-enhancement)
  - [30.10 L3 Phase 1 — 结构化对话状态与引用消解](#3010-l3-phase-1-结构化对话状态与引用消解-conversationstate-resultref-referenceresolver)
31. [文件附件上传与上下文注入（Attachment Upload & Injection）](#31-文件附件上传与上下文注入attachment-upload--injection)
32. [NER PII 数据脱敏（NER-based PII Masking）](#32-ner-pii-数据脱敏ner-based-pii-masking)
33. [金丝雀测试与自动回滚（Canary Testing & Auto-Rollback）](#33-金丝雀测试与自动回滚canary-testing--auto-rollback)
34. [可解释审计 XAI（Explainable Audit XAI）](#34-可解释审计-xaiexplainable-audit-xai)

---

## 1. 项目概述

OpenTrace 是一个**认知内核驱动的 Agent 系统**，支持以下核心能力：

- **对话式问答**：同步和 SSE 流式两种模式
- **工具调用**：时间、天气、计算器、代码执行，支持前端卡片化渲染
- **RAG 文档问答**：基于 pgvector 的知识库检索
- **Text2SQL 数据查询**：自然语言转 SQL 并自动执行
- **联网搜索**：基于 Serper API 的实时 Web 检索
- **推理链可视化**：完整的推理步骤和 DAG 执行图展示
- **多层记忆**：工作记忆、语义记忆、情节记忆、程序记忆，已全量接入聊天管线
- **多轮对话记忆注入**：每轮对话前自动检索相关历史记忆，注入编排器上下文
- **V5 分层路由**：L0（零 LLM）+ L1（1.7B 单次分类）+ L2（全管线），30%+ 请求免 LLM
- **规则引擎**：YAML 驱动的产品查询与业务规则
- **多子问题编排**：语法 + LLM 双路径拆分，顺序融合

### 1.1 版本演进

| 阶段 | 版本 | 核心能力 |
|------|------|---------|
| V3 | legacy | 单线问答管线 |
| V4 | stable | Plan → Dispatcher → Agent Cluster → Fusion → Critic |
| V5 | current | V4 + L0 规则路由 + L1 小模型分类 + 语义缓存 |
| V6 | current | V5 + 多轮对话 6 大增强（追问/纠正/DST/压缩/记忆价值/分支）+ 文件附件上传与注入 |

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
│  ├── /api/v1/chat       — 聊天（同步/流式/追问/纠正/分支）      │
│  ├── /api/v1/chat/feedback — 记忆反馈（like/dislike）            │
│  ├── /api/v1/auth       — 认证（注册/登录/Token）                │
│  ├── /api/v1/documents  — 文档管理                               │
│  ├── /api/v1/databases  — 数据源管理                             │
│  ├── /api/v1/data       — 数据查询                               │
│  ├── /api/v1/conversations — 会话管理（含分支）                  │
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
│  ├── V6 Multi-Turn Enhancement                                    │
│  │   ├── ClarificationGate — 主动追问                            │
│  │   ├── RefinePlanner — 纠正增量重规划                          │
│  │   ├── DialogueStateTracker — 对话状态追踪                     │
│  │   ├── ContextComposer — 智能上下文压缩                        │
│  │   └── Active Memory Detection — 主动记忆写入                  │
│  ├── Intent Engine — 意图域分类                                  │
│  ├── Self Model — 自我能力评估                                    │
│  └── Orchestrator V4 — 主编排器                                   │
│      ├── Plan Agent — 任务分解 (DAG)                              │
│      ├── Dispatcher — 并发调度 + DAG checkpoint 复用             │
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
│       └── routers/             # API 路由模块（20 个）
│           ├── chat.py          # 聊天（同步/流式/重生成/图控制）
│           ├── auth.py          # 认证
│           ├── conversations.py # 会话管理
│           ├── documents.py     # 文档管理
│           ├── databases.py     # 数据源管理
│           ├── data.py          # 数据查询
│           ├── memories.py      # 记忆 CRUD
│           ├── skills.py        # 技能管理
│           ├── rules.py         # 规则管理（CRUD + YAML 生成 + 金丝雀回滚）
│           ├── xai.py           # [Phase 3] XAI 认知审计追踪 API
│           ├── tasks.py         # 任务管理
│           ├── health.py        # 健康检查
│           ├── cognitive.py     # 认知事件回放
│           ├── feedback.py      # 用户反馈
│           ├── audit.py         # 审计日志
│           ├── connectors.py    # 连接器
│           ├── sandbox.py       # 沙箱
│           ├── admin.py         # 管理接口
│           └── ui_settings.py   # 用户 UI 设置
├── kernel/                      # 认知内核（97 个文件）
│   ├── cognitive_kernel.py      # 唯一中枢入口（run/stream + ContextComposer + 主动记忆检测）
│   ├── orchestrator_v4.py       # V4 编排器（核心调度逻辑 + 追问/纠正/DST/分支集成）
│   ├── clarification_gate.py    # [V6] 主动追问门控（ClarificationGate + 启发式快速路径）
│   ├── refine_planner.py        # [V6] 纠正增量重规划（RefinePlanner + CorrectionIntent）
│   ├── dialogue_state_tracker.py # [V6] 对话状态追踪（DST + EntitySlot + 槽位解析）
│   ├── context_composer.py      # [V6] 智能上下文压缩（ContextComposer + ConversationSummary）
│   ├── protocol/                # 统一协议层（事件/MCP/治理）
│   │   ├── events.py            # 标准化事件协议 v2（Trace/Span 模型）
│   │   ├── mcp.py               # 模型上下文协议（Evidence/Hypothesis/Critique）
│   │   └── governance.py        # 可编程治理框架（Budget/QualityGate/GovernanceProfile）
│   ├── plan_agent.py            # 任务规划 Agent（单/多问题 + DST/clarify 上下文注入）
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
│   ├── conversation_state.py    # [L3 Phase 1] 结构化对话状态 + ConversationStateManager
│   ├── result_reference.py      # [L3 Phase 1] ResultRef 结构化引用 + 序列化
│   ├── reference_resolver.py    # [L3 Phase 1] 中文多轮指代消解 + 启发式+LLM 双向解析
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
├── agents/                      # 智能体集群（11 个文件）
│   ├── base.py                  # BaseAgent 抽象基类
│   ├── data_agent.py            # 数据查询 Agent（Text2SQL）
│   ├── rag_agent.py             # RAG 检索 Agent
│   ├── web_agent.py             # 联网搜索 Agent
│   ├── tool_agent.py            # 通用工具 Agent
│   ├── skills_agent.py          # 技能调用 Agent
│   ├── rule_engine_agent.py     # 规则引擎 Agent
│   ├── vision_agent.py          # [Phase 3] 视觉分析 Agent（图表/截图/照片解读）
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
├── memory/                      # 记忆系统（15 个文件）
│   ├── working_memory/          # 工作记忆（环形缓冲区 + summary_slot）
│   ├── semantic_memory/         # 语义记忆（向量检索）
│   ├── episodic_memory/         # 情节记忆（会话事件）
│   ├── procedural_memory/       # 程序记忆
│   ├── memory_router/           # 记忆路由（联邦检索 + 价值评分重排）
│   ├── evolution/               # 记忆演化（强化 + 演化 + 技能 + 自动衰减）
│   └── value_scorer.py          # [V6] 记忆价值评分（base + recency + feedback）
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
├── safety/                      # 安全防护（5 个模块）
│   ├── guardrails/              # 输入防护栏
│   ├── masking/                 # [Phase 3] NER PII 脱敏
│   │   └── ner_masker.py        # 中英文实体识别 + 可逆占位符替换
│   ├── canary/                  # [Phase 3] 金丝雀测试与自动回滚
│   │   └── canary_guard.py      # 版本指标追踪 + 衰退检测 + 自动回滚
│   └── xai/                     # [Phase 3] 可解释审计
│       └── cognitive_trace.py   # 认知管道全链路审计追踪
├── rules/                       # YAML 规则存储
├── services/                    # 业务服务
│   └── file_parser.py           # 文件解析服务（txt/pdf/docx/csv/xlsx/json/code/image）
├── skills/                      # 技能系统
│   └── marketplace/
│       ├── store.py             # 技能存储
│       └── manifest.py          # 技能清单
├── alembic/                     # 数据库迁移
│   ├── env.py                   # Alembic 环境
│   └── versions/                # 迁移脚本
├── deploy/docker/               # Docker 配置
├── scripts/                     # 运维脚本
├── tests/                       # 测试（102 个测试文件，759 个测试方法）
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
| `apiUploadAttachment(token, file, onProgress)` | 上传文件附件（XMLHttpRequest + 进度回调） |

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

### 5.6 消息渲染与 JSON 剥离管线（Card-Based Rendering）

前端强制要求**不展示裸 JSON 数据**——工具/Agent 结果必须以卡片化形式渲染。系统实现了三层防御管线：

**第一层：ChatInput normalizeAnswerContent**（`frontend/src/components/ChatInput.tsx`）

```ts
function normalizeAnswerContent(content: unknown): string {
  // 字符串 → 透传
  // 对象且含卡片标识（type/agent_type/tool_name）→ 序列化 JSON + 提取 inner text
  //   使 tryParseToolCard 可解析卡片元数据（解决 JSON 双层嵌套时卡片类型丢失）
  // 对象无卡片标识 → 提取 content/text/answer/summary/output/message 字段
  // 无匹配 → 返回 ''（绝不 fallback 到 JSON.stringify）
}
```

**注意**：`onFinalAnswer` 中已移除 `parseMarkdownWithHighlight` 调用。原因是后端的工具卡片注入使用 ` ```json {...} ``` ` 代码块格式，`parseMarkdownWithHighlight` 会将代码块替换为语法高亮 HTML，导致 `tryParseToolCard` 无法解析 JSON。保留原始内容可确保卡片正确渲染。

**流式渲染中的 JSON 剥离**：`StreamingMessage` 组件使用 `useMemo` 调用 `stripJsonBlocks()`，在流式传输期间实时剥离 JSON 块，防止裸 JSON 在流式显示时闪烁。

**第二层：chat.ts normalizeMessageText**（`frontend/src/store/chat.ts`）

```ts
function normalizeMessageText(input: unknown): string {
  // 对已知卡片类型（table/time/weather/sql/tool/turn/agent_result）返回 ''
  // 防止卡片化对象被当作 plain text 渲染
  // 不匹配任何字符串字段 → 返回 ''
}
```

**第三层：ChatMessage 渲染管线**（`frontend/src/components/ChatMessage.tsx`）

```
markdown 内容
  └── stripJsonBlocks() — 剥离嵌入的 JSON 块
      ├── _stripTrailingJsonArray() — 剥离末尾 JSON 数组
      ├── _stripInlineJsonObjects() — 剥离行内独立 JSON 对象/数组
      │   ├── 单行：以 { 或 [ 开头 → JSON.parse 成功 → 跳过
      │   └── 多行：均衡的大括号/中括号块 → JSON.parse 成功 → 跳过所有行
      └── 剩余内容 → MarkdownMessage 渲染

tryParseToolCard(content):
  ├── time card:   { current_time: ..., timezone: ... }
  ├── weather card: { location: ..., temperature: ..., description: ... }
  ├── table card:  { type: "table", columns: [...], rows: [...], row_count: ... }
  ├── data card:   { sql: ..., rows: [...], row_count: ... }
  │   └── CardShell(eyebrow="DATA QUERY") + SQL code block + DataTableChart
  └── agent card:  { agent_type: ... } | { tool_name: ... } | type="agent_result" | type="turn"
      └── CardShell(eyebrow=agent_type) + title + confidence + MarkdownMessage/content
```

**卡片类型覆盖**：

| 卡片类型 | 检测条件 | 渲染方式 |
|---------|---------|---------|
| `time` | `parsed.current_time` 存在 | CardShell + 时间/时区信息 |
| `weather` | `parsed.temperature` 存在 | CardShell + 天气信息 |
| `table` | `parsed.type === 'table'` | CardShell + DataTableChart |
| `data` | `parsed.sql` 非空 | CardShell + SQL pre/code + DataTableChart |
| `agent` | `parsed.agent_type` / `parsed.tool_name` / type=`turn`/`agent_result` | CardShell + 标题/meta + MarkdownMessage |

若 `tryParseToolCard` 返回 `null` 且 `stripJsonBlocks` 后无内容 → "未获取到有效回答"安全提示。

---

## 6. API 网关

**基础路径**：`/api/v1`
**端口**：`14100`
**框架**：FastAPI
**中间件**：CORS、Request ID、异常处理、内存事件订阅生命周期

### 6.1 路由注册

20 个路由模块注册在 `gateway/api_gateway/main.py`：

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
app.include_router(xai.router, prefix="/api/v1", tags=["xai"])
```

### 6.2 关键端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login` | 用户登录 |
| POST | `/chat` | 同步聊天（含 clarify_context, parent_message_id） |
| POST | `/chat/stream` | SSE 流式聊天 |
| POST | `/chat/feedback` | [V6] 记忆反馈（like/dislike/none） |
| POST | `/chat/attachments` | 上传文件附件（支持 txt/pdf/docx/csv/xlsx/json/code/image） |
| GET | `/chat/history/{session_id}` | 聊天历史 |
| POST | `/conversations` | 创建会话 |
| GET | `/conversations` | 列出会话 |
| DELETE | `/conversations/{id}` | 删除会话 |
| POST | `/conversations/{id}/archive` | 归档会话 |
| POST | `/conversations/{id}/branch` | 分支会话（含 parent_message_id） |
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
| POST | `/rules/{rule_id}/rollback` | [Phase 3] 规则金丝雀回滚 |
| GET | `/rules/yaml` | 规则 YAML 生成 |
| GET | `/xai/traces` | [Phase 3] 列出认知审计追踪 |
| GET | `/xai/traces/{trace_id}` | [Phase 3] 获取完整审计追踪 |
| GET | `/xai/sessions/{session_id}/trace` | [Phase 3] 获取会话最近追踪 |
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
Step 3: ContextComposer    — [V6] 长历史智能压缩（>2000 tokens 触发，摘要存入 WorkingMemory.summary_slot）
Step 4: Memory Injection   — EpisodicMemory + WorkingMemory + MemoryRouter 语义检索 + 价值评分
Step 5: intent_domain      — 意图域分类（仅 L2）
Step 6: SelfModel          — 自我能力评估（仅 L2）
Step 7: OrchestratorV4     — 全 V4+V6 管线（L2）
Step 8: Active Memory      — [V6] 检测"记住/我更喜欢"模式，写入 UserMemory 偏好表
Step 9: Semantic Cache Save — L2 成功后写入缓存
Step 10: Memory Save       — 异步保存对话记忆
```

### 7.3 入口方法

| 方法 | 签名 | 返回 |
|------|------|------|
| `run(request: KernelRequest)` | 同步执行 | `KernelResponse` |
| `stream(request: KernelRequest)` | SSE 流式 | `AsyncIterator[dict]` |

`KernelRequest` 新增 `trace_ctx: TraceContext | None` 字段，由 Gateway 在请求入口创建并传入，贯穿整个请求生命周期，实现全链路 Span 追踪。

### 7.3.1 协议层导出

```python
from kernel import (
    # 事件协议
    CognitiveEventV2, CognitiveEventTypeV2, SpanStage, TraceContext,
    # MCP 数据协议
    Evidence, Hypothesis, ActionPlan, Critique, AgentTrace, FailureTag,
    # 治理框架
    GovernanceProfile, Budget, QualityGate, QualityGateResult, check_quality_gate,
)
```

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

### 7.7 记忆上下文注入（Memory Context Injection）

**特性开关**：`KERNEL_MEMORY_CONTEXT_ENABLED=true`（默认启用）

在 V5 路由层之后、编排器调用之前，自动执行三层记忆检索并将结果注入编排器的上下文中。此前记忆系统组件（MemoryRouter、WorkingMemory、EpisodicMemory）均已实现但从未接入聊天管线，此功能将其全量激活。

**注入流程**：

```
Step 3: Memory Injection
  ├── EpisodicMemory.recall(last_n=20) → 近期关键事件（Q&A 对，可读文本）
  ├── WorkingMemory.get_or_create()    → 当前会话轮次累加
  └── MemoryRouter.retrieve(query, episodic_chunks, keyword_chunks, top_k=8)
      ├── 语义向量检索（InMemorySemanticStore）
      ├── 关键词匹配（用户偏好/事实）
      ├── 情节记忆片段
      └── 重排序 → Top-K 记忆片段
  → 注入 metadata["memory_context"] → OrchestratorV4 消费
```

**容错设计**：三层检索各自独立 try/except，EpisodicMemory 失败不阻断关键词/语义检索，Redis 不可用时降级到纯本地检索。

**编排器消费**（`orchestrator_v4.py`）：记忆片段以 `ToolResult(source="memory", confidence=score, source_priority=3)` 形式注入 FusionEngine，参与多源证据加权融合。`[历史记忆]` 标签在融合上下文中呈现，LLM 提示词要求自然融入回答。

**写入侧**（已有，不变）：Gateway 层 `_save_user_memory_from_turn()` 和 `EvolutionMemoryRouter` 订阅者在每轮对话后异步存储。

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
├── 0. Resume/Branch Check → [V6] 对话分支回溯，加载 checkpoint plan + results
├── 1. force_mode 检测 → 跳过规划
├── 2. Correction Detection → [V6] 启发式检测纠正意图（不对/错了/换成），RefinePlanner 增量重规划
├── 3. Dialogue State Tracking → [V6] 短查询（<30 字）槽位解析，指代消解
├── 4. PlanAgent → TaskPlan（DAG 子任务图 + clarify_context + DST 上下文）
├── 5. Memory Context 注入 → 记忆片段转为 ToolResult(memory) → FusionEngine
├── 5.5. Attachment Context 注入 → 附件转为 ToolResult(attachment) → FusionEngine + background_materials → LLM prompt
├── 6. Dispatcher → 并行调度 + [V6] DAG checkpoint 复用（分支场景跳过已执行子任务）
├── 7. DAG Scheduler → 依赖解析 + 拓扑排序
├── 8. 各 Agent 执行 → 返回候选结果
├── 9. FusionEngine → 加权融合多源证据（含 Memory/SQL/Document/Web/Tool）
├── 10. CriticEngine → 质量审校 + 重写/拒答
├── 11. ClarificationGate → [V6] 启发式检查（fusion_confidence < 0.6 + 短答案 + 信息不足），触发时返回追问
├── 12. Answer Generation → 结构化回答 + 引文 + 注释 + Card JSON
└── 13. Tool Card Injection → 时间/天气 payload JSON 注入
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
- **[V6] DAG checkpoint 复用**：`dispatch(plan, previous_results=...)` — 对话分支时按 `(agent_type, query)` 匹配跳过已执行子任务，仅调度新增子任务，~40% 延迟降低

### 9.6 Fusion + Critic

- **FusionEngine**（`kernel/fusion_engine/engine.py`）：加权融合多 Agent 结果
- **SequenceFusionEngine**（`kernel/fusion_engine/sequence_fusion.py`）：多子问题顺序融合，含 `_generate_knowledge_answer()` 事实问题降级
- **CriticEngine**（`kernel/critic_engine/`）：质量审校 + 重写建议

### 9.6.1 工具卡片注入（Tool Card Injection）

时间/天气工具返回结构化 JSON（`{"type":"time","time":"...","timestamp":...}`），但此前 `ToolAgent` 将其转为纯文本，前端 `tryParseToolCard()` 无法解析。修复后，编排器在最终答案组装阶段检测 time/weather 类型的 Agent 结果，将其 metadata 中的 payload JSON 以 markdown code block 形式注入答案：

```
```json
{"type":"time","time":"2026-04-30 17:30:00","timestamp":1746005400,"timezone":"Asia/Shanghai"}
```

现在是北京时间17点30分。
```

前端 `tryParseToolCard()` 扫描 code fence 或 inline JSON，命中后渲染 `<TimeCard>` 或 `<WeatherCard>` 组件。JSON 注入仅针对 `type` 为 `time` 或 `weather` 的 payload，不影响计算器、Web 搜索等其他工具。

### 9.6.2 回答风格优化（Response Tone）

针对回复生硬的问题，在以下方面做了优化：

**提示词升温**（3 处）：
- `_llm_fallback_answer`：温度 0.2→0.35，system prompt 强调"热情、可靠、有温度""亲切口语化""温和语气词"
- `_llm_grounded_answer`：温度 0.15→0.3，system prompt 从"文档问答助手"扩展为"知识问答助手"，强调"亲切、靠谱、不端着""愉快的对话而不是干巴巴的报告"
- `_grounded_answer_style`：4 个分支全部加入口语化引导，单证据分支强调"实用的下一步建议""真心帮他解决问题"

**附件作为候选认知材料**（1 处）：
- 用户上传的文件在 `process()` 中转换为 `ToolResult(source="attachment", confidence=0.95, source_priority=2)` 注入 FusionEngine
- FusionEngine 权重 `"attachment": 0.85`（高于 web_search 的 0.6，低于 llmwiki 的 1.05）
- `[用户上传文件]` 标签在融合上下文中呈现
- **背景材料注入**：附件内容作为 `background_materials` 注入 `_llm_grounded_answer()`，置于用户问题之前（`--- 背景材料开始 ---`），指导 LLM 以文件内容为知识背景作答
- 全路径覆盖：`process()` → `_llm_grounded_answer()`、`_process_multi_question()` → `SequenceFusionEngine`、`_llm_fallback_answer()` 均支持背景材料注入

**Web/Tool 结果走 LLM**（1 处）：
- 此前 Web 搜索结果和丰富工具结果通过 annotator 直出文本，绕过 LLM，导致回复干瘪
- 现在检测到 web_search 或内容长度 >80 字符的 tool 结果时，自动路由到 `_llm_grounded_answer()` 生成自然语言回答

### 9.7 Span 链式事件发射

编排器在 `process()` 中通过 `TraceContext.start_span()` 为每个阶段生成 span ID，并通过 `CognitiveEventBus` 发射带 `span_id`/`parent_span_id` 的事件：

| 阶段 | Span ID | parent_span_id | 事件类型 |
|------|---------|----------------|---------|
| Planning | `planning_span` | `root_span` | PLANNING |
| Dispatch | `dispatch_span` | `root_span` | EXECUTION |
| Fusion | `fusion_span` | `root_span` | FUSION |
| Critic | `critic_span` | `root_span` | CRITIC |
| Final | `final_span` | `root_span` | LEARNING |

完整的 span 链为：`Gateway → Planning → Dispatch → Agent Execution → Fusion → Critic → Final`

---

## 10. 智能体集群（Agent Cluster）

### 10.1 BaseAgent

**文件**：`agents/base.py`

所有 Agent 继承 `BaseAgent`，需实现 `execute(task: SubTask) -> AgentResult`。

**AgentResult 标准化输出**（v2）：

```python
class AgentResult(BaseModel):
    task_id: str
    agent_type: str
    status: str           # success | error | timeout
    content: str          # 人类可读的文本结果
    confidence: float     # 置信度 0-1
    metadata: dict
    error: str | None
    evidence: list[dict]  # [新增] Evidence 标准格式的证据列表
    agent_trace: dict | None  # [新增] Agent 执行全链路记录
```

`evidence` 列表中每个元素包含：`source`, `source_type`, `payload`, `credibility_score`, `relevance_score`, `acquisition_cost`, `provenance`。

### 10.2 Agent 列表

| Agent | 文件 | 说明 | 启停开关 |
|-------|------|------|---------|
| DataAgent | `data_agent.py` | Text2SQL 数据查询 | `KERNEL_AGENT_DATA_ENABLED` |
| RAGAgent | `rag_agent.py` | 文档检索（pgvector） | `KERNEL_AGENT_RAG_ENABLED` |
| WebAgent | `web_agent.py` | 联网搜索（Serper API） | `KERNEL_AGENT_WEB_ENABLED` |
| ToolAgent | `tool_agent.py` | 通用工具（时间/天气/计算），含卡片 JSON payload 输出 | `KERNEL_AGENT_TOOL_ENABLED` |
| SkillsAgent | `skills_agent.py` | 技能调用 | — |
| RuleEngineAgent | `rule_engine_agent.py` | YAML 规则引擎 + 金丝雀指标记录 | — |
| VisionAgent | `vision_agent.py` | 视觉分析（图表/截图/照片解读）+ Redis 缓存降级 | — |

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

**多模态支持**：`LLMMessage.content` 字段类型为 `str | list[dict]`，`list` 格式用于图像等多模态输入（如 `[{"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}}, {"type": "text", "text": "..."}]`），`openai_adapter._to_oai()` 透传 list content。用于文件附件中的图像解析（图片 → base64 → qwen3.6-plus vision → 文字描述）。

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

四层记忆 + 路由 + 演化 + 价值评分闭环，已全量接入聊天管线（2026-05-03）。

### 12.1 记忆层级

| 层 | 模块 | 文件 | 状态 | 说明 |
|----|------|------|------|------|
| L1 工作记忆 | `working_memory` | `memory/working_memory/` | ✅ 已激活 | 环形缓冲区（最大 32 轮对话）+ 身份缓存，每轮自动累加 |
| L2 语义记忆 | `semantic_memory` | `memory/semantic_memory/` | ✅ 已激活 | 向量检索（InMemorySemanticStore），MemoryRouter 调用 |
| L3 情节记忆 | `episodic_memory` | `memory/episodic_memory/` | ✅ 已激活 | Redis 持久化会话事件序列，recall(last_n=20) 注入上下文 |
| L4 程序记忆 | `procedural_memory` | `memory/procedural_memory/` | 待接入 | 成功的流程和工具链 |
| 路由 | `memory_router` | `memory/memory_router/` | ✅ 已激活 | 联邦检索 + 重排序 + [V6] 价值评分重排 |
| 演化 | `evolution` | `memory/evolution/` | ✅ 已激活 | EvolutionMemoryRouter：强化 + 演化 + 压缩 + 技能 + [V6] 自动衰减 |
| 价值评分 | `value_scorer` | `memory/value_scorer.py` | ✅ [V6] | base + recency + feedback 三元加权，Redis feedback streak |

### 12.2 查询管线

```
MemoryRouter.retrieve(query, episodic_chunks, keyword_chunks, top_k=8)
  ├── 语义向量检索 → InMemorySemanticStore.search(query)
  ├── 情节记忆片段 → EpisodicMemory.recall(last_n=20)
  ├── 关键词匹配    → UserMemory SQL 偏好/事实
  └── 重排序合并    → 加权 Top-K 记忆片段
```

### 12.3 价值评分与反馈闭环 [V6]

**文件**：`memory/value_scorer.py`

每段记忆在检索后计算最终价值分：

```
final_score = 0.5 × base_score + 0.3 × recency_score + 0.2 × feedback_score
recency_score = exp(-0.01 × turn_gap)     # 半衰期 ~70 轮
feedback_score = like: +0.3 / dislike: -0.5 / 无反馈: 0
```

**自动衰减**：连续 N 轮无反馈 → score × 0.1（`kernel_memory_auto_decay_threshold=3`）

**Feedback API**：`POST /api/v1/chat/feedback` 接收 `{session_id, chunk_id, feedback_type: like|dislike|none, score?}`，更新 EvolutionMemoryRouter 价值评分和 Redis streak counter。

Redis 键格式：
- `opentrace:memory:feedback:{chunk_id}:streak` — 连续无反馈计数（INCR，30 天 TTL）
- `opentrace:memory:feedback:{chunk_id}:type` — 最新反馈类型（like/dislike，30 天 TTL）

### 12.4 写入管线（已有）

- Gateway 层 `_save_user_memory_from_turn()` — 每轮 Q&A 异步写入
- `EvolutionMemoryRouter` 订阅者 — 技能检索 + 演化记录

### 12.5 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `KERNEL_MEMORY_CONTEXT_ENABLED` | `true` | 记忆上下文注入主开关 |
| `KERNEL_MEMORY_VALUE_SCORING_ENABLED` | `true` | [V6] 记忆价值评分开关 |
| `KERNEL_MEMORY_FEEDBACK_LIKE_BONUS` | `0.3` | [V6] 点赞加分 |
| `KERNEL_MEMORY_FEEDBACK_DISLIKE_PENALTY` | `-0.5` | [V6] 踩罚分 |
| `KERNEL_MEMORY_AUTO_DECAY_THRESHOLD` | `3` | [V6] 无反馈衰减阈值 |
| `KERNEL_V5_ROUTING_ENABLED` | `true` | V5 路由（Memory Injection 在此之后执行） |

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
| `AppSettings` | 应用 + 内核 + V5 + V6 | 75+ |

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

### 16.1 零信任与输入防护

- **零信任风险评估**（`infra/security/zero_trust.py`）：输入风险评分
- **输入防护栏**（`safety/guardrails/`）：PII/SQL 注入/有害内容检测
- **SQL 只读校验**：所有生成的 SQL 强制只读
- **JWT 认证**：所有 API 端点需 Bearer Token
- **CORS**：已配置跨域支持

### 16.2 NER PII 数据脱敏 [Phase 3]

**文件**：`safety/masking/ner_masker.py`（~154 行）

在所有查询进入 LLM 管线之前，自动检测并替换敏感实体为类型化占位符，LLM 回答后再逆向还原。无需外部 NLP 依赖，使用精选正则模式覆盖中英文 9 种实体类型。

**实体类型**：

| 类型 | 示例 | 占位符 |
|------|------|--------|
| `EMAIL` | `user@example.com` | `{MASK_EMAIL_0}` |
| `PHONE_CN` | `13800138000` | `{MASK_PHONE_CN_0}` |
| `PHONE_INTL` | `+86 10 1234 5678` | `{MASK_PHONE_INTL_0}` |
| `CREDIT_CARD` | `1234-5678-9012-3456` | `{MASK_CREDIT_CARD_0}` |
| `ID_CN` | `110101199001011234` | `{MASK_ID_CN_0}` |
| `IP_ADDRESS` | `192.168.1.1` | `{MASK_IP_ADDRESS_0}` |
| `PERSON_CN` | `张三先生`、`李丽老师` | `{MASK_PERSON_CN_0}` |
| `LOCATION_CN` | `北京市`、`浦东新区` | `{MASK_LOCATION_CN_0}` |
| `ORG_CN` | `阿里巴巴集团`、`人民医院` | `{MASK_ORG_CN_0}` |

**数据模型**：

```python
@dataclass
class MaskResult:
    masked: str               # 脱敏后的文本
    mapping: dict[str, str]   # 占位符 → 原始值映射
    pii_detected: bool        # 是否检测到 PII

class NERMasker:
    def mask_input(text: str) -> MaskResult    # 替换 PII → 占位符
    def unmask_output(text: str, mapping: dict) -> str  # 还原占位符 → 原始值
    def scan_pii(text: str) -> dict[str, list[str]]     # 审计扫描（不替换）
```

**编排器集成**（`kernel/orchestrator_v4.py`）：在 `process()` 入口处调用 `get_ner_masker().mask_input(req.query)`，脱敏后的查询用于后续所有 LLM 调用，最终答案通过 `unmask_output()` 还原。

### 16.3 金丝雀测试与自动回滚 [Phase 3]

**文件**：`safety/canary/canary_guard.py`（~327 行）

为规则引擎提供版本金丝雀发布能力：每个规则版本可独立追踪错误率/延迟指标，当金丝雀版本相对基线出现衰退时自动回滚。

**核心组件**：

```python
@dataclass
class RuleVersionMetrics:
    rule_id: str; version: str
    error_count: int; success_count: int
    total_latency_ms: float; sample_count: int
    # 属性: error_rate, avg_latency_ms

@dataclass
class CanaryStatus:
    rule_id: str; canary_version: str; baseline_version: str
    canary_error_rate: float; canary_avg_latency_ms: float
    baseline_error_rate: float; baseline_avg_latency_ms: float
    degraded: bool; auto_rolled_back: bool; rollback_reason: str

class CanaryGuard:
    def record(rule_id, version, success, latency_ms)      # 记录执行指标
    def check_health(rule_id) -> CanaryStatus | None        # 健康检查（冷启动保护）
    def rollback(rule_id, reason="") -> bool                # 回滚到稳定版本
    def auto_rollback_if_degraded(rule_id) -> CanaryStatus   # 检测 + 自动回滚
    def sweep_all() -> list[CanaryStatus]                   # 全量规则健康巡扫
```

**衰退检测逻辑**：
- 错误率 > `kernel_canary_error_rate_threshold`（默认 10%）→ 触发
- 平均延迟 > 基线 `kernel_canary_latency_multiplier` 倍（默认 2×）→ 触发
- 最小样本数保护：`kernel_canary_min_samples`（默认 100），冷启动期间不做判断

**自动回滚机制**：
1. 修改 `_meta.yml` 将金丝雀版本 percentage 置 0、status 置 `rolled_back`
2. 基线版本 percentage 恢复 100%
3. `grayscale.enabled` 设为 false
4. 记录回滚事件（含 reason/timestamp）至 `_rollback_history`

**编排器集成**（`agents/rule_engine_agent.py`）：`execute()` 循环中对每个规则执行结果调用 `guard.record(rid, version, success, latency_ms)`。

**API 端点**：`POST /api/v1/rules/{rule_id}/rollback` 支持手动回滚。

### 16.4 可解释审计 XAI [Phase 3]

**文件**：`safety/xai/cognitive_trace.py`（~317 行）

为每次查询构建结构化的认知管道审计追踪，记录 **什么发生了**（数据）和 **为什么会这样决定**（人类可读的推理说明）。追踪覆盖完整的 PLAN → DISPATCH → AGENT → FUSION → CRITIC → REWRITE → FINAL 管道。

**核心组件**：

```python
@dataclass
class TraceEvent:
    timestamp: float; stage: str; event_type: str
    data: dict; reasoning: str  # 人类可读的 WHY

@dataclass
class CognitiveTrace:
    trace_id: str; session_id: str; query: str
    events: list[TraceEvent]; summary: dict; metadata: dict

class CognitiveTracer:
    def start_trace(session_id, query, user_id="") -> str  # 返回 trace_id
    def finish_trace(trace_id, summary=None)
    def record_decision(trace_id, stage, event_type, data={}, reasoning="")
    def record_agent_execution(trace_id, agent_type, status, latency_ms, ...)
    def record_fusion(trace_id, source_count, merged_length, strategy="")
    def record_critic(trace_id, issues_found, corrections=[], llm_feedback="")
    def record_rewrite(trace_id, iteration, reason="", improvement="")
    def record_final(trace_id, answer_length, confidence, total_agents, total_latency_ms)
    def get_trace(trace_id) -> dict | None
    def list_traces(session_id=None, limit=50) -> list[dict]
    def get_recent_trace_for_session(session_id) -> dict | None
```

**管道阶段覆盖**：

| 阶段 | 记录方法 | 记录内容 |
|------|---------|---------|
| DST | `record_decision` | 对话状态追踪，查询消解 |
| PLAN | `record_decision` | 任务规划（子任务数/Agent 类型） |
| AGENT | `record_agent_execution` | 每个 Agent 的执行结果/耗时/置信度 |
| FUSION | `record_fusion` | 多源证据融合（来源数/策略/上下文长度） |
| CRITIC | `record_critic` | 质量审校（问题数/修正建议） |
| REWRITE | `record_rewrite` | 每次重写迭代 |
| FINAL | `record_final` | 最终答案（长度/置信度/总耗时） |

**容量控制**：
- 单次追踪最大 500 个事件（`MAX_TRACE_EVENTS`）
- 内存中最多保留 200 条追踪（`MAX_STORED_TRACES`，FIFO 淘汰）

**编排器集成**（`kernel/orchestrator_v4.py`）：`process()` 中在 NER 脱敏后立即 `start_trace()`，每个管道阶段调用相应记录方法，最终 `finish_trace()`。

**API 端点**（3 个）：
- `GET /api/v1/xai/traces` — 列出追踪（可选 `session_id` 过滤，`limit` 1-100）
- `GET /api/v1/xai/traces/{trace_id}` — 获取完整追踪（含所有事件和管道阶段摘要）
- `GET /api/v1/xai/sessions/{session_id}/trace` — 获取会话最近追踪

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

### 18.2 规则版本化与灰度发布 [Phase 3]

每个规则目录包含 `_meta.yml` 元信息文件，支持多版本管理和灰度发布：

```yaml
# rules/{rule_id}/_meta.yml 示例
rule_id: product_catalog
active_version: v1
versions:
  v1:
    file: rule_v1.yml
    status: baseline
    percentage: 90
  v2:
    file: rule_v2.yml
    status: canary
    percentage: 10
grayscale:
  enabled: true
  hash_key: user_id    # 用户 ID 哈希分桶
```

**版本解析**（`_resolve_version()`）：通过 `hash(user_id) % 100` 确定性分桶，`hash_value < canary_percentage` 的请求路由到金丝雀版本，其余路由到基线版本。同一用户始终落在同一桶中（粘性）。

### 18.3 金丝雀指标追踪

**文件**：`agents/rule_engine_agent.py`

```python
# execute() 循环中
t0 = time.monotonic()
# ... 规则执行 ...
elapsed_ms = (time.monotonic() - t0) * 1000
guard.record(rid, version, success=ok, latency_ms=elapsed_ms)
```

每次规则执行后记录成功/失败和延迟至 `CanaryGuard`，用于衰退检测和自动回滚判断。

### 18.4 规则管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rules` | 列出规则 |
| POST | `/rules` | 创建规则 |
| PUT | `/rules/{id}` | 更新规则 |
| DELETE | `/rules/{id}` | 删除规则 |
| POST | `/rules/{rule_id}/rollback` | [Phase 3] 规则版本回滚（手动或自动触发） |
| GET | `/rules/yaml` | 生成 YAML |

**回滚端点**：接受 `{"reason": "..."}` 请求体，调用 `CanaryGuard.rollback()` 将金丝雀版本 percentage 归零、基线版本恢复 100%、关闭灰度。返回 `{"message": "...", "rule_id": "..."}`。

### 18.5 前端规则页面

**文件**：`frontend/src/pages/RulesPage.tsx`

- 在线 CRUD 操作
- YAML 预览与生成
- 规则启用/禁用控制

---

## 19. 消息总线（Message Bus）

### 19.1 认知事件总线

**文件**：`infra/message_bus/cognitive_event_bus.py`

- 统一事件模型：ROUTING、PLANNING、EXECUTION、EVIDENCE、FUSION、CRITIC、FEEDBACK、LEARNING
- 事件携带统一元信息：`trace_id`, `span_id`, `parent_span_id`（[新增] Span 链支持）, `session_id`, `request_id`, `actor`, `timestamp`
- `schema_version` 已升级至 2
- 新增 `emit_routing()` 和 `emit_fusion()` 发射方法
- EventStore 的 `list_by_trace()` 通过 SMEMBERS + XRANGE 实现真正的 trace index 检索
- 所有 emit 方法接受 `span_id` 和 `parent_span_id` 参数，用于构建因果链

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
| `ConversationState` | [L3 Phase 1] 结构化对话状态（FK→chat_sessions.id ON DELETE CASCADE，含 `active_attachment_ids`） |
| `Attachment` | [L3 Phase 2] 文件附件持久化（FK→chat_sessions.id + users.id，含 content_hash / image_base64 / duplicate_of） |
| `TraceLog` | 请求追踪日志（含 [V6] `parent_message_id` 分支字段） |
| `UserMemory` | 用户记忆（含 [V6] `score` 价值分数字段） |
| `Feedback` | 用户反馈（like/dislike/none） |
| 更多 | 文档、数据源、任务、审计等 |

**ConversationState 模型字段**：`id`, `session_id`（FK, unique, ondelete="CASCADE"）, `active_topic`, `active_intent`, `active_domain`, `active_entities`（JSON）, `active_constraints`（JSON）, `active_mode`, `active_data_source_id`, `active_document_ids`（JSON）, `active_attachment_ids`（JSON list, [L3 Phase 2]）, `last_user_goal`, `last_assistant_summary`, `last_plan`（JSON）, `last_results`（JSON）, `pending_clarification`（JSON）, `state_version`（int）, `created_at`, `updated_at`。ChatSession 反向关系：`conversation_state`（uselist=False, passive_deletes=True）和 `attachments`（cascade="all, delete-orphan"）。

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
KERNEL_MEMORY_CONTEXT_ENABLED=true
```

**内核 V4/V6**：
```
KERNEL_ORCHESTRATOR_VERSION=v4
KERNEL_AGENT_TIMEOUT_SEC=25
KERNEL_AGENT_MAX_PARALLEL=5
KERNEL_AGENT_MAX_RETRY=1
KERNEL_ADAPTIVE_MODE_ENABLED=true
KERNEL_ANSWER_DRAFT_CONFIDENCE_THRESHOLD=0.75
KERNEL_ANSWER_DRAFT_MAX_CHARS=220
KERNEL_MEMORY_CONTEXT_ENABLED=true
RAG_MIN_SCORE=0.25
```

**V6 多轮对话增强**：
```
# Feature ⑤ ClarificationGate — 主动追问
KERNEL_CLARIFICATION_GATE_ENABLED=true
KERNEL_CLARIFICATION_CONFIDENCE_THRESHOLD=0.6

# Feature ④ Error Correction — 错误纠正
KERNEL_CORRECTION_DETECTION_ENABLED=true
KERNEL_REFINE_REPLAN_ENABLED=true

# Feature ② Dialogue State Tracking — 对话状态追踪
KERNEL_DST_ENABLED=true
KERNEL_DST_QUERY_LENGTH_THRESHOLD=30

# Feature ① Context Compression — 上下文压缩
KERNEL_CONTEXT_COMPOSER_ENABLED=true
KERNEL_COMPRESS_TRIGGER_TOKENS=3000
KERNEL_COMPRESS_KEEP_RECENT_TURNS=5

# Feature ③ Memory Value Feedback — 记忆价值闭环
KERNEL_MEMORY_VALUE_SCORING_ENABLED=true
KERNEL_MEMORY_FEEDBACK_LIKE_BONUS=0.3
KERNEL_MEMORY_FEEDBACK_DISLIKE_PENALTY=-0.5
KERNEL_MEMORY_AUTO_DECAY_THRESHOLD=3

# Feature ⑥ Conversation Branching — 对话分支
KERNEL_CONVERSATION_BRANCHING_ENABLED=true

# [L3 Phase 1] ConversationState — 结构化对话状态
KERNEL_CONVERSATION_STATE_ENABLED=true
```

**文件附件上传**：
```
ATTACHMENT_UPLOAD_ENABLED=true
ATTACHMENT_MAX_SIZE_MB=20
ATTACHMENT_STORAGE_PATH=/tmp/opentrace_attachments
ATTACHMENT_MAX_CHARS=4000
MULTIMODAL_ATTACHMENT_ENABLED=true
```

**Vision LLM（视觉分析）**：
```
DEFAULT_LLM_VISION_MODEL=qwen3.6-vl-plus
DEFAULT_LLM_VISION_PROVIDER=阿里巴巴Qwen(DashScope)
```

**规则版本化与灰度发布**：
```
KERNEL_RULE_GRAYSCALE_ENABLED=true
KERNEL_RULE_GRAYSCALE_DEFAULT_PERCENTAGE=100
```

**NER PII 数据脱敏 [Phase 3]**：
```
KERNEL_NER_MASKING_ENABLED=true
KERNEL_NER_MASKING_ENTITY_TYPES=EMAIL,PHONE_CN,PHONE_INTL,CREDIT_CARD,ID_CN,IP_ADDRESS,PERSON_CN,LOCATION_CN,ORG_CN
```

**金丝雀测试与自动回滚 [Phase 3]**：
```
KERNEL_CANARY_AUTO_ROLLBACK_ENABLED=true
KERNEL_CANARY_ERROR_RATE_THRESHOLD=0.10
KERNEL_CANARY_LATENCY_MULTIPLIER=2.0
KERNEL_CANARY_MIN_SAMPLES=100
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
| `pytest` | 运行全部 759 个测试 |
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

- **测试文件**：102 个（不含 `__init__.py`）
- **测试方法**：759 个
- **框架**：pytest + unittest.TestCase
- **风格**：合约测试（Contract Tests），验证代码结构和关键路径存在

### 25.2 主要测试模块

| 测试文件 | 测试数 | 覆盖范围 |
|---------|--------|---------|
| `test_v5_routing_contract.py` | 50 | V5 L0/L1/缓存/复杂度/导出/降级/.env |
| `test_data_cognition_pipeline.py` | 36 | Text2SQL 完整管线 |
| `test_canary_rollback_contract.py` | 34 | [Phase 3] 金丝雀测试：指标/衰退检测/自动回滚/API/sweep |
| `test_xai_cognitive_trace_contract.py` | 34 | [Phase 3] XAI 认知追踪：事件/生命周期/录制/检索/编排器集成/API |
| `test_multi_question_orchestration_contract.py` | 33 | 多子问题编排全链路 + background_materials 注入 |
| `test_attachment_api_kernel_contract.py` | 32 | 附件上传 API + 认知内核注入 + 全路径背景材料 |
| `test_ner_masking_contract.py` | 28 | [Phase 3] NER 脱敏：9 种实体/可逆占位符/中英文/边界条件 |
| `test_force_mode_routing.py` | 20 | 强制模式/斜杠命令路由 |
| `test_memory_context_injection.py` | 18 | 记忆上下文注入全链路 |
| `test_kernel_agent_loop.py` | 15 | 内核 Agent 循环 |
| `test_attachment_file_parser_contract.py` | 14 | 文件解析服务全类型覆盖 |
| `test_rag_agent_contract.py` | 14 | RAG 检索 Agent |
| `test_rule_engine_agent_contract.py` | 13 | 规则引擎 Agent |
| `test_streaming_ttft_contract.py` | 10 | 流式输出 + TTFT |
| `test_skills_api_contract.py` | 9 | 技能 API |
| `test_analytics_plugins.py` | 7 | 分析插件 |
| `test_tool_card_injection.py` | 6 | 工具卡片 JSON 注入 |
| `test_conversation_state_contract.py` | 17 | [L3 Phase 1] ConversationState：创建/加载/更新/合并/压缩/边界值/并发 |
| `test_reference_resolution_contract.py` | 20 | [L3 Phase 1] 中文指代消解：刚才/第二个/换成/不要/那个+10+ 场景 |
| `test_multiturn_data_query_contract.py` | 10 | [L3 Phase 1] Data Agent 多轮追问端到端 |
| `test_multiturn_rag_contract.py` | 8 | [L3 Phase 1] RAG 文档 QA 多轮追问端到端 |
| `test_multiturn_correction_contract.py` | 8 | [L3 Phase 1] 纠正重规划全链路 |

其余 80 个测试文件覆盖 orchestrator、fusion、critic、bus、memory、database、adapters 等。

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

## 29. 协议层（Protocol Layer）

**文件**：`kernel/protocol/`（3 个模块）

协议层是 Tier 1 重构的核心成果，为 OpenTrace 建立了**统一事件协议 + MCP 数据协议 + 可编程治理框架**三层底座，作为系统所有组件通信的唯一"语言"。

### 29.1 设计动机

重构前，Kernel、Orchestrator、Agent、Gateway、前端各自使用不同的数据格式通信，存在以下问题：
- **协议不统一**：事件模型不一致，Agent 输出格式各异
- **不可观测**：缺少 `span_id`/`parent_span_id`，无法构建因果链
- **无标准化数据结构**：Evidence、Hypothesis、Critique 等核心概念散落在代码各处
- **缺少治理框架**：预算、质量门禁、路由策略分散

协议层解决了以上所有问题，且**向后兼容**（所有新字段提供默认值，零破坏性变更）。

### 29.2 标准化事件协议 (events.py)

**Trace/Span 模型**：

```python
class SpanStage(str, Enum):
    GATEWAY = "gateway"           # API 网关层
    ROUTING_L0 = "routing_l0"     # L0 规则路由
    ROUTING_L1 = "routing_l1"     # L1 Tiny Router
    PLANNING = "planning"         # 任务规划
    DISPATCH = "dispatch"         # 任务分发
    AGENT_EXECUTION = "agent_execution"  # Agent 执行
    FUSION = "fusion"             # 证据融合
    CRITIC = "critic"             # 质量审校
    DRAFT = "draft"               # 答案起草
    REWRITE = "rewrite"           # 答案重写
    FINAL = "final"               # 最终输出

@dataclass(slots=True)
class TraceContext:
    trace_id: str              # = request_id
    request_id: str
    session_id: str | None
    user_id: str | None
    root_span_id: str          # UUID4 hex[:16]，根 span

    def start_span(self, stage: SpanStage, parent_span_id: str | None = None) -> str:
        """生成格式为 {root}:{counter:04d} 的子 span ID"""

class CognitiveEventTypeV2(str, Enum):
    ROUTING = "routing"        # [新增]
    PLANNING = "planning"
    EXECUTION = "execution"
    EVIDENCE = "evidence"
    FUSION = "fusion"          # [新增]
    CRITIC = "critic"
    FEEDBACK = "feedback"
    LEARNING = "learning"

@dataclass(slots=True)
class CognitiveEventV2:
    event_type: CognitiveEventTypeV2
    trace_id: str
    span_id: str              # [新增] 当前 span ID
    stage: SpanStage          # [新增] 阶段标签
    parent_span_id: str | None  # [新增] 父 span ID，构建因果链
    # ... 其他标准字段
```

**工厂函数**：

```python
def trace_context_for_request(
    request_id: str,
    session_id: str = "",
    user_id: str = "",
) -> TraceContext:
    """为每个请求创建 TraceContext，trace_id = request_id"""
```

### 29.3 MCP 数据协议 (mcp.py)

定义了认知内核与 Agent 集群交互的标准化数据结构：

**核心数据结构**：

| 结构 | 说明 | 关键字段 |
|------|------|---------|
| `CognitiveContext` | 请求级上下文 | `query`, `history`, `budget`, `risk_threshold`, `governance_profile` |
| `Evidence` | Agent 输出的标准格式 | `source`, `source_type`, `payload`, `credibility_score`, `relevance_score`, `acquisition_cost`, `provenance` |
| `Hypothesis` | Planner 中间结论 | `statement`, `supporting_evidence_ids`, `confidence`, `needs_more_evidence` |
| `ActionPlan` | 待执行指令集 | `actions: list[Action]`, `merge_strategy`, `max_parallel`, `should_follow_up`, `should_refuse` |
| `Action` | 单个执行指令 | `agent_type`, `query`, `priority`, `depends_on`, `budget` |
| `Critique` | 审校器结构化批评 | `verdict` (pass/rewrite/refuse/follow_up), `failure_tags: list[FailureTag]`, `suggested_fix`, `severity` |
| `AgentTrace` | 执行全链路记录 | `problem_identification`, `metric_mapping`, `filters`, `join_paths`, `sql_generated`, `sql_rewrites`, `validation_errors`, `execution_result`, `confidence` |

**FailureTag 枚举（11 种结构化失败标签）**：

```python
class FailureTag(str, Enum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EVIDENCE_CONFLICT = "evidence_conflict"
    REASONING_GAP = "reasoning_gap"
    WRONG_TOOL = "wrong_tool"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    HALLUCINATION_RISK = "hallucination_risk"
    ANSWER_INCOMPLETE = "answer_incomplete"
    SQL_SEMANTIC_DRIFT = "sql_semantic_drift"
    RAG_IRRELEVANT = "rag_irrelevant"
    WEB_RETRIEVAL_FAILED = "web_retrieval_failed"
    SHOULD_REFUSE = "should_refuse"
```

### 29.4 可编程治理框架 (governance.py)

**GovernanceProfile** — YAML/JSON 驱动的请求全生命周期策略：

```python
@dataclass
class GovernanceProfile:
    profile_id: str           # default | speed | quality | safe
    budget: Budget            # 预算限制
    quality_gates: QualityGate  # 质量门禁
    routing_strategy: RoutingStrategy  # 路由策略
    safety: SafetyPolicy      # 安全策略
    metadata: dict
```

**Budget** — 运行时资源追踪：

| 限制项 | 默认值 (default) | 说明 |
|--------|-----------------|------|
| `max_tokens` | 8000 | Token 上限 |
| `max_latency_ms` | 5000 | 延迟上限 |
| `max_tool_calls` | 3 | 工具调用上限 |
| `max_agent_calls` | 5 | Agent 调用上限 |
| `max_retries` | 2 | 最大重试次数 |

Budget 提供运行时追踪方法：`record_tokens()`, `record_tool_call()`, `record_agent_call()`，以及 `any_exhausted` 属性检查配额。

**QualityGate** — 质量门禁检查：

| 门禁 | 默认值 | 说明 |
|------|--------|------|
| `critic_threshold` | `"high"` | 审校严格度 (low/medium/high) |
| `require_source_attribution` | `True` | 要求来源标注 |
| `min_confidence` | `0.6` | 最低置信度 |
| `max_hallucination_risk` | `0.3` | 最大幻觉风险 |
| `answer_draft_max_chars` | `220` | 草稿最大字符数 |

`check_quality_gate(critique, gate) -> QualityGateResult` 执行质量门禁检查。

**4 种内置 Profile**：

| Profile | 特点 | 适用场景 |
|---------|------|---------|
| `default` | 8000 tokens / 5000ms | 通用查询 |
| `speed` | 3000 tokens / 2000ms | 低延迟优先 |
| `quality` | 16000 tokens / 15000ms | 高质量优先 |
| `safe` | 4000 tokens / 3000ms, strict | 安全优先 |

```python
from kernel.protocol.governance import load_governance_profile
profile = load_governance_profile("quality")  # 或 "speed", "safe"
```

### 29.5 Agent 输出标准化

所有 6 个 Agent 的 `execute()` 方法在返回前填充标准化输出：

| Agent | Evidence 来源 | AgentTrace |
|-------|-------------|------------|
| **DataAgent** | 查询结果 + SQL 链路 | 完整 SQL 生成全链路 |
| **RAGAgent** | 每个检索块（credibility/relevance/evidence_tier） | — |
| **WebAgent** | 每个搜索结果项 | — |
| **ToolAgent** | 解析后的工具输出 | — |
| **SkillsAgent** | 每个匹配技能结果 | — |
| **RuleEngineAgent** | 每个规则匹配结果 | — |

每个 Evidence 字典格式：
```python
{
    "source": "data_agent",
    "source_type": "sql_query",
    "payload": {"sql": "...", "rows": [...]},
    "credibility_score": 0.9,
    "relevance_score": 0.85,
    "acquisition_cost": 0.0,  # latency_seconds
    "provenance": "database://source_id/table_name",
}
```

### 29.6 全链路 Span 追踪

每个请求从 Gateway 到 Final Answer 形成完整的 Span 因果链：

```
Gateway (gateway_span)
  │  parent_span_id: root_span_id
  ▼
Kernel / Orchestrator
  ├── Planning (planning_span) ─── parent: root_span_id
  ├── Dispatch (dispatch_span) ─── parent: root_span_id
  ├── Agent Execution (agent spans) ─── parent: dispatch_span
  ├── Fusion (fusion_span) ─── parent: root_span_id
  ├── Critic (critic_span) ─── parent: root_span_id
  └── Final (final_span) ─── parent: root_span_id
```

**Gateway 层**（`chat.py`）：创建 TraceContext 实例，发射 8 类事件（`chat.request.received` → `reasoning_step` → `final_answer` → `stream_cancelled`/`stream_error` → `kernel_run_error`/`fallback_used` → `kernel_run_completed`），每个事件携带 `span_id` 和 `parent_span_id`。

**Orchestrator 层**（`orchestrator_v4.py`）：在 `process()` / `stream()` 的 6 个阶段（Planning, Dispatch, Fusion, Critic, Draft, Final）发射链式事件。

**Span ID 格式**：`{root_span_id[:16]}:{counter:04d}`，例如 `a1b2c3d4e5f6g7h8:0001`

### 29.7 前端协议对齐

前端类型定义（`frontend/src/api/client.ts`）已扩展：

```typescript
type ReasoningStage =
  'ROUTE' | 'REASON' | 'DECIDE' | 'EXECUTE' | 'OBSERVE' |
  'REFLECT' | 'PLAN' | 'ACT' | 'DRAFT' | 'CRITIC' |
  'REWRITE' | 'FINAL' | 'FUSION' | 'EVIDENCE'
```

`ReasoningChain.tsx` 新增 stage 图标：ROUTE 🚦, FUSION 🔄, EVIDENCE 📋

### 29.8 向后兼容保证

- 所有旧版 `CognitiveEvent` 新增字段 (`span_id`, `parent_span_id`, `stage`) 均提供空字符串/None 默认值
- `AgentResult.evidence` 和 `AgentResult.agent_trace` 默认空列表/None
- `schema_version` 机制区分 v1/v2 事件
- 现有测试全部通过，零破坏性变更

---

## 30. V6 多轮对话增强（Multi-Turn Enhancement）

V6 在 V5 基础上为多轮对话引入了 6 大增强功能，解决指代消解、上下文压缩、错误纠正、主动追问、记忆价值评估和对话分支回溯等核心痛点。

### 30.1 功能总览

| # | 功能 | 优先级 | 核心文件 | 解决的问题 |
|---|------|--------|---------|-----------|
| ⑤ | ClarificationGate | P0 | `kernel/clarification_gate.py` | 信息不足时主动生成追问 |
| ④ | Error Correction | P0 | `kernel/refine_planner.py` | 用户纠正后增量重规划，避免全量重跑 |
| ② | Dialogue State Tracking | P1 | `kernel/dialogue_state_tracker.py` | 指代消解（"那华北区呢？"） |
| ① | ContextComposer | P1 | `kernel/context_composer.py` | 长历史智能压缩，节省 token |
| ③ | Memory Value Scoring | P2 | `memory/value_scorer.py` | 记忆分值评估 + 自动衰减 + 反馈闭环 |
| ⑥ | Conversation Branching | P2 | `kernel/dispatcher.py` + `chat.py` | 对话分支回溯，复用 checkpoint |

### 30.2 Feature ⑤ — ClarificationGate（主动追问）

**核心逻辑**：

```
ClarificationGate.check(fusion_confidence, answer, query)
  ├── 启发式快速路径（无 LLM）：
  │   ├── fusion_confidence < 0.6 → 触发
  │   ├── answer < 50 字符 → 触发
  │   └── 答案含"信息不足"/"无法确定" → 触发
  └── 仅当启发式触发时 → MiddleShort 8B 生成追问
      └── 返回 ClarificationGateResult(needs_clarification=True, questions=[...])
```

**Orchestrator 集成**：Critic 之后、Tool Card Injection 之前，触发时提前返回 `route="clarification_needed"`，metadata 含 `clarification_question`。

**前端交互**：收到 `needs_clarification` SSE 事件 → 渲染追问卡片 → 用户回答后带 `clarify_context` 和 `clarify_question_id` 重新请求 → PlanAgent 检测 `clarify_context` 后将其注入规划 prompt。

**API 字段**（`ChatRequest`）：
- `clarify_context: Optional[str]` — 用户对追问的回答
- `clarify_question_id: Optional[str]` — 被回答的追问 ID

### 30.3 Feature ④ — Error Correction & Incremental Re-planning（错误纠正）

**启发式门控**：仅当 `query < 100 字符` 且含以下关键词时才触发 LLM 分类：
`不对`, `不是`, `错了`, `重新`, `纠正`, `改成`, `换成`, `应该是`

**核心流程**：

```
1. looks_like_correction(query) → True
2. TinyRouter._CLASSIFY_PROMPT 返回 reply_type: "correction"
3. RefinePlanner.detect_correction(query, previous_plan) → CorrectionIntent
4. RefinePlanner.refine_plan(correction, plan, results, original_query) → RefinedPlan
5. Dispatcher 仅执行 replaced_indices 对应的新 SubTask
6. 合并 reused_results + new_results → 最终答案
```

**效果**：延迟降低 ~40%（仅重新执行 1 个 Agent 而非全部）。

**RefinedPlan 数据结构**：

```python
@dataclass
class RefinedPlan:
    plan: TaskPlan              # 增量后的新计划
    replaced_indices: list[int] # 被替换的 SubTask 索引
    reused_results: dict[int, AgentResult]  # 复用的已有结果
```

### 30.4 Feature ② — DialogueStateTracker（对话状态追踪）

**触发条件**：`len(query) < 30` AND `not _has_explicit_entities(query)`

**核心流程**：

```
DialogueStateTracker.track(query, previous_plan, previous_results, history)
  ├── 检查显式实体（华东、销量、订单等）→ 有则跳过
  ├── 使用 MiddleShort 8B 做结构化槽位解析
  │   输入：当前 query + 上一轮 TaskPlan + AgentResult
  │   输出：DialogueSlotState
  └── PlanAgent 检测到 referenced_previous_result=True
      └── 优先沿用上一轮的 Agent 类型和数据源参数
```

**DialogueSlotState 数据结构**：

```python
@dataclass
class EntitySlot:
    slot_name: str        # 例如 "region", "metric"
    value: str            # 例如 "华北区", "销量"
    confidence: float
    source: str           # "explicit" | "resolved" | "inferred"

@dataclass
class DialogueSlotState:
    active_domain: str
    entity_slots: list[EntitySlot]
    referenced_previous_result: bool
    referenced_agent_type: str   # "data" | "rag" | "web" | ""
    resolved_query: str          # 补全后的完整查询
```

### 30.5 Feature ① — ContextComposer（智能上下文压缩）

**触发条件**：估算 token 数超过 `kernel_compress_trigger_tokens`（默认 2000）

**Token 估算**：中文 ~2 chars/token，英文 ~4 chars/token

**核心流程**：

```
ContextComposer.compose(history, current_query, session_id)
  ├── _estimate_tokens(history) > 2000 → 触发压缩
  ├── 调用 COMPRESS 模型（qwen3.5-27b, LLMRole.COMPRESS）
  │   生成 ConversationSummary：
  │   ├── 用户身份/偏好
  │   ├── 已确认事实
  │   ├── 未完成动作
  │   └── 最近 kernel_compress_keep_recent_turns 轮原文
  ├── 存入 WorkingMemory.summary_slot（带版本号）
  └── 返回 ComposedContext(compressed=True, summary=..., recent_turns=[...])
```

**Cognitive Kernel 集成**：`run()` 和 `stream()` 两条路径都在调用 orchestrator 前执行压缩，并将 `memory_injection_query` 设为 `current_query + summary[:200]`，提升记忆检索精度。

### 30.6 Feature ③ — Memory Value Feedback Loop（记忆价值闭环）

**评分公式**：

```
final_score = 0.5 × base_score + 0.3 × recency_score + 0.2 × feedback_score
recency_score = exp(-0.01 × turn_gap)     # 半衰期 ~70 轮
feedback_score = like: +0.3 / dislike: -0.5 / 无反馈: 0
```

**调用链**：

```
MemoryRouter.retrieve()
  └── rerank → MemoryScoreComponents.apply()
      └── re-sort by final_score

EvolutionMemoryRouter.retrieve()
  └── auto-decay: no_feedback_streak >= threshold → score *= 0.1

POST /api/v1/chat/feedback
  └── EvolutionMemoryRouter.record_feedback(chunk_id, feedback_type)
      ├── like/dislike → set Redis feedback:type, reset streak
      └── none → INCR Redis feedback:streak
```

**主动记忆检测**（Cognitive Kernel）：

检测查询中的"记住，我更喜欢..."等模式，自动写入 `UserMemory`（`kind="preference"`, `score=0.7`）：

```python
_ACTIVE_MEMORY_PATTERNS = [
    "记住", "记下", "记录下来", "别忘了", "提醒我",
    "我更喜欢", "我喜欢", "我偏好", "我习惯", "我常用",
    "保存下来", "存下来", "记录下来",
]
```

### 30.7 Feature ⑥ — Conversation Branching（对话分支回溯）

**核心流程**：

```
POST /chat (parent_message_id="msg_xxx")
  ├── _load_history_before_message(db, session_id, parent_message_id)
  │   └── 回滚历史到 parent_message_id 之前
  ├── _load_branch_checkpoint(db, session_id, parent_message_id)
  │   └── 从 TraceLog.execution_graph_json 提取 plan + agent_results
  ├── metadata["resume_mode"] = True
  ├── metadata["branch_checkpoint"] = {plan, agent_results}
  └── OrchestratorV4.process()
      ├── resume_mode 检测 → 加载 checkpoint_plan / checkpoint_results
      └── Dispatcher.dispatch(plan, previous_results=checkpoint_results)
          ├── 按 (agent_type, query) 匹配已有结果 → 跳过执行
          └── 仅调度新 Subtask → 合并结果
```

**数据库字段**：

```python
# TraceLog 模型
parent_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
```

**_save_trace 签名更新**：

```python
async def _save_trace(
    session_id, query, response, latency_ms,
    decision_type="kernel", validation_score=1.0,
    reasoning_steps=None, execution_graph=None,
    parent_message_id=None,  # [V6] 新增
)
```

### 30.8 架构原则

1. **懒加载模式**：所有新组件通过 `_get_xxx()` 在首次访问时初始化，不影响零 LLM 的 L0 路径
2. **启发式门控**：Feature ④ 和 ② 使用关键词/长度检查做 LLM 调用前置过滤，减少无谓开销
3. **向后兼容**：所有新 metadata 字段通过 `.get()` 安全访问，不存在时不改变原有行为
4. **两路对齐**：`run()` 和 `stream()` 两条路径同步接入所有 V6 特性

### 30.9 验证方案

| Feature | 验证方式 | 预期结果 |
|---------|---------|---------|
| ⑤ | 发送"查一下数据"（无数据源） | 收到 clarification 追问 → 回答后正确路由到 DataAgent |
| ④ | 先问"华东区销量"，再说"不对，我要的是利润" | 检测为 correction → 仅重新执行 data 子任务 |
| ② | 先问"华东区销量"，再问"那华北区呢？" | 复用 DataAgent + 数据源，自动补全为"华北区销量是多少" |
| ① | 连续 15+ 轮对话 | 触发压缩 → 摘要存入 WorkingMemory.summary_slot |
| ③ | 点赞/踩记忆片段 | final_score 对应调整 → 连续无反馈自动衰减 |
| ⑥ | 点击 AI 回答的"分支"按钮 | 回滚历史 → 加载 checkpoint → 复用已有结果继续对话 |

### 30.10 L3 Phase 1 — 结构化对话状态与引用消解（ConversationState, ResultRef, ReferenceResolver）

L3 Phase 1 将多轮对话从 **L1/L2（prompt 内拼接 history 数组）** 升级到 **L3（持久化结构化对话状态 + 结果引用 + 智能指代消解）**。核心设计：每轮对话后，编排器从 Plan + Agent 结果中派生 `state_patch`，由 API 层持久化到 `conversation_states` 表；下一轮开始时加载状态，若用户查询短/模糊则触发 `ReferenceResolver` 解析中文指代（"刚才那个"/"第二个"/"换成…"）。

#### 30.10.1 数据流

```
Chat Request
  └── chat.py: 通过 ConversationStateManager.get_or_create() 加载 ConversationState
      └── KernelRequest(conversation_state=...)
          └── OrchestratorV4.process()
              ├── ReferenceResolver.resolve(query, state, result_refs)
              │   └── 返回 ResolutionResult（resolved_refs, turn_type, resolved_query, ...）
              ├── PlanAgent.generate_plan(resolved_query, ...)
              ├── Agent Cluster 执行 → AgentResult.metadata.result_refs
              ├── Fusion Engine 收集 all_result_refs
              ├── Critic Engine 审校
              └── derive state_patch (从 plan + results + DST)
          └── KernelResponse(state_patch=state_patch, result_refs=result_refs)
      └── chat.py: ConversationStateManager.apply_patch(state, state_patch)
      └── ChatResponse(result_refs=result_refs, state_version=state.state_version)
```

#### 30.10.2 ConversationState（`kernel/conversation_state.py`）

持久化到 `conversation_states` 表的每会话结构化状态。

**数据模型**：

```python
@dataclass
class EntityRef:
    name: str                 # 例如 "华东区"
    entity_type: str          # "region" | "metric" | "date" | "product" ...
    value: str                # 例如 "华东区"
    confidence: float = 1.0

@dataclass
class ConversationState:
    session_id: str
    active_topic: str = ""            # 当前话题
    active_intent: str = ""           # DST 意图（如 "data_query"）
    active_domain: str = "general_qa"
    active_entities: list = []        # list[EntityRef]
    active_constraints: dict = {}     # {"date_range": "昨天", "region": "华北"}
    active_mode: str = ""             # "data_query" | "rag" | ...
    active_data_source_id: str = ""
    active_document_ids: list = []
    last_user_goal: str = ""          # 上一轮用户目标原文
    last_assistant_summary: str = ""  # 上一轮回答摘要
    last_plan: dict | None = None     # 上一轮 TaskPlan（序列化）
    last_results: list = []           # list[ResultRef]（最多保留 10 条）
    pending_clarification: dict = {}
    state_version: int = 0
```

**ConversationStateManager**：

| 方法 | 说明 |
|------|------|
| `async load(session_id)` | 从 DB 加载状态 |
| `async save(state)` | 写入 DB（insert/update） |
| `apply_patch(state, patch: dict)` | 合并 patch 到状态，`state_version += 1`（in-place 修改） |
| `compact(state)` | 修剪旧数据：last_results 保留最新 10 条，summaries 截断到 2000 字符 |
| `async get_or_create(session_id)` | 优先加载，不存在时创建默认状态 |

#### 30.10.3 ResultRef（`kernel/result_reference.py`）

Agent 执行结果的结构化引用——替代之前不可查询的原始 AgentResult 对象。

**数据模型**：

```python
@dataclass
class ResultRef:
    ref_id: str                # 全局唯一（uuid4）
    type: str                  # sql | table | doc_chunk | citation | tool | skill | sub_question | graph_node | web_source
    title: str                 # 简短描述（如"华东区销量 SQL"）
    summary: str = ""          # 单行摘要
    payload: dict = {}         # 携带数据 {sql:, table_name:, rows: [...], ...}
    source_agent: str = ""     # "data_agent" | "rag_agent" | ...
    message_id: str = ""       # 产生该引用的消息 ID
    created_at: str = ""       # ISO 时间戳
```

**序列化工具**：`serialize_refs()`, `deserialize_refs()`, `refs_from_agent_result()`, `collect_refs_from_results()`

**Agent 与 result_refs 类型映射**：

| Agent | ref type | 说明 |
|-------|---------|------|
| `data_agent.py` | `sql`, `table` | SQL 语句 + 查询结果表格 |
| `rag_agent.py` | `doc_chunk`, `citation` | 文档片段 + 出处 |
| `web_agent.py` | `web_source` | 网页来源 |
| `skills_agent.py` | `skill` | 技能执行结果 |
| `vision_agent.py` | `vision` | 图表/图片分析结果 |
| `rule_engine_agent.py` | `rule` | 规则引擎匹配结果 |

#### 30.10.4 ReferenceResolver（`kernel/reference_resolver.py`）

中文多轮对话的指代消解和追问意图识别。先用启发式规则匹配，匹配不明确时回退到 LLM。

**5 阶段启发式流水线**：

```
Stage 1 — 纠正检测（Correction）
  keywords: 不对|不是|错了|重新|纠正|改成|换成|应该是|不要|去掉|去掉那个
  → turn_type = "correction", resolved_refs = 上一轮被纠正的结果

Stage 2 — 序号索引（Index）
  pattern: 第(一|二|三|四|1|2|3)个 / 第N个
  → turn_type = "reference", 按索引匹配上一轮的 result_refs

Stage 3 — 类型匹配（Type）
  type hints: SQL|查询|表格(/data), 文档|这个文档(/rag/doc), 搜索/搜索结果(/web), 工具(/tool)
  → turn_type = "reference", 按类型匹配上一轮的 result_refs

Stage 4 — 通用引用（Generic）
  keywords: 刚才|刚才那个|上一个|上一步|这个|那个
  → turn_type = "continuation", 使用上一轮的首个 result_ref

Stage 5 — 新话题（New Topic）
  default: 未匹配任何模式
  → turn_type = "new_topic", resolved_refs = []
```

**ResolutionResult 数据结构**：

```python
@dataclass
class ResolutionResult:
    resolved_refs: list           # list[ResultRef] — 匹配到的结果引用
    turn_type: str                # "continuation" | "correction" | "new_topic" | "reference" | "clarification_answer"
    confidence: float             # 0.0–1.0
    resolved_query: str           # 补全后的完整查询（替换了"那个"等模糊指代）
    corrected_constraints: dict   # 纠正类型时的新约束（替换或删除）
    suggested_domain: str         # 建议的 Agent 类型
    suggested_agent: str          # 建议的 Agent 名称
```

#### 30.10.5 Orchestrator 集成

`OrchestratorV4.process()` 方法在所有 5 条返回路径均返回 `state_patch` + `result_refs`：

| 返回路径 | state_patch | result_refs |
|---------|------------|-------------|
| 身份快捷路径 | `state_patch` | `[]` |
| 多子问题 | `multi_q_state_patch` | `multi_q_result_refs` |
| Force-mode 缺少数据源 | `state_patch` | `[]` |
| Force-mode 回退 | `fallback_state_patch` | `fallback_result_refs` |
| Agent 集群主路径 | `state_patch` | `all_turn_result_refs`（fusion 收集） |

`stream()` 方法在 `final_data` 中发送 `"state_patch"` 和 `"result_refs"` 字段。

**state_patch 推导逻辑**（在 OrchestratorV4 返回前执行）：

```python
state_patch = {
    "active_domain": (dst_resolved_query 或 "general_qa"),
    "active_topic": dst_detected_topic,
    "active_mode": planned_task_types,
    "last_user_goal": query,
    "last_plan": task_plan.to_dict(),
    "last_results": [serialize_refs(all_turn_result_refs)],
}
# 如果纠正检测到 constraints，同时更新 active_constraints
```

#### 30.10.6 API 层集成（chat.py）

**同步路径**：
1. `ConversationStateManager.get_or_create(session_id)` 加载/初始化状态
2. 传入 `KernelRequest(conversation_state=conversation_state)` 替代散落在 `metadata["previous_plan"]` / `metadata["previous_results"]` 中的 flat dict
3. Orchestrator 返回后：`ConversationStateManager.save(conversation_state)` fire-and-forget 持久化
4. `ChatResponse` 携带 `result_refs` 和 `state_version` 字段

**流式路径**：同样加载状态、传入 KernelRequest；在 SSE final_answer 事件中发送 `state_patch` 和 `result_refs`；异常时 `logger.warning("Failed to persist ConversationState in stream path")` 安全降级。

**ChatRequest 扩展字段**：
- `reference_id: Optional[str]` — 用户明确引用的结果 ID
- `reference_type: Optional[str]` — 引用类型（sql/table/doc_chunk/...）
- `state_version: Optional[int]` — 客户端上次已知的 state_version（乐观并发参考）

**ChatResponse 扩展字段**：
- `result_refs: list` — 本轮的 ResultRef 列表（前端可展示为"结果引用"卡片）
- `state_version: int` — 新 state_version（每次 apply_patch 后 +1）

#### 30.10.7 数据库迁移

**文件**：`alembic/versions/20260508_add_conversation_state.py`

- `down_revision = "20260423_add_chunk_strategy"`
- 创建 `conversation_states` 表（20 列）
- `session_id` FK → `chat_sessions.id` ON DELETE CASCADE, UNIQUE 约束
- 遵循幂等模式（`_table_exists()` / `_index_exists()` 守卫）

#### 30.10.8 验证方案

| 场景 | 验证方法 | 预期结果 |
|------|---------|---------|
| 追踪引用 | 先问"查一下华东区销量"→再问"刚才的 SQL 是什么" | ReferenceResolver 识别"刚才"→返回 sql ResultRef |
| 序号引用 | 多子问题后说"第二个结果再详细一点" | 按索引匹配第二个 ResultRef |
| 类型引用 | "那个表格再展开一下" | 按 type=table 匹配上一轮结果 |
| 纠正 | "查一下销量"→"换成昨天" | 检测为 correction → 重建 plan 并使用新约束 |
| 新话题 | 先问数据查询→再问"今天天气怎么样" | Turn type = new_topic，不加载状态 |
| 状态持久化 | 同一 session 发送 3 轮 | 每轮 state_version 递增，最后验证 DB 记录 |
| 流式对齐 | SSE 多轮对话 | final_answer 事件包含 state_patch + result_refs |

#### 30.10.9 合约测试

新增 5 个合约测试模块，63 个测试方法：

| 测试文件 | 测试数 | 覆盖范围 |
|---------|--------|---------|
| `test_conversation_state_contract.py` | 17 | State 创建/加载/更新/合并/压缩/边界值/并发 |
| `test_reference_resolution_contract.py` | 20 | 中文指代：刚才/第二个/换成/那个/不要/10+ 场景 |
| `test_multiturn_data_query_contract.py` | 10 | Data Agent MR Follow-Up E2E |
| `test_multiturn_rag_contract.py` | 8 | RAG 文档 QA MR Follow-Up E2E |
| `test_multiturn_correction_contract.py` | 8 | 纠正重规划全链路 |

**运行**：
```bash
pytest tests/test_conversation_state_contract.py \
       tests/test_reference_resolution_contract.py \
       tests/test_multiturn_data_query_contract.py \
       tests/test_multiturn_rag_contract.py \
       tests/test_multiturn_correction_contract.py -v
```

---

## 31. 文件附件上传与上下文注入（Attachment Upload & Injection）

文件附件上传功能允许用户上传文件（代码、文档、表格、图片等），系统自动解析内容并作为「候选认知材料」注入 LLM 提示词，使 AI 能基于文件内容回答用户问题。架构上严格遵循认知内核唯一中枢原则：**所有输出必须由认知内核生成，附件只是候选认知材料**。

### 31.1 整体数据流

```
用户选择文件 → 前端预览 → POST /chat/attachments
  → 文件扩展名校验（_ALLOWED_EXTENSIONS 白名单）
  → SHA-256 content_hash 计算 & 同会话重复检测
  → services/file_parser.parse_attachment_content()
  → PostgreSQL 持久化（attachments 表） + Redis 缓存（12h TTL）
  → 更新 ConversationState.active_attachment_ids
  → 返回 AttachmentUploadResponse（attachment_id + content_summary + content_hash + is_duplicate）
用户输入文字（不指定 attachment_ids 时自动加载当前会话所有活跃附件）
  → POST /chat → Gateway 从 PostgreSQL 批量加载附件内容（Redis fallback）
  → 注入 KernelRequest.metadata["attachment_contexts"]
  → OrchestratorV4.process()
      ├── ToolResult(source="attachment", confidence=0.95, source_priority=2) → FusionEngine
      └── background_materials → _llm_grounded_answer() / SequenceFusionEngine / _llm_fallback_answer()
  → LLM 生成融入文件内容的回答
```

### 31.2 API 端点

**文件**：`gateway/api_gateway/routers/chat.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat/attachments` | 上传文件附件（multipart/form-data），持久化到 PostgreSQL + Redis |
| GET | `/chat/attachments/{session_id}` | 列出会话所有活跃附件 |
| DELETE | `/chat/attachments/{attachment_id}` | 软删除附件（标记 status="deleted" + 清除 Redis） |

**POST 请求参数**：
- `file: UploadFile` — 文件（最大 20MB）
- `session_id: str` — 所属会话 ID（Form 字段）
- `message_id: Optional[str]` — 关联消息 ID（Form 字段，可选）

**POST 响应体**（`AttachmentUploadResponse`）：
```python
class AttachmentUploadResponse(BaseModel):
    attachment_id: str       # UUID，用于后续 chat 请求引用
    content_summary: str     # 解析后的内容摘要（前 200 字符）
    content_hash: str        # SHA-256 哈希，用于去重
    is_duplicate: bool       # 同会话是否已存在相同内容的附件
```

**GET 响应体**（`AttachmentListResponse`）：
```python
class AttachmentListResponse(BaseModel):
    session_id: str
    attachments: list[AttachmentInfo]  # 含 filename, file_size, mime_type, file_extension, content_summary, status, message_id, created_at
    total: int
```

**ChatRequest 扩展字段**：
```python
attachment_ids: list[str] | None = None  # 关联的附件 ID 列表（为空时自动加载会话所有活跃附件）
```

**MIME 类型校验**：上传时比对真实 MIME 类型与文件扩展名，不匹配时通过 `_warn_on_mime_mismatch()` 记录 warning 日志（仅警告，不阻断）。

### 31.3 允许的文件类型

**文件**：`gateway/api_gateway/routers/chat.py`（`_ALLOWED_EXTENSIONS`）

| 类别 | 扩展名 | 解析器 |
|------|--------|--------|
| 纯文本 | `.txt`, `.md`, `.rst`, `.log` | `_parse_txt()` |
| 代码 | `.py`, `.js`, `.ts`, `.go`, `.rust`, `.java`, `.c`, `.cpp`, `.sql`, `.sh`, `.yaml`, `.html`, `.css`, `.vue`, `.svelte` | `_parse_code()` |
| PDF | `.pdf` | `_parse_pdf()` (PyMuPDF → pdfplumber) |
| Word | `.docx` | `_parse_docx()` (python-docx) |
| CSV/TSV | `.csv`, `.tsv` | `_parse_csv()` (pandas → markdown table) |
| Excel | `.xlsx` | `_parse_xlsx()` (pandas) |
| JSON | `.json` | `_parse_json_file()` |
| 图片 | `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp` | `_parse_image()` (multimodal LLM) |

### 31.4 文件解析服务

**文件**：`services/file_parser.py`

核心入口函数：
```python
async def parse_attachment_content(file_path: str, mime_type: str = "") -> str
```

**解析器类型**：

| 解析器 | 说明 | 截断策略 |
|--------|------|---------|
| `_parse_txt()` | 直接读取文本内容，含 frontmatter 格式优化 | 总字符数 ≤ `MAX_ATTACHMENT_CONTENT_CHARS` (4000) |
| `_parse_code()` | 代码文件，包裹在 ```` ```py ```` markdown fence 中 | 行数 ≤ `MAX_CODE_LINES` (500) |
| `_parse_pdf()` | PyMuPDF (fitz) 提取文本，失败降级到 pdfplumber | 同上 4000 字符 |
| `_parse_docx()` | python-docx 提取段落文本 | 同上 |
| `_parse_csv()` | pandas 读取 → markdown 表格 | 行数 ≤ `MAX_CSV_ROWS` (50) |
| `_parse_xlsx()` | pandas 读取所有 sheet → 多段输出 | 每 sheet 前 30 行 |
| `_parse_json_file()` | `json.load()` → `indent=2` 格式化 | 同上 4000 字符 |
| `_parse_image()` | base64 编码 → qwen3.6-plus vision → 文字描述 | `max_tokens=1024` |

**输出格式**：所有解析结果以 `[用户上传文件: filename.ext]` 为前缀。

**图片解析**（多模态）：
- 将图片编码为 base64 data URI
- 构建多模态 `LLMMessage`（`content` 为 `list[dict]`，含 `image_url` 和 `text` 两部分）
- 调用 ModelGateway（QUERY 角色，temperature=0.2，max_tokens=1024）
- 模型输出图片中的文字、表格、图表描述等信息
- `multimodal_attachment_enabled=false` 时返回"多模态解析未启用"提示

### 31.5 认知内核注入

**文件**：`kernel/orchestrator_v4.py`

#### ToolResult 注入

在 `process()` 的 Agent 执行之后、FusionEngine 调用之前：

```python
attachment_contexts = req.metadata.get("attachment_contexts", [])
if attachment_contexts:
    for ac in attachment_contexts:
        if isinstance(ac, dict) and ac.get("content"):
            tool_results.append(ToolResult(
                source="attachment",
                data=str(ac["content"])[:4000],
                confidence=0.95,
                source_priority=2,
            ))
```

附件 ToolResult 参与 FusionEngine 加权融合，与其他 Agent 结果（RAG、Web、Tool 等）平等竞争。

#### 背景材料注入（background_materials）

附件内容同时注入为**背景材料**，在 `_llm_grounded_answer()` 中置于用户问题之前：

```
用户上传了以下文件作为背景材料，请将材料内容作为回答的知识背景：

--- 背景材料开始 ---
[文件内容，最多 6000 字符]
--- 背景材料结束 ---

用户问题：xxx

检索证据：
[FusionEngine 融合结果]

输出要求：
...
```

**全路径覆盖**（3 条答案生成路径均已支持）：

| 路径 | 注入方式 | 截断 |
|------|---------|------|
| `process()` → `_llm_grounded_answer()` | `background_materials` 参数 → 直接拼入 LLM 提示词 | 6000 字符 |
| `_process_multi_question()` → `SequenceFusionEngine` | `SequenceFusionInput.background_materials` → `_generate_answer_for_question()` / `_generate_knowledge_answer()` | 4000 字符 |
| `_llm_fallback_answer()` | 从 `req.metadata` 提取 → 拼入最终用户消息 | 6000 字符 |

#### FusionEngine 配置

**文件**：`kernel/fusion_engine/engine.py`

```python
_weights = {
    ...
    "attachment": 0.85,  # 高权重：用户上传内容可信度高
    ...
}

_source_labels = {
    ...
    "attachment": "用户上传文件",
    ...
}
```

权重设计：`llmwiki(1.05) > sql(1.0) > weather/time(0.9) > attachment(0.85) > document(0.72) > web_search/search(0.6) > memory(0.55)`

### 31.6 前端附件 UI

**文件**：`frontend/src/components/ChatInput.tsx`

**交互流程**：
1. 用户点击输入框附件按钮（Paperclip 图标）→ 触发隐藏的 `<input type="file" multiple>`
2. 选择文件后 → 文件显示为预览 Chip（文件名 + 大小 + 状态图标）
3. 状态指示器：`pending`（等待）→ `uploading`（上传中，Loader2 动画）→ `done`（✓ 绿色）→ `error`（✗ 红色）
4. 每个 Chip 有 X 按钮可移除
5. 用户发送消息时 → `send()` 先确保会话存在 → 调用 `uploadAttachments(currentSessionId)` 先上传所有 pending 文件 → 将 `attachment_ids` 放入 chat 请求 payload → 发送后清空附件列表
6. 重复文件检测：上传后若 `is_duplicate=true`，Chip 旁显示黄色 AlertCircle 图标提示内容重复

**API 客户端**（`frontend/src/api/client.ts`）：
```typescript
apiUploadAttachment(token, file, sessionId, messageId?, onProgress?)
  : Promise<AttachmentUploadResponse>   // XHR 上传，含 content_hash + is_duplicate
apiListAttachments(token, sessionId)
  : Promise<AttachmentListResponse>     // 列出会话所有附件
apiDeleteAttachment(token, attachmentId)
  : Promise<{ attachment_id, status }>  // 软删除附件
```
使用 XMLHttpRequest 实现上传进度回调。

### 31.7 PostgreSQL 持久化与 Redis 缓存

**数据库模型**：`infra/storage/models.py` — `Attachment` 类（`attachments` 表）

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | String(36) PK | UUID 主键 |
| `session_id` | String(36) FK→chat_sessions.id | 所属会话（CASCADE 删除，已索引） |
| `user_id` | String(36) FK→users.id | 上传用户 |
| `filename` | String(512) | 原始文件名 |
| `file_size` | Integer | 文件大小（bytes） |
| `mime_type` | String(255) | MIME 类型 |
| `file_extension` | String(20) | 文件扩展名 |
| `content_hash` | String(128) | SHA-256 内容哈希（已索引） |
| `content_text` | Text | 解析后的文本内容（≤100KB） |
| `content_summary` | String(512) | 前 200 字符摘要 |
| `status` | String(20) | active / expired / deleted |
| `image_base64` | Text | 图片 base64 编码（nullable） |
| `image_mime` | String(100) | 图片 MIME 类型（nullable） |
| `message_id` | String(36) | 关联的上传消息 ID |
| `duplicate_of` | String(36) | 指向同内容的首个附件 ID（nullable） |
| `state_version` | Integer | 乐观并发版本号 |
| `created_at` / `updated_at` | DateTime(tz) | 时间戳 |

**索引**：`(session_id)`、`(user_id)`、`(content_hash)`、`(session_id, created_at)`。

**ChatSession 反向关系**：`attachments`（cascade="all, delete-orphan"）。

**双写策略**：
- 上传时同时写入 PostgreSQL（持久化 + FK 约束 + 去重检测）和 Redis（快速读取缓存）
- 读取时优先从 PostgreSQL 批量查询（`WHERE session_id=$1 AND id IN $2 AND status='active'`），缺失的 ID 回退到 Redis
- 删除时软标记 `status='deleted'` 并清除 Redis 缓存

**重复检测**：
- 上传时计算 `content_hash`（SHA-256），查询同会话同哈希的活跃附件
- 相同内容也允许上传（每次上传都是新的附件），但记录 `duplicate_of` 字段标记
- 前端通过 `is_duplicate` 响应字段提示用户

**ConversationState 集成**：
- `ConversationState.active_attachment_ids: list[str]` — 会话级活跃附件 ID 列表
- 每次上传后自动追加到 `ConversationState`，跨轮持久化
- Chat 请求未指定 `attachment_ids` 时，自动加载 `ConversationState` 中的所有活跃附件

**Redis 缓存**（辅助层）：
- **Key 格式**：`attachment:{attachment_id}:content` / `attachment:{attachment_id}:raw`
- **TTL**：12 小时（43,200 秒）
- **容错**：Redis 读取失败时跳过该附件（不阻断聊天请求），日志记录 warning

### 31.8 配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `attachment_upload_enabled` | `True` | 附件上传功能主开关 |
| `attachment_max_size_mb` | `20` | 最大文件大小（MiB） |
| `attachment_storage_path` | `/tmp/opentrace_attachments` | 文件临时存储路径 |
| `attachment_max_chars` | `4000` | 解析后内容最大字符数 |
| `multimodal_attachment_enabled` | `True` | 多模态图片解析开关 |

### 31.9 测试覆盖

| 测试文件 | 测试数 | 覆盖范围 |
|---------|--------|---------|
| `test_attachment_file_parser_contract.py` | 14 | 文件解析器全类型（txt/md/code/csv/json）/截断/header/不支持类型/图片多模态 |
| `test_attachment_api_kernel_contract.py` | 32 | API 端点/模型字段/扩展名校验/Redis key/FusionEngine 权重标签/background_materials 注入全路径/降级路径/截断/多附件拼接 |
| `test_attachments_contract.py` | 25 | [L3 Phase 2] Attachment ORM 模型字段/FK 关系/迁移链验证/API 端点完整覆盖/PG 持久化/ConversationState 集成/前端 API 函数签名/防重复追踪 |

### 31.10 架构原则

1. **唯一中枢**：附件不是回答来源，而是「候选认知材料」— LLM 根据背景材料自行判断和回答
2. **双重注入**：附件既作为 FusionEngine 加权证据参与竞争，又作为背景材料直接注入 LLM 提示词，确保文件内容在回答中充分体现
3. **安全第一**：扩展名白名单 + MIME 校验 + 大小限制，禁止可执行文件
4. **全路径覆盖**：正常路径、多问题路径、降级路径均支持背景材料注入
5. **按需解析**：图片多模态解析仅在 `multimodal_attachment_enabled=true` 时启用
6. **[L3 Phase 2] 会话级持久化**：附件从临时 Redis 缓存升级为 PostgreSQL 持久化存储（双写），通过 `ConversationState.active_attachment_ids` 跨轮自动生效，用户无需每次重新上传
7. **[L3 Phase 2] 自动加载**：指定 `attachment_ids` 或自动加载会话所有活跃附件，前后轮无缝衔接
8. **[L3 Phase 2] 去重检测**：SHA-256 内容哈希检测重复上传，但每次上传都生成新的附件记录（不阻塞），仅标记 `duplicate_of` 字段

---

## 32. NER PII 数据脱敏（NER-based PII Masking）

**核心文件**：`safety/masking/ner_masker.py`（~154 行）

### 32.1 设计动机

在查询进入 LLM 管线之前，自动检测并替换敏感实体为类型化占位符，防止 PII 数据进入第三方 LLM 服务。LLM 回答后逆向还原占位符为原始值。整个过程对用户透明。

### 32.2 覆盖实体类型

9 种中英文实体，全部基于精选正则（无外部 NLP 依赖）：

| 类型 | 覆盖范围 | 正则精度 |
|------|---------|---------|
| EMAIL | 标准邮箱格式 | 高 |
| PHONE_CN | 中国大陆手机号 1[3-9]xxxxxxxxx | 高 |
| PHONE_INTL | 国际电话号码（含分隔符） | 中 |
| CREDIT_CARD | 13-19 位数字（含空格/连字符） | 中 |
| ID_CN | 18 位身份证号（含校验位 X） | 高 |
| IP_ADDRESS | IPv4 地址 | 高 |
| PERSON_CN | 中文人名 + 称谓（先生/女士/老师/经理等） | 中 |
| LOCATION_CN | 中文地名 + 地理后缀（省/市/区/路/大厦等） | 中 |
| ORG_CN | 中文组织名 + 机构后缀（公司/银行/医院/学校等） | 中 |

### 32.3 可逆脱敏流程

```
原始查询: "请查张三先生的账户，手机13800138000"
    │  mask_input()
    ▼
脱敏查询: "请查{MASK_PERSON_CN_0}的账户，手机{MASK_PHONE_CN_0}"
    │  送入 LLM 管线（Plan/Agent/Fusion 全部使用脱敏后文本）
    ▼
LLM 回答: "{MASK_PERSON_CN_0}的账户余额为 500 元"
    │  unmask_output()
    ▼
最终回答: "张三先生的账户余额为 500 元"
```

### 32.4 编排器集成点

1. `orchestrator_v4.py` → `process()` 入口处调用 `mask_input(query)`
2. 脱敏后的 query 用于所有 Plan/Agent/Fusion 调用
3. 最终 `answer` 调用 `unmask_output()` 还原
4. XAI 认知追踪中 `start_trace()` 的 query 参数使用脱敏前原文（审计完整性）

### 32.5 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `KERNEL_NER_MASKING_ENABLED` | `True` | 脱敏主开关 |
| `KERNEL_NER_MASKING_ENTITY_TYPES` | 全部 9 种 | 逗号分隔的实体类型列表 |

### 32.6 测试覆盖

**文件**：`tests/test_ner_masking_contract.py`（28 个测试）

- 9 种实体类型识别与替换
- 可逆还原（占位符 → 原始值）
- 无 PII 文本零影响
- 边界条件（空字符串、仅占位符文本）
- `scan_pii()` 审计扫描
- 配置开关（enabled=false 跳过）
- 单例模式

详细设计见 [16.2 NER PII 数据脱敏](#162-ner-pii-数据脱敏-phase-3)。

---

## 33. 金丝雀测试与自动回滚（Canary Testing & Auto-Rollback）

**核心文件**：`safety/canary/canary_guard.py`（~327 行）

### 33.1 设计动机

规则引擎支持多版本 YAML 定义（如 `v1`/`v2`），但缺乏安全发布机制。金丝雀测试允许新版本先承载少量流量（如 10%），通过实时指标追踪判断是否衰退，出现问题时自动回滚到稳定版本，避免影响全体用户。

### 33.2 流量分桶

通过 `hash(user_id) % 100 < canary_percentage` 实现确定性分桶：
- 同一用户始终路由到同一版本（粘性）
- 10% 金丝雀 = hash 值 0-9 的用户路由到 canary 版本
- 90% 用户继续使用 baseline 版本

### 33.3 衰退检测

两种触发条件（满足任一即判定衰退）：

| 条件 | 阈值配置 | 说明 |
|------|---------|------|
| 错误率超标 | `kernel_canary_error_rate_threshold` (0.10) | canary error_rate > 10% |
| 延迟倍增 | `kernel_canary_latency_multiplier` (2.0) | canary avg_latency > baseline × 2 |

**冷启动保护**：`kernel_canary_min_samples`（默认 100）——样本不足时不做判断，避免因小样本波动误触发回滚。

### 33.4 自动回滚流程

```
CanaryGuard.sweep_all()  ← 定时任务 / API 触发
  └── check_health(rule_id)
      ├── 样本充足 → 比较 error_rate / latency
      ├── 已衰退 → auto_rollback_if_degraded()
      │   ├── 修改 _meta.yml: canary% → 0, baseline% → 100
      │   ├── grayscale.enabled → false
      │   ├── canary status → "rolled_back"
      │   └── 记录回滚事件 + 触发回调
      └── 未衰退 → 返回 CanaryStatus
```

### 33.5 集成点

| 位置 | 集成内容 |
|------|---------|
| `agents/rule_engine_agent.py` | `execute()` 循环中 `guard.record()` 记录每次执行的 success/latency_ms |
| `gateway/api_gateway/routers/rules.py` | `POST /rules/{rule_id}/rollback` 手动回滚端点 |
| `infra/config/settings.py` | 4 个 canary 配置项 |

### 33.6 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `KERNEL_CANARY_AUTO_ROLLBACK_ENABLED` | `True` | 自动回滚主开关 |
| `KERNEL_CANARY_ERROR_RATE_THRESHOLD` | `0.10` | 错误率阈值 |
| `KERNEL_CANARY_LATENCY_MULTIPLIER` | `2.0` | 延迟倍数阈值 |
| `KERNEL_CANARY_MIN_SAMPLES` | `100` | 最小样本数（冷启动保护） |

### 33.7 测试覆盖

**文件**：`tests/test_canary_rollback_contract.py`（34 个测试）

- 模块导入（CanaryGuard/RuleVersionMetrics/CanaryStatus/get_canary_guard）
- RuleVersionMetrics（error_rate/avg_latency_ms 计算）
- CanaryStatus dataclass
- record/health/rollback/history/sweep 全流程
- 配置项验证
- RuleEngineAgent 金丝雀接线
- API rollback 端点
- 包 `__init__.py`

详细设计见 [16.3 金丝雀测试与自动回滚](#163-金丝雀测试与自动回滚-phase-3)。

---

## 34. 可解释审计 XAI（Explainable Audit XAI）

**核心文件**：`safety/xai/cognitive_trace.py`（~317 行）

### 34.1 设计动机

V4/V5 认知管道包含多个阶段（Plan/Agent/Fusion/Critic），但此前缺少结构化的审计追踪。XAI 模块为每次查询构建完整的决策时间线，记录每个阶段**发生了什么**（数据）和**为什么这样做**（人类可读的推理说明），支持事后审计、调试和可解释性检查。

### 34.2 管道覆盖

```
Trace Timeline
──────────────────────────────────────────────►
PLAN → DST → AGENT → FUSION → CRITIC → REWRITE → FINAL
 │       │      │        │        │         │        │
 │       │      │        │        │         │        └─ answer_length, confidence, total_latency_ms
 │       │      │        │        │         └─ iteration, reason, improvement
 │       │      │        │        └─ issues_found, corrections[], llm_feedback
 │       │      │        └─ source_count, merged_length, strategy
 │       │      └─ agent_type, status, latency_ms, confidence
 │       └─ resolved_query, confidence
 └─ agent_types, subtask_count, plan_strategy
```

### 34.3 事件记录语义

每个事件包含 `reasoning` 字段（中文），直接可用作审计报告：

```json
{
  "timestamp": 1714780000.123,
  "stage": "PLAN",
  "event_type": "plan_generated",
  "data": {"plan_id": "p1", "subtasks": 3},
  "reasoning": "查询被拆分为 3 个子任务 (data/rag/web)，因为用户询问了华东区销量、最新行业报告和竞品动态"
}
```

### 34.4 容量与性能

- **事件上限**：单次追踪最大 `MAX_TRACE_EVENTS=500`，超标后静默丢弃
- **存储上限**：内存中 `MAX_STORED_TRACES=200`，FIFO 淘汰
- **延迟开销**：<1ms/event（纯内存操作，无 I/O）
- **内存估算**：200 条追踪 × ~100 事件 × ~500 字节 ≈ 10MB

### 34.5 API 端点

| 方法 | 路径 | 参数 | 说明 |
|------|------|------|------|
| GET | `/xai/traces` | `session_id?` `limit?` (1-100) | 列出追踪摘要 |
| GET | `/xai/traces/{trace_id}` | — | 获取完整追踪（含事件列表 + 管道阶段摘要） |
| GET | `/xai/sessions/{session_id}/trace` | — | 获取会话最近追踪 |

### 34.6 集成点

| 位置 | 集成内容 |
|------|---------|
| `kernel/orchestrator_v4.py` | `start_trace()` → 各阶段 `record_*()` → `finish_trace()` |
| `gateway/api_gateway/routers/xai.py` | 3 个 API 端点 |
| `gateway/api_gateway/main.py` | xai router 注册 |

### 34.7 测试覆盖

**文件**：`tests/test_xai_cognitive_trace_contract.py`（34 个测试）

- 模块导入（CognitiveTrace/CognitiveTracer/TraceEvent/get_cognitive_tracer）
- TraceEvent 创建与默认值
- start/finish 生命周期
- 全部录制方法（record_decision/agent_execution/fusion/critic/rewrite/final）
- 事件顺序保证
- 管道阶段摘要
- 列表/过滤/会话最近追踪
- 空追踪处理
- 事件上限 capping
- 编排器接线验证（7 个方法调用断言）
- API 路由端点验证
- 包 `__init__.py`

详细设计见 [16.4 可解释审计 XAI](#164-可解释审计-xai-phase-3)。

---
> 文档版本：SERVICE.md
>
> 维护原则：当核心能力、运行链路、配置项、API 端点发生变化时，优先追加或者修改或者更新本文档，使其代表当前项目状态的准确参考。
