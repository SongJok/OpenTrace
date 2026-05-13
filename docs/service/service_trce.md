# OpenTrace 系统蓝图
> 本文档是 OpenTrace 项目的完整技术参考，涵盖架构设计、API 接口、配置说明、数据流程、部署方案和开发指南。
> 
> 最后更新：2026-05-12

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
28. [V6 多轮对话增强（Multi-Turn Enhancement）](#28-v6-多轮对话增强multi-turn-enhancement)
29. [文件附件上传与上下文注入](#29-文件附件上传与上下文注入)
30. [NER PII 数据脱敏](#30-ner-pii-数据脱敏)
31. [金丝雀测试与自动回滚](#31-金丝雀测试与自动回滚)
32. [可解释审计 XAI](#32-可解释审计-xai)

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
| V6 | current | V5 + 多轮对话全面升级（6 大增强 + 15 项深度优化） |

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
│       ├── api/client.ts        # API 客户端
│       ├── components/          # UI 组件
│       │   ├── ChatInput.tsx    # 聊天输入（含快捷标签）
│       │   ├── ChatMessage.tsx  # 消息渲染
│       │   ├── MultiQuestionCards.tsx  # 多子问题卡片
│       │   └── Sidebar.tsx      # 侧边栏导航
│       ├── pages/               # 页面组件
│       ├── store/               # Zustand 状态管理
│       └── utils/               # 工具函数
├── gateway/                     # FastAPI 网关
│   └── api_gateway/
│       ├── main.py              # FastAPI 应用入口
│       └── routers/             # API 路由模块（20 个）
├── kernel/                      # 认知内核（核心模块）
│   ├── cognitive_kernel.py      # 中枢入口
│   ├── orchestrator_v4.py       # V4 编排器
│   ├── clarification_gate.py    # 主动追问门控
│   ├── refine_planner.py        # 纠正增量重规划
│   ├── dialogue_state_tracker.py # 对话状态追踪
│   ├── context_composer.py      # 智能上下文压缩
│   ├── protocol/                # 统一协议层
│   ├── plan_agent.py            # 任务规划 Agent
│   ├── dispatcher.py            # 并发任务分发
│   ├── dag_scheduler.py         # DAG 依赖调度
│   ├── query_router_v2.py       # L0 规则路由器
│   ├── tiny_router.py           # L1 Tiny Router
│   ├── complexity_engine.py     # 规则复杂度评分
│   ├── semantic_cache.py        # Redis 语义缓存
│   ├── fusion_engine/           # 证据融合引擎
│   ├── critic_engine/           # 质量审校引擎
│   ├── intent_engine/           # 意图识别
│   ├── data_cognition/          # 数据认知（Text2SQL）
│   └── context/                 # 查询重写
├── agents/                      # 智能体集群
│   ├── base.py                  # BaseAgent 抽象基类
│   ├── data_agent.py            # 数据查询 Agent
│   ├── rag_agent.py             # RAG 检索 Agent
│   ├── web_agent.py             # 联网搜索 Agent
│   ├── tool_agent.py            # 通用工具 Agent
│   ├── skills_agent.py          # 技能调用 Agent
│   ├── rule_engine_agent.py     # 规则引擎 Agent
│   ├── vision_agent.py          # 视觉分析 Agent
│   ├── worker.py                # Agent Worker
│   └── registry.py              # Agent 注册与发现
├── model/                       # 模型网关
│   ├── model_gateway/           # 模型路由 + 熔断 + 重试
│   ├── llm_adapter/             # LLM 适配器
│   ├── embedding/               # 嵌入模型接口
│   └── reranker/                # 重排接口
├── memory/                      # 记忆系统
│   ├── working_memory/          # 工作记忆
│   ├── semantic_memory/         # 语义记忆
│   ├── episodic_memory/         # 情节记忆
│   ├── procedural_memory/       # 程序记忆
│   ├── memory_router/           # 记忆路由
│   ├── evolution/               # 记忆演化
│   └── value_scorer.py          # 记忆价值评分
├── execution/                   # 执行平面
│   ├── dag_engine/              # DAG 执行引擎
│   ├── data/                    # 数据执行层
│   └── tool_router/             # 工具路由
├── infra/                       # 基础设施
│   ├── config/settings.py       # 统一配置
│   ├── storage/                 # 存储管理
│   ├── cache/                   # Redis 缓存
│   ├── message_bus/             # 消息总线
│   ├── observability/           # 可观测性
│   ├── security/                # 安全
│   └── errors/                  # 错误处理
├── safety/                      # 安全防护
│   ├── guardrails/              # 输入防护栏
│   ├── masking/                 # NER PII 脱敏
│   ├── canary/                  # 金丝雀测试
│   └── xai/                     # 可解释审计
├── rules/                       # YAML 规则存储
├── services/                    # 业务服务
├── skills/                      # 技能系统
├── alembic/                     # 数据库迁移
├── deploy/docker/               # Docker 配置
├── scripts/                     # 运维脚本
├── tests/                       # 测试（102 个文件）
├── docker-compose.yml           # Docker 编排
├── pyproject.toml               # Python 项目配置
├── alembic.ini                  # Alembic 配置
└── .env.example                 # 环境变量模板
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

所有后端调用通过 `apiFetch()` 统一处理，支持 Vite 环境变量 `VITE_API_URL` 配置。

### 5.3 快捷标签与斜杠命令

输入 `/` 弹出候选下拉框，包含以下命令：

| 命令 | 标签 | force_mode |
|------|------|------------|
| `/rag` | 知识库检索 | `rag` |
| `/data_query` | 数据查询 | `data_query` |
| `/data_analysis` | 数据分析 | `data_analysis` |
| `/anomaly_tracking` | 异常追踪 | `anomaly_tracking` |
| `/product` | 产品查询 | `product` |
| `/rule_engine` | 规则引擎 | `rule_engine` |
| `/skills` | 技能调用 | `skills` |
| `/web` | 联网搜索 | `web` |
| `/tool` | 工具调用 | `tool` |

**别名映射**：
- `/data` → `data_query`
- `/doc`, `/document` → `rag`
- `/search` → `web`
- `/rule` → `rule_engine`

### 5.4 消息渲染与卡片化管线

前端强制不展示裸 JSON，实现三层防御：

1. **ChatInput normalizeAnswerContent** - 检测卡片标识并序列化
2. **chat.ts normalizeMessageText** - 对已知卡片类型返回空
3. **ChatMessage 渲染管线** - 剥离 JSON 块，解析并渲染卡片

**卡片类型覆盖**：

| 卡片类型 | 检测条件 | 渲染方式 |
|---------|---------|---------|
| `time` | `parsed.current_time` 存在 | CardShell + 时间信息 |
| `weather` | `parsed.temperature` 存在 | CardShell + 天气信息 |
| `table` | `parsed.type === 'table'` | CardShell + DataTableChart |
| `data` | `parsed.sql` 非空 | CardShell + SQL + DataTableChart |
| `agent` | `parsed.agent_type` / `parsed.tool_name` | CardShell + 标题 + 内容 |

### 5.5 开发命令

```bash
cd frontend && npm install    # 安装依赖
npm run dev                  # 启动开发服务器
npm run build                # 构建
npm run test                 # 测试
```

---

## 6. API 网关

**基础路径**：`/api/v1`
**端口**：`14100`
**框架**：FastAPI

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
```

### 6.2 关键端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/auth/register` | 用户注册 |
| POST | `/auth/login` | 用户登录 |
| POST | `/chat` | 同步+流式聊天 |
| POST | `/chat/stop` | 取消 SSE 流 |
| POST | `/chat/feedback` | 记忆反馈 |
| POST | `/chat/attachments` | 上传文件附件 |
| POST | `/conversations` | 创建会话 |
| GET | `/conversations` | 列出会话 |
| POST | `/conversations/{id}/branch` | 分支会话 |
| POST | `/documents` | 上传文档 |
| POST | `/data/query` | 数据查询 |
| GET | `/health` | 基础健康检查 |
| GET/POST | `/skills` | 技能 CRUD |
| GET/POST | `/rules` | 规则 CRUD |
| GET | `/xai/traces` | 认知审计追踪 |

### 6.3 异常处理

**后端异常分层**：
- `AppException` → 统一 JSON 错误信封：`{code, message, details, request_id, timestamp}`
- `Exception` → 全局兜底返回 `INTERNAL_ERROR`
- 每个响应携带 `x-request-id` 和 `x-response-time-ms` 头

---

## 7. 认知内核（Cognitive Kernel）

**文件**：`kernel/cognitive_kernel.py`

认知内核是系统的**唯一中枢入口**，所有能力均通过内核调度。

### 7.1 核心原则

1. 所有输出必须由认知内核生成
2. 所有插件返回的数据只是「候选认知材料」
3. LLM 不是回答器，而是「认知执行器」
4. Prompt 不是模板，而是「认知协议」

### 7.2 执行流程（V5）

```
Step 0: is_multi_question  — 多子问题检测
Step 1: Working Memory     — 身份问答缓存检查
Step 2: V5 Routing Tier    — L0 → L0.5 → L1 → L2
Step 3: ContextComposer    — 长历史智能压缩
Step 4: Memory Injection   — 记忆片段注入
Step 5: intent_domain      — 意图域分类
Step 6: SelfModel          — 自我能力评估
Step 7: OrchestratorV4     — 全管线执行
Step 8: Active Memory      — 主动记忆写入检测
Step 9: Semantic Cache Save — 写入缓存
Step 10: Memory Save       — 异步保存对话记忆
```

### 7.3 入口方法

| 方法 | 签名 | 返回 |
|------|------|------|
| `run(request: KernelRequest)` | 同步执行 | `KernelResponse` |
| `stream(request: KernelRequest)` | SSE 流式 | `AsyncIterator[dict]` |

---

## 8. V5 分层路由（L0/L1/L2 Routing Tier）

### 8.1 架构图

```
User Query
    │
    ▼
┌─────────────────────────────────────────┐
│ L0: Rule Router (零 LLM, <1ms)           │
│  FAQ / 身份问题 / 斜杠命令 / 工具触发 / 去重 │
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
│  → identity/faq: MiddleShort 8B 直答     │
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

### 8.2 L0 规则路由器

**文件**：`kernel/query_router_v2.py`

**FAQ 固定回答（13 条）**：你好/您好、hi/hello、谢谢/感谢、再见/bye、好的/ok、嗯、帮助/help、你能做什么/有什么功能

**工具触发模式**：

| 触发类别 | 正则 | 路由 |
|---------|------|------|
| `_TOOL_TIME` | `几点\|什么时间\|现在时间\|日期\|今天几号\|星期几` | force_mode=tool |
| `_TOOL_WEATHER` | `天气\|气温\|下雨\|刮风\|雾霾\|aqi\|pm2.5` | force_mode=tool |
| `_TOOL_CALC` | `^[\d\s+\-*/().^%]+$` | force_mode=tool |

### 8.3 L1 Tiny Router

**文件**：`kernel/tiny_router.py`
**模型**：JuniorShort 1.7B

**分类 Prompt**：
```
{"route": "identity|faq|tool|knowledge|complex",
 "difficulty": "trivial|simple|moderate|complex",
 "needs_tool": bool, "needs_data": bool, "needs_web": bool}
```

### 8.4 复杂度引擎

**文件**：`kernel/complexity_engine.py`

**评分因子**：

| 因子 | 权重 | 信号 |
|------|------|------|
| 查询长度 | 0-30 | 长度越长分数越高 |
| 歧义信号 | 0-25 | 模糊代词+15, 缺失实体+10 |
| 工具需求 | 0-20 | 工具关键词+10 |
| 风险信号 | 0-30 | PII+40, SQL注入+50 |
| 多跳指示 | 0-25 | 跨表引用+20 |
| 领域特异性 | 0-20 | 数据查询+15 |

---

## 9. V4 编排器（Orchestrator V4）

**文件**：`kernel/orchestrator_v4.py`

### 9.1 架构

```
OrchestratorV4Request
    │
    ▼
Process:
├── 0. Resume/Branch Check → 对话分支回溯
├── 1. force_mode 检测 → 跳过规划
├── 2. Correction Detection → 纠正意图检测
├── 3. Dialogue State Tracking → 槽位解析
├── 4. PlanAgent → TaskPlan（DAG 子任务图）
├── 5. Memory Context 注入 → 记忆片段
├── 6. Dispatcher → 并行调度 + DAG checkpoint
├── 7. DAG Scheduler → 依赖解析 + 拓扑排序
├── 8. 各 Agent 执行 → 返回候选结果
├── 9. FusionEngine → 加权融合多源证据
├── 10. CriticEngine → 质量审校
├── 11. ClarificationGate → 启发式追问
├── 12. Answer Generation → 结构化回答
└── 13. Tool Card Injection → 卡片 JSON 注入
```

### 9.2 有效强制模式

```python
VALID_FORCE_MODES = frozenset({
    "rag", "data_query", "data_analysis", "anomaly_tracking",
    "product", "rule_engine", "tool", "skills", "web", "vision",
})
```

### 9.3 Agent 映射

| force_mode | Agent 类型 |
|------------|------------|
| `rag` | `rag` |
| `data_query` | `data` |
| `data_analysis` | `data` |
| `product` | `product` |
| `rule_engine` | `rule_engine` |
| `tool` | `tool` |
| `skills` | `skills` |
| `web` | `web` |
| `vision` | `vision` |

### 9.4 Fusion + Critic

- **FusionEngine**：加权融合多 Agent 结果
- **SequenceFusionEngine**：多子问题顺序融合
- **CriticEngine**：质量审校 + 重写建议

---

## 10. 智能体集群（Agent Cluster）

### 10.1 BaseAgent

**文件**：`agents/base.py`

所有 Agent 继承 `BaseAgent`，需实现 `execute(task: SubTask) -> AgentResult`。

**AgentResult 标准化输出**：

```python
class AgentResult(BaseModel):
    task_id: str
    agent_type: str
    status: str           # success | error | timeout
    content: str          # 人类可读的文本结果
    confidence: float     # 置信度 0-1
    metadata: dict
    error: str | None
    evidence: list[dict]  # 证据列表
    agent_trace: dict | None  # 执行链路记录
```

### 10.2 Agent 列表

| Agent | 文件 | 说明 |
|-------|------|------|
| DataAgent | `data_agent.py` | Text2SQL 数据查询 |
| RAGAgent | `rag_agent.py` | 文档检索（pgvector） |
| WebAgent | `web_agent.py` | 联网搜索（Serper API） |
| ToolAgent | `tool_agent.py` | 通用工具（时间/天气/计算） |
| SkillsAgent | `skills_agent.py` | 技能调用 |
| RuleEngineAgent | `rule_engine_agent.py` | YAML 规则引擎 |
| VisionAgent | `vision_agent.py` | 视觉分析 |

### 10.3 Agent Worker

**文件**：`agents/worker.py`

消费 Redis Bus 消息，支持 `pubsub` 和 `stream` 两种模式。

---

## 11. 模型网关（Model Gateway）

**文件**：`model/model_gateway/gateway.py`

### 11.1 角色路由（9 个角色）

| 角色 | 用途 | 默认模型 | 参数量 |
|------|------|----------|--------|
| `ROUTER` | L1 单次分类 | qwen3-1.7b | 1.7B |
| `IDENTITY` | 用户身份识别 | qwen3-0.6b | 0.6B |
| `FAST` | 简单 FAQ/澄清 | qwen3-8b | 8B |
| `KNOWLEDGE` | 事实性知识问答 | qwen3-14b | 14B |
| `CHEAP_CRITIC` | 轻量级质量审校 | qwen3-14b | 14B |
| `PLANNING` | 意图识别/任务规划/SQL 生成 | qwen3.5-flash | 8B |
| `COMPRESS` | 上下文压缩/总结 | qwen3.5-27b | 27B |
| `QUERY` | 用户查询回答/证据融合 | qwen3.6-plus | 32B |
| `VISION` | 多模态分析 | qwen3.6-vl-plus | — |

### 11.2 熔断器设计

每个角色有独立的 CircuitBreaker：

| 参数 | 值 |
|------|------|
| failure_threshold | 5 |
| recovery_timeout | 60s |
| half_open_max_calls | 3 |

### 11.3 错误分类与重试

| 错误类别 | 处理策略 |
|---------|---------|
| `transient` | 自动重试 |
| `rate_limit` | 指数退避重试 |
| `context_length` | 自动截断上下文后重试 |
| `model_error` | 切换备用 provider |
| `offline` | 降级到 `_offline_fallback_response()` |

### 11.4 嵌入与重排

| 组件 | 默认实现 | 模型名 |
|------|----------|--------|
| Embedder | DashScope | `text-embedding-v3` |
| Embedder (fallback) | Hash | — |
| Reranker | Heuristic | `BAAI/bge-reranker-v2-m3` |
| Reranker (DashScope) | DashScope | `BAAI/bge-reranker-v2-m3` |

---

## 12. 记忆系统（Memory System）

四层记忆 + 路由 + 演化 + 价值评分闭环。

### 12.1 记忆层级

| 层 | 模块 | 文件 | 说明 |
|----|------|------|------|
| L1 工作记忆 | `working_memory` | `memory/working_memory/` | 环形缓冲区（最大 32 轮）+ 身份缓存 |
| L2 语义记忆 | `semantic_memory` | `memory/semantic_memory/` | 向量检索 |
| L3 情节记忆 | `episodic_memory` | `memory/episodic_memory/` | Redis 持久化会话事件 |
| L4 程序记忆 | `procedural_memory` | `memory/procedural_memory/` | 待接入 |
| 路由 | `memory_router` | `memory/memory_router/` | 联邦检索 + 重排序 |
| 演化 | `evolution` | `memory/evolution/` | 强化 + 演化 + 压缩 |
| 价值评分 | `value_scorer` | `memory/value_scorer.py` | base + recency + feedback |

### 12.2 价值评分与反馈闭环

**文件**：`memory/value_scorer.py`

```
final_score = 0.5 × base_score + 0.3 × recency_score + 0.2 × feedback_score
recency_score = exp(-0.01 × turn_gap)     # 半衰期 ~70 轮
feedback_score = like: +0.3 / dislike: -0.5 / 无反馈: 0
```

### 12.3 Feedback API

`POST /api/v1/chat/feedback` 接收 `{session_id, chunk_id, feedback_type: like|dislike|none}`。

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
| `sql_executor.py` | SQL 只读执行 |
| `query_intents.py` | 查询意图识别 |

### 13.3 工具路由

**文件**：`execution/tool_router/`

- 时间工具：`get_current_time()`
- 天气工具：`get_weather(city)`
- 计算器：`calculate(expression)`

---

## 14. 数据认知层（Data Cognition）

**文件**：`kernel/data_cognition/`

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

---

## 15. 基础设施层（Infrastructure）

### 15.1 配置

**文件**：`infra/config/settings.py`

`Settings` 单例整合所有配置块：

| 配置块 | 说明 |
|--------|------|
| `DatabaseSettings` | 数据库连接 |
| `RedisSettings` | Redis 多 DB |
| `LLMSettings` | 9 个 LLM 角色 |
| `EmbeddingSettings` | 嵌入模型 |
| `RerankSettings` | 重排模型 |
| `JWTSettings` | JWT |
| `OTelSettings` | 链路追踪 |
| `AppSettings` | 应用 + 内核 + V5 + V6 |

### 15.2 Redis 分库

| DB | 用途 |
|----|------|
| 10 | Session |
| 11 | Cache（语义缓存） |
| 12 | Memory |
| 13 | Queue |
| 14 | Rate Limit |
| 15 | Pub/Sub |

### 15.3 可观测性

| 组件 | 文件 | 说明 |
|------|------|------|
| Logger | `observability/logger.py` | 结构化日志 |
| Metrics | `observability/metrics.py` | Prometheus 指标 |
| Tracer | `observability/tracer.py` | OpenTelemetry 追踪 |

---

## 16. 安全与防护（Safety）

### 16.1 零信任与输入防护

- **零信任风险评估**：输入风险评分
- **输入防护栏**：PII/SQL 注入/有害内容检测
- **SQL 只读校验**：所有生成的 SQL 强制只读
- **JWT 认证**：所有 API 端点需 Bearer Token

### 16.2 NER PII 数据脱敏

**文件**：`safety/masking/ner_masker.py`

在查询进入 LLM 管线前自动检测并替换敏感实体：

| 类型 | 示例 | 占位符 |
|------|------|--------|
| `EMAIL` | `user@example.com` | `{MASK_EMAIL_0}` |
| `PHONE_CN` | `13800138000` | `{MASK_PHONE_CN_0}` |
| `ID_CN` | `110101199001011234` | `{MASK_ID_CN_0}` |
| `IP_ADDRESS` | `192.168.1.1` | `{MASK_IP_ADDRESS_0}` |
| `PERSON_CN` | `张三` | `{MASK_PERSON_CN_0}` |
| `LOCATION_CN` | `北京市` | `{MASK_LOCATION_CN_0}` |
| `ORG_CN` | `阿里巴巴集团` | `{MASK_ORG_CN_0}` |

### 16.3 金丝雀测试与自动回滚

**文件**：`safety/canary/canary_guard.py`

为规则引擎提供版本金丝雀发布能力：

**衰退检测逻辑**：
- 错误率 > 10% → 触发回滚
- 平均延迟 > 基线 2× → 触发回滚
- 最小样本数保护：100 个样本

### 16.4 可解释审计 XAI

**文件**：`safety/xai/cognitive_trace.py`

为每次查询构建结构化的认知管道审计追踪：

**管道阶段覆盖**：

| 阶段 | 记录内容 |
|------|---------|
| DST | 对话状态追踪 |
| PLAN | 任务规划 |
| AGENT | Agent 执行结果/耗时/置信度 |
| FUSION | 多源证据融合 |
| CRITIC | 质量审校 |
| REWRITE | 重写迭代 |
| FINAL | 最终答案 |

---

## 17. 技能系统（Skills）

**文件**：`skills/marketplace/`

- **Skill Store**：技能 CRUD + 持久化
- **Skill Manifest**：技能清单验证
- **Skills API**：REST API
- **SkillsAgent**：技能执行

---

## 18. 规则引擎（Rule Engine）

**文件**：`rules/`、`agents/rule_engine_agent.py`

### 18.1 规则版本化与灰度发布

每个规则目录包含 `_meta.yml`：

```yaml
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
  hash_key: user_id
```

### 18.2 规则管理 API

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/rules` | 列出规则 |
| POST | `/rules` | 创建规则 |
| PUT | `/rules/{id}` | 更新规则 |
| DELETE | `/rules/{id}` | 删除规则 |
| POST | `/rules/{rule_id}/rollback` | 规则版本回滚 |

---

## 19. 消息总线（Message Bus）

### 19.1 认知事件总线

**文件**：`infra/message_bus/cognitive_event_bus.py`

- 统一事件模型：ROUTING、PLANNING、EXECUTION、EVIDENCE、FUSION、CRITIC、FEEDBACK、LEARNING
- 事件携带统一元信息：`trace_id`, `span_id`, `parent_span_id`, `session_id`, `request_id`

### 19.2 Agent Bus

**文件**：`infra/message_bus/agent_bus.py`

- 支持 `pubsub` 和 `stream` 两种模式
- 死信队列：`opentrace:agent:stream:dlq`

---

## 20. 快捷标签与强制模式路由

### 20.1 L0 斜杠命令处理

**文件**：`kernel/query_router_v2.py`

斜杠命令通过正则 `^/(\w[\w_]*)\s*` 检测，经别名映射解析为 `force_mode`。

### 20.2 9 种有效 force_mode

`rag`, `data_query`, `data_analysis`, `anomaly_tracking`, `product`, `rule_engine`, `tool`, `skills`, `web`

### 20.3 工具触发词自动路由

| 类别 | 示例查询 | 路由 |
|------|---------|------|
| 时间 | "现在几点" | force_mode=tool |
| 天气 | "北京天气" | force_mode=tool |
| 计算 | "1+1" | force_mode=tool |

---

## 21. 数据库模型与迁移

### 21.1 ORM 模型

**文件**：`infra/storage/models.py`

| 模型 | 说明 |
|------|------|
| `User` | 用户（邮箱/密码/角色） |
| `ChatSession` | 聊天会话 |
| `ConversationState` | 结构化对话状态 |
| `Attachment` | 文件附件持久化 |
| `TraceLog` | 请求追踪日志 |
| `UserMemory` | 用户记忆 |
| `Feedback` | 用户反馈 |

### 21.2 迁移

**文件**：`alembic/versions/`

- 所有迁移脚本需幂等
- 执行迁移：`docker compose exec -T api alembic upgrade head`
- 查看当前版本：`docker compose exec -T api alembic current`

---

## 22. 配置说明

### 22.1 环境变量

**数据库**：
```
DATABASE_URL=postgresql+asyncpg://postgres:PASSWORD@postgres:5432/opentrace_v2
```

**Redis**：
```
REDIS_URL=redis://localhost:6379/10
REDIS_SESSION_DB=10 / REDIS_CACHE_DB=11 / REDIS_MEMORY_DB=12
```

**V5 路由层**：
```
KERNEL_V5_ROUTING_ENABLED=true
KERNEL_L0_RULE_ROUTER_ENABLED=true
KERNEL_L1_TINY_ROUTER_ENABLED=true
KERNEL_SEMANTIC_CACHE_ENABLED=true
```

**V6 多轮对话增强**：
```
KERNEL_CLARIFICATION_GATE_ENABLED=true
KERNEL_CORRECTION_DETECTION_ENABLED=true
KERNEL_CONTEXT_COMPOSER_ENABLED=true
KERNEL_MEMORY_VALUE_SCORING_ENABLED=true
KERNEL_CONVERSATION_BRANCHING_ENABLED=true
```

**文件附件上传**：
```
ATTACHMENT_UPLOAD_ENABLED=true
ATTACHMENT_MAX_SIZE_MB=20
MULTIMODAL_ATTACHMENT_ENABLED=true
```

**金丝雀测试**：
```
KERNEL_CANARY_AUTO_ROLLBACK_ENABLED=true
KERNEL_CANARY_ERROR_RATE_THRESHOLD=0.10
KERNEL_CANARY_LATENCY_MULTIPLIER=2.0
```

---

## 23. Docker 部署

### 23.1 服务

| 服务 | 端口 | 说明 |
|------|------|------|
| `postgres` | 5432 | PostgreSQL 16 + pgvector |
| `redis` | 6380→6379 | Redis 7 |
| `api` | 14100 | FastAPI 网关 |
| `agent-worker` | — | Agent 消息消费者 |
| `prometheus` | 14190→9090 | 指标收集（可选） |
| `jaeger` | 14186:16686 | 分布式追踪（可选） |

### 23.2 常用 Docker 命令

```bash
bash start.sh                    # 启动所有服务
bash stop.sh                     # 停止服务
bash restart.sh                  # 强制重启
bash start.sh --with-observability  # 启动 + 可观测性
bash scripts/docker_logs.sh api  # 查看 API 日志
```

---

## 24. 常用命令

### 24.1 服务管理

| 命令 | 说明 |
|------|------|
| `bash start.sh` | 启动所有服务 |
| `bash stop.sh` | 停止所有服务 |
| `bash restart.sh` | 强制重启 |

### 24.2 测试

| 命令 | 说明 |
|------|------|
| `pytest` | 运行全部测试 |
| `pytest tests/test_name.py::test_method` | 运行特定测试 |
| `pytest -v` | 详细输出 |

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

---

## 25. 测试体系

### 25.1 总览

- **测试文件**：102 个
- **测试方法**：759 个
- **框架**：pytest + unittest.TestCase
- **风格**：合约测试

### 25.2 主要测试模块

| 测试文件 | 测试数 | 覆盖范围 |
|---------|--------|---------|
| `test_v5_routing_contract.py` | 50 | V5 L0/L1/缓存/复杂度 |
| `test_data_cognition_pipeline.py` | 36 | Text2SQL 完整管线 |
| `test_canary_rollback_contract.py` | 34 | 金丝雀测试 |
| `test_xai_cognitive_trace_contract.py` | 34 | XAI 认知追踪 |
| `test_multi_question_orchestration_contract.py` | 33 | 多子问题编排 |
| `test_attachment_api_kernel_contract.py` | 32 | 附件上传 API |
| `test_ner_masking_contract.py` | 28 | NER 脱敏 |
| `test_force_mode_routing.py` | 20 | 强制模式路由 |
| `test_memory_context_injection.py` | 18 | 记忆上下文注入 |

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
| 数据库连接失败 | 检查 `DATABASE_URL` |
| Redis 连接失败 | 检查 `REDIS_URL` |
| Agent 超时 | 增大 `KERNEL_AGENT_TIMEOUT_SEC` |

---

## 27. 开发规范

### 27.1 代码风格

- **格式化**：使用 `black` 自动格式化
- **Lint**：使用 `ruff` 检查
- **类型检查**：使用 `mypy`

### 27.2 提交规范

遵循 Conventional Commits 规范：
- `feat:` - 新功能
- `fix:` - 修复 bug
- `docs:` - 文档更新
- `refactor:` - 重构
- `test:` - 测试更新
- `chore:` - 构建/工具更新

### 27.3 测试规范

- 所有新功能必须编写测试
- 测试文件命名：`test_*.py`
- 测试方法命名：`test_*`

---

## 28. V6 多轮对话增强

### 28.1 6 大增强特性

| 特性 | 说明 |
|------|------|
| **Context Compression** | 长历史智能压缩 |
| **Dialogue State Tracking** | 对话状态追踪 |
| **Memory Value Feedback** | 记忆价值闭环 |
| **Error Correction** | 错误纠正 |
| **ClarificationGate** | 主动追问 |
| **Conversation Branching** | 对话分支 |

### 28.2 关键组件

**ClarificationGate**：启发式检查置信度 < 0.6 + 短答案 + 信息不足，触发时返回追问

**RefinePlanner**：检测"不对/错了/换成"等纠正意图，进行增量重规划

**DialogueStateTracker**：短查询槽位解析，指代消解

**ContextComposer**：长历史智能压缩为 ConversationSummary

---

## 29. 文件附件上传与上下文注入

### 29.1 支持的文件类型

- txt、pdf、docx、csv、xlsx、json、code、image

### 29.2 处理流程

1. 前端上传文件 → 后端存储 → 返回 attachment_id
2. 聊天请求携带 attachment_id → 后端加载文件内容
3. 文件内容转为 `ToolResult(source="attachment")` 注入 FusionEngine
4. 作为 `background_materials` 注入 LLM prompt

### 29.3 配置

```bash
ATTACHMENT_UPLOAD_ENABLED=true
ATTACHMENT_MAX_SIZE_MB=20
ATTACHMENT_STORAGE_PATH=/tmp/opentrace_attachments
```

---

## 30. NER PII 数据脱敏

### 30.1 实体类型

| 类型 | 示例 | 占位符 |
|------|------|--------|
| `EMAIL` | `user@example.com` | `{MASK_EMAIL_0}` |
| `PHONE_CN` | `13800138000` | `{MASK_PHONE_CN_0}` |
| `ID_CN` | `110101199001011234` | `{MASK_ID_CN_0}` |
| `IP_ADDRESS` | `192.168.1.1` | `{MASK_IP_ADDRESS_0}` |
| `PERSON_CN` | `张三` | `{MASK_PERSON_CN_0}` |
| `LOCATION_CN` | `北京市` | `{MASK_LOCATION_CN_0}` |
| `ORG_CN` | `阿里巴巴集团` | `{MASK_ORG_CN_0}` |

### 30.2 脱敏流程

1. 编排器入口处调用 `get_ner_masker().mask_input(req.query)`
2. 脱敏后的查询用于后续所有 LLM 调用
3. 最终答案通过 `unmask_output()` 还原占位符

---

## 31. 金丝雀测试与自动回滚

### 31.1 核心组件

```python
class CanaryGuard:
    def record(rule_id, version, success, latency_ms)      # 记录执行指标
    def check_health(rule_id) -> CanaryStatus              # 健康检查
    def rollback(rule_id, reason="") -> bool               # 回滚
    def auto_rollback_if_degraded(rule_id) -> CanaryStatus # 自动回滚
    def sweep_all() -> list[CanaryStatus]                  # 全量巡扫
```

### 31.2 衰退检测

- 错误率 > 10% → 触发回滚
- 平均延迟 > 基线 2× → 触发回滚
- 最小样本数：100

---

## 32. 可解释审计 XAI

### 32.1 核心组件

```python
class CognitiveTracer:
    def start_trace(session_id, query) -> str    # 开始追踪
    def finish_trace(trace_id, summary)          # 结束追踪
    def record_decision(trace_id, stage, ...)    # 记录决策
    def record_agent_execution(trace_id, ...)    # 记录 Agent 执行
    def record_fusion(trace_id, ...)             # 记录融合
    def record_critic(trace_id, ...)             # 记录审校
    def get_trace(trace_id) -> dict              # 获取追踪
```

### 32.2 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/xai/traces` | 列出追踪 |
| GET | `/xai/traces/{trace_id}` | 获取完整追踪 |
| GET | `/xai/sessions/{session_id}/trace` | 获取会话最近追踪 |

---

*本文档最后更新于 2026-05-12*