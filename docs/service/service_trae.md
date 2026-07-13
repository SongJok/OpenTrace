# OpenTrace 完整项目文档

> **版本**: 2.0.0 | **最后更新**: 2026-07-12 | **许可**: MIT
>
> 本文档是 OpenTrace 项目的唯一权威技术参考，涵盖架构设计、API 接口、配置说明、数据流程、部署方案和开发指南。所有内容均从源码直接分析得出。

---

# Part I: 介绍与概述

## Chapter 1: 项目概述

### 1.1 什么是 OpenTrace

OpenTrace 是一个以**认知内核（Cognitive Kernel）**为核心构建的**企业级分布式认知操作系统**（Distributed Cognitive Operating System）。它不是一个简单的 LLM 聊天机器人——它是一个完整的智能体运行时系统，将所有 AI 能力（对话、检索、数据分析、工具调用、记忆、任务编排）组织成一套可部署、可治理、可演化的 AgentOS 后端。

系统的核心设计理念是**认知运行时管线**（Cognitive Runtime Pipeline）：所有用户请求经过统一的认知执行流水线，从查询改写、深度理解、认知规划、约束检查、执行、证据收集、融合、批评到制品合成，每一步都有确定性护栏和治理机制。不是"让 LLM 回答一切"，而是"让 LLM 在受控的认知管线中执行特定认知任务"。

### 1.2 项目元信息

| 属性 | 值 |
|------|-----|
| 项目名称 | OpenTrace |
| 版本 | 0.1.0 |
| Python 版本 | ≥3.11 |
| 许可证 | MIT |
| 应用端口 | 14100 (API Gateway), 14108 (Frontend Dev) |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存 | Redis 7 (6-DB 分区) |
| 容器化 | Docker Compose (4 服务) |
| 消息队列 | Celery + RabbitMQ / Redis Stream |
| LLM 提供者 | 阿里巴巴 Qwen 系列 (DashScope API) |

### 1.3 核心能力矩阵

| 能力域 | 实现方式 | 核心依赖 |
|--------|---------|---------|
| 对话问答 | Cognitive Kernel + LLM Gateway + 认知执行器 | DashScope/Qwen 系列模型 |
| 文档检索（RAG） | Query Rewrite + HyDE + 混合检索 + Rerank + 证据质量控制 | pgvector, DashScope 嵌入 |
| 数据查询（Text2SQL） | SemanticLayer + SQLPlanner + DataAgent V2 认知管线 | PostgreSQL/MySQL/ClickHouse |
| 联网搜索 | WebAgent + WebIntelligence + 覆盖评估器 | Serper API |
| 工具调用 | ToolAgent + 内置工具集 + 工具选择器 | 天气 API、时间服务等 |
| 技能执行 | Skills Marketplace + Skill Runtime | 可安装技能包 |
| 视觉分析 | VisionAgent + Qwen3-VL | DashScope Vision API |
| 记忆管理 | Working/Episodic/Semantic/Procedural Memory + TMS | PostgreSQL + Redis |
| 代码执行 | 沙箱运行时（AST/gVisor/Firecracker） | 本地/容器/MicroVM |
| 规则解释 | RulesAgent + 规则引擎 | 关键词匹配 + LLM |
| 知识管理 | 知识编排引擎 + 知识编译 | pgvector + LLM |
| 企业多租户 | 租户隔离 + 配额 + 计费 + RLS | PostgreSQL + Redis |

### 1.4 vNext 主路径架构

这是系统当前的主请求处理路径，所有请求必经此路：

```
Client → API Gateway (FastAPI, port 14100)
  → Chat Router (认证 → 风险评估 → 附件解析 → 上下文加载)
  → CognitiveKernel (意图识别 → V5 快路径检查 → 回合增强)
  → RuntimeGateway
    → CognitiveSupervisor.prepare_run
      → 控制平面门控 (预检、配额)
      → 治理评估 (风险/证据/策略)
      → RuntimeTask 构建
      → RuntimeContext 构建 (40+ 结构化字段)
      → 世界状态注入
      → 目标图绑定 (GoalGraph)
      → 策略投影注入
      → 上下文织物种子
    → RuntimeTurnDispatcher.run_turn()
      → runtime.registry (registry_governance)
      → cognitive_executive | data_intelligence | multi_goal
    → run_outcomes (Artifact, GoalEvidenceBinding, semantic_alerts)
  → SSE/JSON Response
```

### 1.5 架构决策记录（ADR）

| 编号 | 主题 | 文件 |
|------|------|------|
| ADR-001 | vNext 主路径架构 | `docs/adr/001-vnext-main-path.md` |
| ADR-002 | 治理分层架构 | `docs/adr/002-governance-layers.md` |
| ADR-003 | 记忆织网架构 | `docs/adr/003-memory-fabric.md` |

---

## Chapter 2: 核心设计原则

### 2.1 七大设计原则

OpenTrace 的架构由七个核心原则驱动，每个原则对应一个架构层面的设计决策：

**原则 1: Planning First（规划优先）**

一次规划到位，不做运行时试探。规划结果投影为 ExecutionPlan 后由运行时执行，无自主 Agent 回退。规划分为四层：Goal → Strategic → Execution → Projection。所有 fallback 决策由认知执行器在约束层统一管理，执行器本身不允许自主决策。

**原则 2: Evidence First（证据优先）**

任务输出是 Evidence，不是原始文本。所有插件返回的数据仅为「候选认知材料」，经证据总线排序、融合后才形成最终回答。每个 Evidence 携带完整的 provenance（来源）、confidence（置信度）和 contradiction（矛盾）元数据。这确保了每个回答都可以追溯到具体证据源。

**原则 3: Capability First（能力优先）**

按 `capability_type` 分配任务（如 `data.query`、`web.search`），不按 Agent 名称硬编码路由。能力通过 Agent Topology Manifest 统一声明，能力注册表在运行时动态解析。这实现了能力与实现的解耦。

**原则 4: Runtime First（运行时优先）**

执行器只负责执行，不允许自主 fallback。所有 fallback 决策由认知执行器在约束层统一管理。执行器通过 AgentRuntimeExecutor 统一门面调度，确保执行行为的一致性和可预测性。

**原则 5: 确定性护栏（Deterministic Guardrails）**

约束层不调用 LLM，纯规则 + 查表。所有 LLM 调用必须经过 ModelGateway 统一路由。预算、策略、风险、能力可用性、历史先验五项检查均为确定性计算，不依赖概率模型。

**原则 6: 模块间仅通过 RuntimeContext 通信**

禁止跨模块直接 import，每个模块自治。RuntimeContext 是单次认知回合中流经每一层的唯一真相来源（Single Source of Truth）。这消除了模块间的隐式依赖，使系统高度可测试和可组合。

**原则 7: Goal-Driven（目标驱动）**

所有用户查询投影为 GoalGraph（目标图），后续所有执行围绕目标进行。每个子目标映射为执行节点，GoalContribution 追踪每个 Agent 对目标的贡献。这使得系统可以量化每个执行步骤的价值。

### 2.2 认知管线完整流程

```
用户查询 → IntentLock → Rewrite → Understand → Policy
  → Plan(V2) → ConstraintLayer → Execute → EvidenceBus
  → Rank → Resolve → Fuse(V2) → Critic(V2)
  → CognitiveIteration → Artifact → Workspace → Memory → Archive
```

### 2.3 多 Prompt 链执行流

系统采用"多 Prompt 链 + 并行插件执行"的核心逻辑，而非单一 Prompt。每个认知阶段使用专门的 Prompt 和特定的 LLM 角色：

1. **意图识别** → 使用 ROUTER 角色 (qwen3-1.7b) 进行分类
2. **任务规划** → 使用 PLANNING 角色 (qwen3.6-plus) 分解任务
3. **工具选择** → 确定性规则 + LLM 辅助选择 Agent
4. **并行插件执行** → 多个 Agent 并行执行，结果通过证据总线汇聚
5. **推理** → 使用 QUERY 角色 (qwen3.7-max) 进行语义推理
6. **反思** → 使用 CHEAP_CRITIC 角色 (qwen3.6-plus) 评估质量
7. **元认知** → 系统级认知健康评估
8. **记忆存储** → 多类型记忆持久化

---

## Chapter 3: 系统架构

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Frontend (React + Vite)                         │
│                  localhost:14108 (Dev) / Nginx (Prod)                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ ChatPage │ │DataPage  │ │DocPage   │ │Settings  │  ...          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │ HTTP/SSE (VITE_API_URL)
┌──────────────────────────▼──────────────────────────────────────────┐
│                   API Gateway (FastAPI, :14100)                      │
│  中间件: CORS → TenantContext → RequestContext                       │
│  全局异常处理: AppException → 统一 error envelope                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ Auth     │ │ Chat     │ │ Documents│ │ Data     │               │
│  │ Router   │ │ Router   │ │ Router   │ │ Router   │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │ Memory   │ │ Tasks    │ │ Skills   │ │ Admin    │               │
│  │ Router   │ │ Router   │ │ Router   │ │ Router   │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │Database  │ │Metrics   │ │Analytical│ │Cognitive │               │
│  │ Router   │ │ Router   │ │Skills    │ │ Router   │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐               │
│  │Feedback  │ │Enterprise│ │Sandbox   │ │Responses │               │
│  │ Router   │ │Admin     │ │ Router   │ │ Router   │               │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘               │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                  Cognitive Kernel (系统中枢)                          │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  V5 Routing Tier: L0(Rule) → SemanticCache → L1(TinyRouter)  │   │
│  │  工具快速路径: weather/time/tool (绕过完整管线)               │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │              CognitiveExecutive (12+ 阶段认知管线)            │   │
│  │  IntentLock → Rewrite → Understand → Policy → Plan           │   │
│  │  → Constraint → Execute → Evidence → Fuse → Critic           │   │
│  │  → CognitiveIteration → Artifact → Archive                   │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐           │
│  │Runtime  │ │Evidence  │ │Fusion    │ │Critic        │           │
│  │Context  │ │Bus       │ │Engine V2 │ │Engine V2     │           │
│  └─────────┘ └──────────┘ └──────────┘ └──────────────┘           │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐           │
│  │Goal     │ │Governance│ │Capability│ │Cognitive     │           │
│  │Lifecycle│ │Center    │ │Intelligence│ │Supervisor   │           │
│  └─────────┘ └──────────┘ └──────────┘ └──────────────┘           │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐           │
│  │Context  │ │Memory    │ │Self-     │ │Artifact      │           │
│  │Fabric   │ │Fabric    │ │Optimizing│ │Composer      │           │
│  └─────────┘ └──────────┘ └──────────┘ └──────────────┘           │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│               Runtime Gateway → Runtime Turn Dispatcher              │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  cognitive_executive | data_intelligence | multi_goal        │   │
│  └──────────────────────────────────────────────────────────────┘   │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  registry_governance → runtime_tiers → capability_dispatch   │   │
│  └──────────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                     Agent Cluster (智能体集群)                        │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐           │
│  │ Data │ │ RAG  │ │ Web  │ │ Tool │ │Skills│ │Vision│           │
│  │Agent │ │Agent │ │Agent │ │Agent │ │Agent │ │Agent │           │
│  │  V2  │ │      │ │Intel │ │      │ │      │ │      │           │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘           │
│  ┌──────┐ ┌──────┐ ┌──────────────────────────────────────┐     │
│  │Rules │ │Cogni-│ │         AgentRuntimeExecutor          │     │
│  │Agent │ │tive  │ │    (Tier-1 Capability 统一门面)       │     │
│  │      │ │Agent │ └──────────────────────────────────────┘     │
│  └──────┘ └──────┘                                               │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │  Agent Bus (Redis Stream/PubSub) — 分布式 Agent 调度        │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────────┐
│                    Infrastructure (基础设施)                          │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │
│  │Postgres│ │ Redis  │ │DashScope│ │OTel    │ │Sandbox │          │
│  │+pgvector│ │Multi-DB│ │(Qwen)  │ │+Prom   │ │Runtime │          │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘          │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                      │
│  │Celery  │ │RabbitMQ│ │Alembic │ │Email   │                      │
│  │Worker  │ │(aio)   │ │Migrate │ │(SMTP)  │                      │
│  └────────┘ └────────┘ └────────┘ └────────┘                      │
│  ┌────────┐ ┌────────┐ ┌────────┐                                  │
│  │Agent   │ │Message │ │Feature │                                  │
│  │Worker  │ │Bus     │ │Flags   │                                  │
│  └────────┘ └────────┘ └────────┘                                  │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 请求全生命周期

一次完整的用户请求经历以下阶段：

```
1. HTTP/SSE 请求到达 (:14100)
   ├── CORS 中间件
   ├── TenantContext 中间件 (租户头部解析)
   └── RequestContext 中间件 (x-request-id, 响应时间)

2. Chat Router 处理
   ├── 用户认证 (JWT Bearer Token)
   ├── 风险评估 (AdaptiveRiskEngine)
   ├── 附件解析 (文件上传)
   └── 上下文加载 (会话、记忆、偏好)

3. CognitiveKernel 中枢处理
   ├── 意图识别 (IntentEngine)
   ├── V5 快路径检查 (L0 Rule → Semantic Cache → L1 TinyRouter)
   ├── 回合增强 (turn_enrichment: 偏好/记忆/上下文)
   └── 委托 RuntimeGateway

4. RuntimeGateway 路由
   ├── Tier-0 数据库直接路径 (SQL 检索)
   ├── Tier-0 工具快速路径 (天气/时间)
   ├── CognitiveSupervisor.prepare_run
   │   ├── GoalGraph 构建
   │   ├── 治理评估 (风险/证据/策略)
   │   ├── 策略记忆加载
   │   ├── RuntimeContext 构建 (40+ 字段)
   │   ├── 世界状态注入
   │   └── 上下文织物种子
   └── RuntimeTurnDispatcher.run_turn()
       └── runtime.registry → cognitive_executive

5. CognitiveExecutive 认知管线 (12+ 阶段)
   ├── IntentLock (意图锁定)
   ├── Rewrite (查询改写)
   ├── Understand (深度理解)
   ├── Policy (策略评估)
   ├── Plan (认知规划)
   ├── Constraint (约束检查)
   ├── Execute (Agent 执行)
   ├── Evidence (证据收集)
   ├── Rank (证据排序)
   ├── Fuse (证据融合)
   ├── Critic (质量评估)
   ├── Iteration (认知迭代)
   └── Artifact (制品合成)

6. 后处理
   ├── 记忆写入 (Working/Episodic/Semantic)
   ├── 缓存更新 (语义缓存)
   ├── 世界模型终结 (world_turn_finalize)
   └── 回合计费 (enterprise_accounting)

7. 响应
   ├── SSE 流式: delta → final_answer → reasoning_step → execution_graph → error
   └── JSON: ChatResponse (content, citations, evidence_refs, confidence, ...)
```

### 3.3 技术栈

#### 3.3.1 后端技术栈

| 层次 | 技术 | 版本 | 说明 |
|------|------|------|------|
| Web 框架 | FastAPI | ≥0.111.0 | 异步 Web 框架 |
| ASGI 服务器 | Uvicorn | ≥0.29.0 | 高性能 ASGI |
| HTTP 客户端 | httpx | ≥0.27.0 | 异步 HTTP |
| WebSocket | websockets | ≥12.0 | WebSocket 支持 |
| ORM | SQLAlchemy 2.0 (async) | ≥2.0.30 | 异步 ORM |
| 数据库驱动 | asyncpg | ≥0.29.0 | PostgreSQL 异步驱动 |
| MySQL 驱动 | asyncmy | ≥0.2.10 | MySQL 异步驱动 |
| 数据库 | PostgreSQL (asyncpg) + pgvector | ≥0.29.0 | 主数据库 + 向量扩展 |
| 缓存 | Redis (多 DB 分区) | ≥5.0.4 | 分布式缓存 |
| LLM | 阿里巴巴 Qwen 系列 (DashScope API) | openai≥1.30.0, dashscope≥1.20.10 | 多模型路由 |
| 嵌入模型 | text-embedding-v3 (1024 维) | DashScope | 向量嵌入 |
| 重排序 | BAAI/bge-reranker-v2-m3 / 启发式 | DashScope | 结果重排序 |
| 向量检索 | pgvector | ≥0.2.5 | 向量相似度搜索 |
| 认证 | JWT (HS256) | python-jose≥3.3.0 | 无状态认证 |
| 密码哈希 | passlib[bcrypt] | ≥1.7.4 | 密码安全 |
| 可观测性 | OpenTelemetry + Prometheus | ≥1.24.0 | 分布式追踪 + 指标 |
| 数据库迁移 | Alembic | ≥1.13.1 | Schema 版本管理 |
| 任务队列 | Celery (Redis) | ≥5.4.0 | 异步任务 |
| 消息队列 | aio-pika (RabbitMQ) | ≥9.4.1 | 消息中间件 |
| 结构化日志 | structlog | ≥24.2.0 | 结构化日志 |
| 图计算 | NetworkX | ≥3.3 | 图分析与拓扑排序 |
| SQL 解析 | sqlglot | ≥25.0.0 | SQL 方言解析与转换 |
| 数据分析 | NumPy, SciPy, Pandas, Matplotlib, Plotly | — | 数据分析与可视化 |
| 配置管理 | pydantic-settings | ≥2.2.1 | 环境变量配置 |
| 序列化 | pydantic≥2.7.0, orjson≥3.10.3 | — | 数据验证与序列化 |
| 邮件 | aiosmtplib + jinja2 | ≥3.0.1 | 异步邮件发送 |
| CLI | click | ≥8.1.7 | 命令行工具 |
| 重试 | tenacity | ≥8.3.0 | 指数退避重试 |
| Token 计数 | tiktoken | ≥0.7.0 | Token 估算 |

#### 3.3.2 前端技术栈

| 层次 | 技术 | 版本 |
|------|------|------|
| 框架 | React 18 + TypeScript | ^18.3.1 |
| 构建 | Vite 5 | ^5.2.12 |
| 状态管理 | Zustand | ^4.5.2 |
| 路由 | React Router v6 | ^6.23.1 |
| UI | Tailwind CSS + Lucide Icons | ^3.4.4 |
| 图表 | Recharts | ^3.8.1 |
| Markdown | react-markdown + remark-gfm + rehype-raw | ^9.0.1 |
| 代码高亮 | react-syntax-highlighter + Shiki | ^1.12.1 |
| 虚拟滚动 | @tanstack/react-virtual | ^3.10.8 |

#### 3.3.3 开发工具

| 工具 | 用途 |
|------|------|
| pytest | 单元测试 |
| pytest-asyncio | 异步测试 |
| pytest-cov | 覆盖率 |
| black | 代码格式化（line-length=100） |
| ruff | Linting（E, F, I, N, UP） |
| mypy | 类型检查 |
| pre-commit | Git 提交钩子 |
| import-linter | 导入边界检查 |

### 3.4 LLM 模型矩阵

项目把模型按用途拆成 9 组，便于按成本和延迟路由：

| 角色 | 对应模型 | 用途 | temperature | max_tokens |
|------|---------|------|-------------|------------|
| QUERY | qwen3.7-max | 主查询/编排/融合/批评 | 0.0~0.3 | 4096 |
| STRONGEST | qwen3.7-max | 最强推理 | — | — |
| COMPRESS | qwen3.6-plus | 上下文压缩 | 0.0 | 600 |
| PLANNING | qwen3.6-plus | 规划/工具选择 | 0.0 | 400~800 |
| ROUTER | qwen3-1.7b (JuniorShort) | L1 分类 | 0.0 | 100 |
| FAST | qwen3-8b (MiddleShort) | 简单回答 | 0.3 | 200 |
| CHEAP_CRITIC | qwen3.6-plus (SeniorShort) | 轻量批评 | 0.0 | 300 |
| KNOWLEDGE | qwen3.6-plus (SeniorShort) | 知识问答 | 0.3 | 1000 |
| IDENTITY | qwen3-0.6b (MinShort) | 身份响应 | 0.0 | 100 |
| VISION | qwen3.6-vl-plus | 图像/图表理解 | 0.0 | 1500 |

### 3.5 LLM 配置组与环境变量

| 配置前缀 | LLMRole | 环境变量示例 |
|---------|---------|-------------|
| DEFAULT_LLM_STRONGEST_* | STRONGEST | `DEFAULT_LLM_STRONGEST_MODEL=qwen3.7-max` |
| DEFAULT_LLM_QUERY_* | QUERY | `DEFAULT_LLM_QUERY_API_KEY=sk-xxx` |
| DEFAULT_LLM_COMPRESS_* | COMPRESS | `DEFAULT_LLM_COMPRESS_MODEL=qwen3.6-plus` |
| DEFAULT_LLM_PLANING_* | PLANNING | `DEFAULT_LLM_PLANING_PROVIDER=阿里巴巴Qwen(DashScope)` |
| DEFAULT_LLM_SENIORSHORT_* | CHEAP_CRITIC/KNOWLEDGE | `DEFAULT_LLM_SENIORSHORT_MODEL=qwen3.6-plus` |
| DEFAULT_LLM_MIDDLESHORT_* | FAST | `DEFAULT_LLM_MIDDLESHORT_MODEL=qwen3-8b` |
| DEFAULT_LLM_JUNIORSHORT_* | ROUTER | `DEFAULT_LLM_JUNIORSHORT_MODEL=qwen3-1.7b` |
| DEFAULT_LLM_MINSHORT_* | IDENTITY | `DEFAULT_LLM_MINSHORT_MODEL=qwen3-0.6b` |
| DEFAULT_LLM_VISION_* | VISION | `DEFAULT_LLM_VISION_MODEL=qwen3.6-vl-plus` |

### 3.6 完整目录结构

```
opentrace/
├── gateway/                              # API 网关层
│   └── api_gateway/
│       ├── main.py                       # FastAPI 应用入口、中间件、路由注册
│       ├── chat_preflight.py             # 对话预检（企业配额/计费）
│       ├── resource_scope.py             # 资源权限范围
│       ├── tenant_middleware.py           # 多租户中间件
│       ├── tier0_paths.py                # Tier-0 快速路径（SQL 直查）
│       ├── middleware/tenant.py           # 租户上下文中间件
│       └── routers/                      # 25+ 路由模块
│           ├── chat.py                   # 对话接口（核心，SSE 流式，2628 行）
│           ├── auth.py                   # 认证接口（注册/登录/me）
│           ├── conversations.py          # 会话管理（CRUD/归档/分支）
│           ├── data.py                   # 数据查询接口
│           ├── databases.py              # 数据库连接/连通性/schema 同步
│           ├── documents.py              # 文档管理（上传/搜索/详情）
│           ├── admin.py                  # 管理员接口
│           ├── enterprise_admin.py       # 企业管理接口
│           ├── skills.py                 # 技能安装/创建/测试
│           ├── analytical_skills.py      # 分析技能接口
│           ├── tasks.py                  # 任务接口
│           ├── memories.py               # 记忆管理
│           ├── knowledge.py              # 知识库管理
│           ├── metrics.py                # 指标定义/发布/废弃
│           ├── rules.py                  # 规则文件 CRUD
│           ├── connectors.py             # 连接器授权/回调/同步
│           ├── feedback.py               # 反馈收集
│           ├── sandbox.py                # 沙箱文件下载
│           ├── audit.py                  # 审计日志查询/导出
│           ├── cognitive.py              # 认知事件 replay
│           ├── personalization.py        # 个性化设置
│           ├── responses.py              # V2 响应接口
│           ├── table_relationships.py    # 表关系维护
│           ├── ui_settings.py            # UI 设置
│           ├── health.py                 # 健康检查
│           └── prometheus.py             # Prometheus 指标导出
│
├── kernel/                               # 认知内核
│   ├── cognitive_kernel.py               # 内核入口（CognitiveKernel）— 系统唯一中枢
│   ├── runtime_gateway.py                # 运行时网关（RuntimeGateway）— 瘦路由层
│   ├── types.py                          # 基础类型（ExecutionStage, ExecutionNode 等）
│   ├── context_fabric.py                 # 上下文织物门面
│   ├── adaptive_profiles.py              # 自适应画像
│   ├── conversation_state.py             # 对话状态管理
│   ├── history_retriever.py              # 语义历史检索
│   ├── multi_turn_resolution.py          # 多轮解析
│   ├── turn_enrichment.py                # 回合增强
│   ├── refine_planner.py                 # 有界局部重规划
│   ├── semantic_cache.py                 # 语义缓存
│   ├── tiny_router.py                    # L1 TinyRouter
│   ├── query_router_v2.py                # L0 规则路由器
│   ├── plan_agent.py                     # 规划智能体
│   ├── plan_memory.py                    # 规划记忆
│   ├── dag_plan.py                       # DAG 计划
│   ├── dag_scheduler.py                  # DAG 调度器
│   ├── dispatcher.py                     # 分派器
│   ├── token_counter.py                  # Token 计数器
│   ├── clarification_gate.py             # 澄清门控
│   ├── fast_tool_path.py                 # 工具快速路径
│   ├── cognitive_controls.py             # 确定性认知控制
│   ├── result_reference.py               # 结果引用
│   │
│   ├── runtime/                          # 运行时核心
│   │   ├── cognitive_executive.py        # 认知执行器（12+ 阶段管线，1560 行）
│   │   ├── constraint_layer.py           # 约束层（五项确定性检查）
│   │   ├── evidence_bus.py               # 证据总线（生命周期管理）
│   │   ├── fusion.py                     # FusionEngineV2（LLM 驱动语义融合）
│   │   ├── critic.py                     # CriticEngineV2（结构化质量评估）
│   │   ├── context.py                    # RuntimeContext（40+ 字段统一上下文）
│   │   ├── understanding_engine.py       # 理解引擎
│   │   ├── rewrite_engine.py             # 改写引擎
│   │   ├── policy.py                     # UnifiedPolicyEngine
│   │   ├── registry.py                   # 运行时注册表
│   │   ├── registry_governance.py        # 注册表治理
│   │   ├── objects.py                    # RuntimeObject, Evidence, ExecutionPlan
│   │   ├── artifact_composer.py          # 制品合成器
│   │   ├── workspace.py                  # 工作空间管理器
│   │   ├── cognitive_iteration.py        # 认知迭代
│   │   ├── self_optimizing_runtime.py    # 自优化运行时
│   │   ├── multi_question_runtime.py     # 多问题运行时
│   │   ├── finalize_turn.py              # 回合终结
│   │   ├── runtime_turn_dispatcher.py    # 回合分派器
│   │   ├── execution_reasoning.py        # 执行推理追踪
│   │   ├── tier0_paths.py                # Tier-0 路径实现
│   │   ├── cognitive/                    # 认知子模块
│   │   │   ├── cognitive_planner_v2.py   # CognitivePlannerV2
│   │   │   ├── cognitive_graph.py        # 认知图
│   │   │   ├── strategy_builder.py       # 策略构建器
│   │   │   └── execution_projection.py   # 执行投影
│   │   ├── cognitive_state/              # 认知状态子系统
│   │   │   ├── bus.py                    # 认知态统一写路径
│   │   │   ├── store.py                  # 认知态存储
│   │   │   └── state_transition.py       # 状态转换
│   │   ├── evidence/                     # 证据子系统
│   │   │   ├── lifecycle.py              # 证据生命周期
│   │   │   ├── ranking.py                # 证据排序
│   │   │   └── resolution.py             # 证据解析
│   │   ├── memory/                       # 记忆子系统
│   │   │   ├── confidence_decay.py       # 置信度衰减
│   │   │   ├── fact_supersession.py      # 事实取代
│   │   │   └── truth_maintenance.py      # 真值维护
│   │   └── replay/                       # 回放子系统
│   │       ├── runtime_snapshot.py        # 运行时快照
│   │       └── execution_replay.py        # 执行回放
│   │
│   ├── capability_intelligence/          # 能力智能层
│   │   ├── profiler.py                   # 5D 能力画像
│   │   ├── reasoner.py                   # 能力推理器
│   │   ├── knowledge_graph.py            # 能力知识图谱
│   │   ├── execution_memory.py           # 执行记忆
│   │   ├── strategy_memory.py            # 策略记忆
│   │   ├── failure_memory.py             # 失败记忆
│   │   ├── capability_score.py           # 多目标评分
│   │   └── evolution.py                  # 能力演化引擎
│   │
│   ├── goal/                             # 目标系统
│   │   ├── goal_supervisor.py            # 目标监督器
│   │   ├── goal_lifecycle.py             # 目标生命周期
│   │   ├── goal_progress.py              # 目标进度追踪
│   │   ├── goal_recovery.py              # 目标恢复
│   │   ├── goal_driven_planner.py        # 目标驱动规划器
│   │   ├── multi_goal_resources.py       # 多目标资源槽
│   │   └── multi_goal_scheduler.py       # 多目标调度器
│   │
│   ├── governance/                       # 治理系统
│   │   ├── governance_center.py          # GovernanceCenter — 统一治理入口
│   │   ├── risk_governor.py              # 风险治理器
│   │   ├── evidence_governor.py          # 证据治理器
│   │   ├── policy_governor.py            # 策略治理器
│   │   ├── memory_governor.py            # 记忆治理器
│   │   ├── capability_governor.py        # 能力治理器
│   │   └── adaptive_risk_engine.py       # 自适应风险引擎
│   │
│   ├── cognitive_supervisor/             # 认知监督层
│   │   ├── supervisor.py                 # CognitiveSupervisor
│   │   ├── prepare_dispatch.py           # 准备分派
│   │   ├── dispatch_enrichment.py        # 分派增强
│   │   ├── control_plane_gate.py         # 控制平面门控
│   │   └── run_outcomes.py               # 运行结果处理
│   │
│   ├── agent_runtime/                    # Agent Runtime V3
│   │   ├── agent_topology_manifest.yaml  # Agent 拓扑清单（SSOT）
│   │   ├── executor.py                   # AgentRuntimeExecutor
│   │   ├── contribution.py               # AgentContribution
│   │   ├── unified_evidence.py           # 统一证据
│   │   └── cognitive_runtimes.py         # 认知运行时
│   │
│   ├── cognition/                        # 认知域
│   │   ├── world_model.py                # 世界模型
│   │   ├── predictive_world.py           # 预测世界
│   │   └── runtime_grounding.py          # 运行时接地
│   │
│   ├── protocol/                         # 协议层
│   │   ├── runtime_contract.py           # 运行时契约
│   │   ├── cognition_protocol.py         # 认知协议
│   │   └── agent_protocol.py             # 智能体协议
│   │
│   ├── data_cognition/                   # 数据认知
│   │   ├── semantic_layer.py             # 语义层
│   │   ├── sql_planner.py                # SQL 规划器
│   │   ├── sql_builder.py                # SQL 构建器
│   │   └── sql_validator.py              # SQL 验证器
│   │
│   ├── prompt_engine/                    # 提示词引擎
│   ├── web_engine/                       # Web 引擎
│   ├── tools/                            # 内核工具
│   ├── epistemology/                     # 认识论
│   ├── reasoning/                        # 推理引擎
│   ├── policy/                           # 策略引擎
│   ├── meta_cognition/                   # 元认知
│   ├── intent_engine/                    # 意图引擎
│   └── identity/                         # 系统身份
│
├── agents/                               # 智能体集群
│   ├── base.py                           # AgentBase, AgentResult, TaskMessage
│   ├── bootstrap.py                      # 智能体引导注册
│   ├── registry.py                       # AgentRegistry
│   ├── worker.py                         # Agent Worker
│   ├── rag_agent.py                      # RAG 检索智能体
│   ├── data_agent.py                     # DataAgent 包装
│   ├── data_agent_v2/                    # DataAgent V2 认知管线
│   │   ├── supervisor.py                 # 监督器
│   │   ├── error_classifier.py           # 错误分类器
│   │   ├── types.py                      # 类型定义
│   │   ├── knowledge_retriever.py        # 知识检索
│   │   ├── planner_agent.py              # 规划代理
│   │   ├── sql_compiler_agent.py         # SQL 编译
│   │   ├── verification_agent.py         # 验证代理
│   │   ├── reflection_agent.py           # 反思代理
│   │   ├── insight_agent.py              # 洞察代理
│   │   ├── statistical_agent.py          # 统计代理
│   │   └── ...                           # 25+ 子代理
│   ├── web_agent.py                      # Web 搜索智能体
│   ├── web_intelligence_agent.py         # Web Intelligence 智能体
│   ├── tool_agent.py                     # 工具调用智能体
│   ├── cognitive_agent.py                # 认知智能体
│   ├── vision_agent.py                   # 视觉分析智能体
│   ├── skills_agent.py                   # 技能执行智能体
│   └── rule_engine_agent.py              # 规则引擎智能体
│
├── memory/                               # 记忆系统
│   ├── working_memory/                   # 工作记忆
│   ├── episodic_memory/                  # 情景记忆
│   ├── semantic_memory/                  # 语义记忆
│   ├── procedural_memory/                # 程序记忆
│   ├── temporal_memory/                  # 时间记忆
│   ├── memory_router/                    # 记忆路由
│   ├── fabric/                           # 记忆织物
│   └── evolution/                        # 记忆进化
│
├── model/                                # 模型层
│   ├── model_gateway/gateway.py          # ModelGateway + LLMRole 枚举
│   ├── llm_adapter/                      # LLM 适配器
│   ├── embedding/                        # 嵌入模型
│   └── reranker/                         # 重排序模型
│
├── infra/                                # 基础设施
│   ├── config/settings.py                # 全局配置（32825 行）
│   ├── storage/database.py               # 数据库连接
│   ├── storage/models.py                 # ORM 模型（65604 行）
│   ├── cache/redis_client.py             # Redis 客户端
│   ├── cache/redis_shadow_store.py       # ShadowRedis
│   ├── message_bus/                      # 消息总线
│   ├── observability/                    # 可观测性
│   ├── security/zero_trust.py            # 零信任安全
│   ├── errors/                           # 错误码
│   └── guards/                           # 内核守卫
│
├── plugins/                              # 插件系统
│   ├── base.py                           # 插件基类
│   ├── code/interpreter.py               # 代码解释器
│   ├── chart/generator.py                # 图表生成器
│   ├── file/sandbox.py                   # 文件沙箱
│   └── data/analysis.py                  # 数据分析
│
├── safety/                               # 安全系统
│   ├── masking/ner_masker.py             # NER 脱敏
│   ├── guardrails/guardrails.py          # 安全护栏
│   └── policy_engine/engine.py           # 安全策略引擎
│
├── skills/                               # 技能系统
│   ├── store/marketplace.py              # 技能市场
│   └── runtime/                          # 技能运行时
│
├── connectors/                           # 连接器
│   ├── registry.py                       # 连接器注册表
│   └── sdk/protocol.py                   # 连接器协议
│
├── tenant/                               # 多租户
│   ├── tenant_manager.py                 # 租户管理
│   ├── quota_manager.py                  # 配额管理
│   ├── billing_manager.py                # 计费管理
│   ├── usage_metering.py                 # 用量计量
│   └── workspace_manager.py              # 工作空间管理
│
├── services/                             # 服务层
│   ├── data_intelligence_runtime/        # 数据认知运行时
│   └── document/                         # 文档服务
│
├── control_plane/                        # 控制平面
├── execution/                            # 执行平面
│   ├── dag_engine/                       # DAG 引擎
│   └── workflow_engine/                  # 工作流引擎
│
├── docs/                                 # 文档
│   ├── service/service_trae.md           # 本文档
│   ├── ARCHITECTURE_REQUIREMENTS_MATRIX.md
│   └── adr/                              # 架构决策记录
│
├── scripts/                              # 脚本
│   ├── run_vnext_final_tests.sh
│   └── report_v4_imports.sh
│
├── tests/                                # 测试
├── frontend/                             # 前端应用
├── docker-compose.yml                    # Docker Compose 配置
├── Dockerfile                            # Docker 镜像
├── start.sh                              # 启动脚本
├── .env.example                          # 环境变量模板
├── pyproject.toml                        # Python 项目配置
└── README.md                             # 项目自述文件
```

---

# Part II: API 网关

## Chapter 4: 网关架构

### 4.1 概述

API 网关是整个 OpenTrace 系统的对外入口，基于 FastAPI 构建，负责所有 HTTP/SSE 请求的接收、路由、认证和中间件处理。网关运行在端口 **14100**，采用前后缀一致的 API 版本策略（`/api/v1` 和 `/api/v2`）。

源文件：`gateway/api_gateway/main.py` — 158 行

### 4.2 FastAPI 应用初始化

```python
app = FastAPI(title="OpenTrace API", version="0.1.0")
```

应用启动时（`@app.on_event("startup")`）执行：
1. **注册内置 Agent**：`register_builtin_agents()` 将 agents/ 目录下的所有 Agent 工厂注册到能力注册表
2. **确保运行时 Schema**：`ensure_runtime_schema()` 验证数据库表结构
3. **启动内存事件订阅器**：`memory_event_subscriber.start()` 异步订阅 Redis Pub/Sub 中的内存事件流

应用关闭时（`@app.on_event("shutdown")`）：
1. 停止内存事件订阅器
2. 取消未完成的异步任务

### 4.3 中间件栈

请求流经三层中间件，顺序如下：

```
Request → CORS 中间件 → TenantContext 中间件 → RequestContext 中间件 → Router
```

#### 4.3.1 CORS 中间件

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

- 允许的来源列表由 `CORS_ORIGIN_LIST` 环境变量配置（逗号分隔）
- 允许携带凭证（Cookie / Authorization header）
- 开发环境通常配置为 `http://localhost:14108`

#### 4.3.2 TenantContext 中间件

```python
from gateway.api_gateway.middleware.tenant import TenantContextMiddleware
app.add_middleware(TenantContextMiddleware)
```

- 解析请求头中的租户信息（`x-tenant-id`、`x-workspace-id`）
- 将租户上下文注入到 `request.state` 中
- 如果加载失败，记录警告日志但不阻断请求

#### 4.3.3 RequestContext 中间件

```python
@app.middleware("http")
async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    t0 = time.time()
    response = await call_next(request)
    response.headers["x-request-id"] = request_id
    response.headers["x-response-time-ms"] = str(int((time.time() - t0) * 1000))
    return response
```

- 每个请求分配唯一 `request_id`（优先使用客户端传入的 `x-request-id`）
- 记录响应时间并注入 `x-response-time-ms` 响应头
- 所有错误响应中携带 `request_id` 便于追踪

### 4.4 全局异常处理

#### 4.4.1 AppException 处理

所有业务异常继承自 `AppException`，统一的错误响应格式：

```json
{
    "code": "ERROR_CODE",
    "message": "人类可读的错误消息",
    "details": "可选的详细信息",
    "request_id": "uuid",
    "timestamp": 1234567890
}
```

#### 4.4.2 未处理异常兜底

```python
@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    spec = ErrorCodes.INTERNAL_ERROR
    payload = {
        "code": spec.code,
        "message": spec.message,
        "details": str(exc) if settings.debug and settings.app_env == "development" else None,
        "request_id": request_id,
        "timestamp": int(time.time()),
    }
```

- 生产环境不暴露异常详情（`details` 为 `null`）
- 开发环境在 `debug=True` 时返回异常堆栈

### 4.5 路由注册

所有路由器通过 `app.include_router()` 注册，按功能分组：

| 前缀 | 路由模块 | 标签 | 说明 |
|------|---------|------|------|
| `/api/v1` | health | health | 健康检查 |
| `/api/v1` | prometheus | observability | Prometheus 指标 |
| `/api/v1` | auth | auth | 认证 |
| `/api/v1` | chat | chat | 核心对话 |
| `/api/v2` | responses | responses | V2 响应接口 |
| `/api/v1` | personalization | personalization | 个性化设置 |
| `/api/v1` | conversations | conversations | 会话管理 |
| `/api/v1` | cognitive | cognitive | 认知事件重放 |
| `/api/v1` | documents | documents | 文档管理 |
| `/api/v1` | knowledge | knowledge | 知识库 |
| `/api/v1` | memories | memories | 记忆管理 |
| `/api/v1` | tasks | tasks | 任务调度 |
| `/api/v1` | audit | audit | 审计日志 |
| `/api/v1` | connectors | connectors | 连接器 |
| `/api/v1` | skills | skills | 技能管理 |
| `/api/v1` | ui_settings | ui_settings | UI 设置 |
| `/api/v1` | data | data | 数据查询 |
| `/api/v1` | databases | databases | 数据库连接 |
| `/api/v1` | feedback | feedback | 用户反馈 |
| `/api/v1` | sandbox | sandbox | 沙箱文件 |
| `/api/v1` | admin | admin | 管理员 |
| `/api/v1` | enterprise_admin | enterprise-admin | 企业管理 |
| `/api/v1` | rules | rules | 规则文件 |
| `/api/v1` | metrics | metrics | 指标定义 |
| `/api/v1` | table_relationships | table-relationships | 表关系 |
| `/api/v1` | analytical_skills | analytical-skills | 分析技能 |

---

## Chapter 5: 认证 API

### 5.1 概述

源文件：`gateway/api_gateway/routers/auth.py` — 243 行

认证系统基于 JWT（HS256 算法）实现无状态认证，使用 `python-jose` 库进行 Token 签发与验证，使用 `passlib[bcrypt]` 进行密码哈希。

### 5.2 核心组件

```python
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")
```

- **密码哈希**：`_hash(password)` 使用 bcrypt 算法
- **密码验证**：`_verify(plain, hashed)` 验证明文与哈希
- **Token 创建**：`_create_token(user_id, email)` 签发 JWT，过期时间由 `JWT_EXPIRE_MINUTES` 配置

### 5.3 端点列表

#### 5.3.1 POST `/api/v1/auth/register` — 用户注册

**请求体** (`RegisterRequest`)：
```json
{
    "email": "user@example.com",
    "password": "optional_password",
    "display_name": "可选显示名"
}
```

**处理流程**：
1. 检查 `registration_enabled` 配置
2. 验证邮箱域名（`_validate_email_domain`）
3. 检查邮箱是否已注册
4. 开发环境自动激活（`dev_registration_auto_activate=True`）
5. 生产环境创建 `pending` 状态用户，异步通知管理员审核

**响应** (`RegisterResponse`)：
```json
{
    "message": "注册申请已提交，请耐心等待管理员审核。",
    "email": "user@example.com"
}
```

#### 5.3.2 POST `/api/v1/auth/token` — OAuth2 表单登录

**请求格式**：`application/x-www-form-urlencoded`（OAuth2 标准）
- `username`: 邮箱
- `password`: 密码

**响应** (`LoginResponse`)：
```json
{
    "access_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "user_id": "uuid",
    "email": "user@example.com",
    "display_name": "显示名",
    "role": "user"
}
```

#### 5.3.3 POST `/api/v1/auth/login` — JSON 登录

与 `/auth/token` 功能相同，但接受 JSON 格式的 `RegisterRequest` 请求体，适用于 Web 前端。

#### 5.3.4 GET `/api/v1/auth/me` — 获取当前用户信息

**认证**：Bearer Token（通过 `get_current_user` 依赖注入）

**响应** (`UserMe`)：
```json
{
    "user_id": "uuid",
    "email": "user@example.com",
    "display_name": "显示名",
    "is_superuser": false,
    "role": "user",
    "status": "active",
    "created_at": "2024-01-01T00:00:00"
}
```

### 5.4 认证依赖注入

```python
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    user_id = payload.get("sub", "")
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user or user.status != "active":
        raise AppException(ErrorCodes.AUTH_INTERNAL_ERROR.code)
    return user
```

- 所有需要认证的端点通过 `Depends(get_current_user)` 注入当前用户
- Token 无效或用户状态非 `active` 时返回 401

### 5.5 JWT 配置

| 配置项 | 环境变量 | 默认值 |
|--------|---------|--------|
| 密钥 | `JWT_SECRET` | （必填） |
| 算法 | `JWT_ALGORITHM` | HS256 |
| 过期时间 | `JWT_EXPIRE_MINUTES` | 1440（24h） |

---

## Chapter 6: Chat API

### 6.1 概述

源文件：`gateway/api_gateway/routers/chat.py` — 2628 行（最大单文件）

Chat API 是系统的核心端点，所有用户对话请求经此进入 CognitiveKernel。支持 **SSE 流式响应** 和 **同步 JSON 响应** 两种模式。

### 6.2 核心请求模型

```python
class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=8192)
    session_id: str | None = None
    stream: bool = False
    memory_mode: str = Field(default="enabled", pattern="^(enabled|disabled|temporary)$")
    web_enabled: bool = False
    request_id: str | None = None
    graph_controls: dict[str, Any] = Field(default_factory=dict)
    enabled_skills: list[str] = Field(default_factory=list)
    disabled_skills: list[str] = Field(default_factory=list)
    tool_permission_token: str | None = None
    confirmation_granted: bool = False
    data_source_id: str | None = None
    data_source_name: str | None = None
    force_database: bool = False
    force_mode: str | None = Field(
        default=None,
        pattern="^(rag|data_query|data_analysis|anomaly_tracking|product|rule_engine|vision)$",
    )
    # 多轮对话增强字段
    clarify_context: str | None = None
    clarify_question_id: str | None = None
    parent_message_id: str | None = None
    attachment_ids: list[str] | None = None
    reference_id: str | None = None
    reference_type: str | None = None
    state_version: int | None = None
    knowledge: KnowledgeControl = Field(default_factory=KnowledgeControl)
```

#### 关键字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | str (1-8192) | 用户查询文本 |
| `stream` | bool | 是否使用 SSE 流式响应 |
| `memory_mode` | enum | `enabled`/`disabled`/`temporary` |
| `web_enabled` | bool | 是否启用联网搜索 |
| `force_mode` | enum | 强制指定执行模式（rag/data_query/vision 等） |
| `tool_permission_token` | str | 零信任安全：工具调用权限 Token |
| `confirmation_granted` | bool | 用户确认危险操作的标记 |
| `knowledge` | KnowledgeControl | 知识控制参数（action/scope/attachment_ids 等） |

### 6.3 核心响应模型

```python
class ChatResponse(BaseModel):
    session_id: str
    content: str
    decision_type: str = "direct"
    validation_score: float = 1.0
    passed_validation: bool = True
    intent_category: str = "qa"
    context_latency_ms: int = 0
    total_latency_ms: int = 0
    citations: list[dict[str, Any]] = Field(default_factory=list)
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    annotations: list[dict[str, Any]] = Field(default_factory=list)
    execution_graph: dict[str, Any] | None = None
    result_refs: list[dict[str, Any]] = Field(default_factory=list)
    state_version: int = 1
    knowledge_operations: list[dict[str, Any]] = Field(default_factory=list)
    confidence: float | None = None
    confidence_level: str | None = None
    uncertainty: list[str] = Field(default_factory=list)
    trace_id: str | None = None
```

### 6.4 端点列表

#### 6.4.1 POST `/api/v1/chat` — 核心对话（SSE 流式）

**请求流程**（预检）：
```
1. 用户认证 (get_current_user)
2. 风险评估 (assess_query_risk)
3. 权限 Token 验证 (validate_permission_token)
4. 会话创建/确认 (_ensure_session)
5. 附件解析 (parse_attachment_content)
6. 上下文加载 (记忆/偏好/自定义指令/数据源)
7. 委托 CognitiveKernel
```

**SSE 事件类型**：

| 事件 | 说明 |
|------|------|
| `delta` | 流式文本增量 |
| `final_answer` | 最终回答 |
| `reasoning_step` | 推理步骤 |
| `execution_graph` | 执行图可视化 |
| `error` | 错误信息 |
| `tool_permission_required` | 需要工具调用确认 |
| `clarification` | 需要澄清 |

#### 6.4.2 POST `/api/v1/chat/sync` — 同步对话

不使用 SSE 流式，直接返回 `ChatResponse` JSON。

#### 6.4.3 POST `/api/v1/chat/attachments` — 上传附件

**请求格式**：`multipart/form-data`
- `file`: 上传文件
- `session_id`: 会话 ID

**响应** (`AttachmentUploadResponse`)：
```json
{
    "attachment_id": "uuid",
    "content_summary": "文件内容摘要",
    "content_hash": "sha256",
    "is_duplicate": false,
    "scope": "session",
    "ingest_status": "temporary"
}
```

#### 6.4.4 GET `/api/v1/chat/attachments/{session_id}` — 获取会话附件列表

**响应** (`AttachmentListResponse`)：
```json
{
    "session_id": "uuid",
    "attachments": [...],
    "total": 3
}
```

#### 6.4.5 POST `/api/v1/chat/stop` — 停止流式响应

请求体：`StopStreamRequest(session_id, request_id)`

#### 6.4.6 POST `/api/v1/chat/resume` — 从断点恢复

请求体：`ResumeRequest(session_id, step_index)`

#### 6.4.7 POST `/api/v1/chat/regenerate` — 重新生成回答

请求体：`RegenerateRequest(session_id, stream, web_enabled)`

#### 6.4.8 POST `/api/v1/chat/edit-regenerate` — 编辑消息后重新生成

请求体：`EditRegenerateRequest(session_id, message_id, new_content, stream, web_enabled)`

#### 6.4.9 POST `/api/v1/chat/feedback` — 提交对话反馈

请求体：`ChatFeedbackRequest(session_id, chunk_id, message_id, feedback_type, score, correction)`

#### 6.4.10 POST `/api/v1/chat/branch` — 创建对话分支

#### 6.4.11 POST `/api/v1/chat/graph-control` — 控制执行图

请求体：`GraphControlRequest(session_id, request_id, action, node_id)`
- `action`: `prune`（剪枝）或 `expand`（展开）

### 6.5 预检与安全流程

Chat API 在将请求委托给 CognitiveKernel 之前执行完整的预检流程：

```
认证 → 风险评估 → 权限 Token → 会话确认 → 附件解析 → 上下文加载 → 内核委托
```

#### 风险评估（零信任安全）

```python
from infra.security.zero_trust import assess_query_risk
risk = assess_query_risk(query)
```

#### 输出安全层

所有 Assistant 输出在持久化和 SSE 传输前经过安全护栏：

```python
def _sanitize_assistant_output(text: str) -> str:
    from safety.guardrails.guardrails import guardrails
    result = guardrails.check_output(text or "")
    return result.sanitized if result.sanitized is not None else (text or "")
```

### 6.6 上下文加载机制

Chat API 在请求处理中加载多层上下文：

1. **对话历史**：`_load_conversation_history()` 从 Message 表或 TraceLog 表加载
2. **上一轮上下文**：`_load_previous_turn_context()` 加载上一轮的 plan 和 agent_results
3. **分支检查点**：`_load_branch_checkpoint()` 从 TraceLog 加载分支规划
4. **用户偏好记忆**：`_load_user_memory_preferences()` 加载分层偏好（Explicit > Behavioral > Project > Session）
5. **自定义指令**：`_load_custom_instruction_block()` 加载用户显式指令
6. **数据源上下文**：`_load_data_source_context()` 按名称匹配或显式指定数据源

---

## Chapter 7: Conversations API

### 7.1 概述

源文件：`gateway/api_gateway/routers/conversations.py`

会话管理 API 提供完整的 CRUD 操作，支持归档、分支和消息历史查询。

### 7.2 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/conversations` | 列出用户的所有会话 |
| POST | `/api/v1/conversations` | 创建新会话 |
| GET | `/api/v1/conversations/{id}` | 获取会话详情 |
| PATCH | `/api/v1/conversations/{id}` | 重命名会话 |
| POST | `/api/v1/conversations/{id}/archive` | 归档会话 |
| POST | `/api/v1/conversations/{id}/unarchive` | 取消归档 |
| DELETE | `/api/v1/conversations/{id}` | 删除会话 |
| GET | `/api/v1/conversations/{id}/messages` | 获取消息历史（分页） |
| POST | `/api/v1/conversations/{id}/branch` | 创建分支 |

### 7.3 推理步骤标准化

Conversations API 包含推理步骤的标准化处理（`_normalize_reasoning_steps`），将不同格式的推理步骤（REASON / DECIDE / EXECUTE / OBSERVE / REFLECT）统一为前端可渲染的格式：

```python
def _normalize_reasoning_steps(raw: object) -> list[dict]:
    # 统一处理 REASON / DECIDE / EXECUTE / OBSERVE / REFLECT 等多种步骤类型
    # 提取 tool name、status、preview 等信息
```

---

## Chapter 8: Data & Database API

### 8.1 概述

Data API 和 Database API 提供数据查询和数据库连接管理功能。

源文件：
- `gateway/api_gateway/routers/data.py` — 数据查询
- `gateway/api_gateway/routers/databases.py` — 数据库连接管理
- `gateway/api_gateway/routers/table_relationships.py` — 表关系维护

### 8.2 Data API 端点

#### 8.2.1 POST `/api/v1/data/query` — 数据查询

**请求体** (`DataQueryRequest`)：
```json
{
    "question": "上个月销售额最高的10个产品是什么？",
    "data_source_id": "uuid",
    "dry_run": false,
    "sql": null,
    "limit": 10,
    "offset": 0,
    "order_by": null,
    "order_dir": null,
    "filters": null,
    "session_id": null,
    "clarify_context": null,
    "session_context": null
}
```

**处理流程**：
1. 验证数据源归属（`get_owned_data_source`）
2. 加载 Schema 检查结果
3. **DataAgent V2 路径**（`data_agent_v2_enabled=True`）：
   - 构建 DSN 连接
   - 构建 Schema 提示
   - 创建 TaskMessage 委托 DataAgent
4. **传统路径**：SQLPlanner → SQLRewriter → SQLValidator → SQLExecutor

**执行管线**：
```
SemanticLayer → SQLPlanner → SQLRewriter → SQLRanker → SQLValidator → SQLExecutor
```

### 8.3 Database API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/databases` | 创建数据源连接 |
| GET | `/api/v1/databases` | 列出用户的数据源 |
| GET | `/api/v1/databases/{id}` | 获取数据源详情 |
| PUT | `/api/v1/databases/{id}` | 更新数据源配置 |
| DELETE | `/api/v1/databases/{id}` | 删除数据源 |
| POST | `/api/v1/databases/{id}/test` | 测试连通性 |
| POST | `/api/v1/databases/{id}/sync` | 同步 Schema |
| POST | `/api/v1/databases/{id}/query` | 直接执行 SQL |

**支持的数据源类型**：`mysql`、`clickhouse`、`doris`、`postgres`

**密码安全**：数据源密码使用 `encrypt_data_source_secret` 加密存储，使用时通过 `decrypt_data_source_secret` 解密。

**Schema 同步**：根据不同的数据源类型使用对应的系统表查询：
- ClickHouse：`system.tables` + `system.columns`
- Doris：`information_schema.tables` + `information_schema.columns`
- MySQL/PostgreSQL：`information_schema.tables` + `information_schema.columns`

---

## Chapter 9: Documents API

### 9.1 概述

源文件：`gateway/api_gateway/routers/documents.py`

文档管理 API 支持文档的上传、分块、向量化、检索和删除。文档经分块（chunking）后嵌入为向量存储于 pgvector，供 RAGAgent 检索。

### 9.2 分块策略

```python
CHUNK_SIZE = 512      # 目标分块大小（字符）
CHUNK_OVERLAP = 64    # 分块重叠（字符）
CHUNK_MAX_CHARS = 800 # 上下文感知分块软上限
CHUNK_MIN_CHARS = 80  # 最小句子组大小
```

### 9.3 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/documents` | 列出用户文档 |
| POST | `/api/v1/documents` | 上传文档（multipart） |
| GET | `/api/v1/documents/{id}` | 文档详情（含内容预览） |
| PUT | `/api/v1/documents/{id}` | 重新上传/更新标题 |
| DELETE | `/api/v1/documents/{id}` | 删除文档及所有分块 |
| POST | `/api/v1/documents/search` | 语义搜索 |

**搜索请求** (`SearchRequest`)：
```json
{
    "query": "如何配置数据库连接",
    "top_k": 6
}
```

**搜索响应** (`SearchResult`)：
```json
{
    "document_id": "uuid",
    "title": "配置指南",
    "chunk_index": 3,
    "content": "匹配的文本片段...",
    "score": 0.92,
    "metadata": {}
}
```

### 9.4 文本质量评估

文档上传后使用启发式文本质量评分（`_text_quality_score`）评估可读性，确保只有高质量文本被向量化。

---

## Chapter 10: Knowledge API

### 10.1 概述

源文件：`gateway/api_gateway/routers/knowledge.py`

知识管理 API 提供对知识资产（Knowledge Assets）的治理，包括知识源、版本、规则、声明、编译任务、Lint 检查、合并案例和演化建议。

### 10.2 核心数据模型

| 模型 | 说明 |
|------|------|
| `KnowledgeSource` | 知识源（文档/数据库/API） |
| `KnowledgeSourceVersion` | 知识源版本 |
| `KnowledgeRule` | 知识规则（schema/validation） |
| `KnowledgeClaim` | 知识声明 |
| `KnowledgeCompilationJob` | 编译任务 |
| `KnowledgeLintIssue` | Lint 问题 |
| `KnowledgeMergeCase` | 合并冲突案例 |
| `KnowledgeFeedback` | 知识反馈 |
| `KnowledgePage` | 知识页面 |
| `KnowledgeRelation` | 知识关系 |

### 10.3 端点列表

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/knowledge/sources` | 列出知识源 |
| GET | `/api/v1/knowledge/sources/{id}/versions` | 列出知识源版本 |
| POST | `/api/v1/knowledge/rules` | 创建/更新知识规则 |
| GET | `/api/v1/knowledge/rules` | 列出知识规则 |
| POST | `/api/v1/knowledge/compile` | 触发编译任务 |
| GET | `/api/v1/knowledge/compile/{job_id}` | 查询编译任务状态 |
| POST | `/api/v1/knowledge/lint` | 运行 Lint 检查 |
| POST | `/api/v1/knowledge/merge/resolve` | 解决合并冲突 |
| POST | `/api/v1/knowledge/evolution/propose` | 生成演化建议 |
| POST | `/api/v1/knowledge/feedback` | 提交知识反馈 |
| POST | `/api/v1/knowledge/trace` | 追溯知识资产 |

---

## Chapter 11: 其他 API

### 11.1 Memories API

源文件：`gateway/api_gateway/routers/memories.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/memories` | 列出用户记忆（可按 `memory_type` 过滤） |
| POST | `/api/v1/memories` | 创建记忆 |
| GET | `/api/v1/memories/{id}` | 获取记忆详情 |
| PUT | `/api/v1/memories/{id}` | 更新记忆 |
| DELETE | `/api/v1/memories/{id}` | 删除记忆 |
| GET | `/api/v1/memories/settings` | 获取记忆设置 |
| PUT | `/api/v1/memories/settings` | 更新记忆设置 |

**记忆类型**：`semantic`、`episodic`、`procedural`

**记忆设置**：
```json
{
    "memory_learning_enabled": true,
    "preference_learning_enabled": true
}
```

### 11.2 Tasks API

源文件：`gateway/api_gateway/routers/tasks.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/tasks` | 创建定时/事件触发任务 |
| GET | `/api/v1/tasks` | 列出任务 |
| POST | `/api/v1/tasks/{id}/run` | 手动执行任务 |
| POST | `/api/v1/tasks/{id}/pause` | 暂停任务 |
| POST | `/api/v1/tasks/{id}/resume` | 恢复任务 |
| DELETE | `/api/v1/tasks/{id}` | 删除任务 |

**任务调度解析**：从自然语言描述中解析调度规则：
- "每小时" → `interval: 3600s`
- "每天" → `cron: 8:00`
- "当..." → `event: external_trigger`

### 11.3 Skills API

源文件：`gateway/api_gateway/routers/skills.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/skills` | 列出已安装技能（管理员） |
| POST | `/api/v1/skills/install` | 从 Git 安装技能 |
| POST | `/api/v1/skills/create` | 创建自定义技能 |
| POST | `/api/v1/skills/{id}/test` | 测试技能 |
| DELETE | `/api/v1/skills/{id}` | 卸载技能 |
| POST | `/api/v1/skills/session-binding` | 绑定技能到会话 |
| GET | `/api/v1/skills/session-binding` | 查询会话技能绑定 |

### 11.4 Admin API

源文件：`gateway/api_gateway/routers/admin.py`

所有管理员端点需要 `get_current_admin_user` 依赖（`role == "admin"` 或 `is_superuser`）。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/users` | 列出所有用户（可按 status 过滤） |
| POST | `/api/v1/admin/users/{id}/approve` | 审核通过用户 |
| POST | `/api/v1/admin/users/{id}/disable` | 禁用用户 |
| POST | `/api/v1/admin/users/{id}/enable` | 启用用户 |
| POST | `/api/v1/admin/learning/run` | 手动触发学习引擎 |

### 11.5 Enterprise Admin API

源文件：`gateway/api_gateway/routers/enterprise_admin.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/enterprise/tenants` | 列出所有租户 |
| POST | `/api/v1/admin/enterprise/tenants/{id}/quota` | 设置租户配额 |
| GET | `/api/v1/admin/enterprise/control-plane/health` | 控制平面健康检查 |
| GET | `/api/v1/admin/enterprise/capabilities/marketplace` | 能力市场 |
| GET | `/api/v1/admin/enterprise/compliance/audit` | 合规审计 |
| GET | `/api/v1/admin/enterprise/usage/{tenant_id}` | 租户用量摘要 |

### 11.6 Sandbox API

源文件：`gateway/api_gateway/routers/sandbox.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/sandbox/download` | 下载沙箱文件 |

- 验证会话归属权限
- 路径安全校验（`resolve_readable_sandbox_file`）
- 返回 `application/octet-stream` 文件流

### 11.7 Feedback API

源文件：`gateway/api_gateway/routers/feedback.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/feedback` | 提交反馈（用于数据飞轮） |

**反馈类型**：`like`、`dislike`、`correction`、`rating`

反馈数据通过 `FeedbackCollector` 收集，并发布到 `cognitive_event_bus` 供数据飞轮消费。

### 11.8 Connectors API

源文件：`gateway/api_gateway/routers/connectors.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/connectors/authorize` | OAuth 授权（生成 state） |
| POST | `/api/v1/connectors/callback` | OAuth 回调 |
| GET | `/api/v1/connectors` | 列出已连接的服务 |
| GET | `/api/v1/connectors/{provider}/resources` | 列出资源（分页） |
| DELETE | `/api/v1/connectors/{provider}` | 断开连接 |

**凭证安全**：连接器凭证使用 `encrypt_connector_credential` / `decrypt_connector_credential` 加密存储。

### 11.9 Audit API

源文件：`gateway/api_gateway/routers/audit.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/audit/logs` | 查询审计日志（按时间范围/操作过滤） |
| GET | `/api/v1/audit/logs/export` | 导出 CSV 格式审计日志 |

### 11.10 Cognitive API

源文件：`gateway/api_gateway/routers/cognitive.py`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/cognitive-events/replay` | 按 trace_id 重放认知事件 |

- 支持按事件类型过滤
- 管理员权限

### 11.11 Health API

源文件：`gateway/api_gateway/routers/health.py` — 177 行

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 基础健康检查（status/version/uptime） |
| GET | `/api/v1/health/deps` | 依赖健康检查（DB/Redis/Agent Bus/Worker） |
| GET | `/api/v1/health/runtime` | 运行时认知健康（WorldModel/指标/自适应模式） |
| GET | `/api/v1/health/cognitive-os` | vNext 就绪检查（Flag 验证/Tier-1 运行时） |
| GET | `/api/v1/ping` | 简单存活检查 |

**依赖健康检查逻辑**：
- PostgreSQL：执行 `SELECT 1`
- Redis：执行 `PING`，检查 Worker 心跳（45s 超时）
- Agent Bus：检查 Stream 模式 vs PubSub 模式
- 综合状态：`ok` / `degraded` / `down`

### 11.12 其他小端点

| 路由 | 路径 | 说明 |
|------|------|------|
| prometheus | `/api/v1/metrics` | Prometheus 指标导出 |
| personalization | `/api/v1/personalization` | 个性化设置 |
| rules | `/api/v1/rules` | 规则文件 CRUD |
| metrics | `/api/v1/metrics/definitions` | 指标定义管理 |
| responses | `/api/v2/responses` | V2 响应格式接口 |
| ui_settings | `/api/v1/ui-settings` | UI 偏好设置 |
| analytical_skills | `/api/v1/analytical-skills` | 分析技能管理 |

---

# Part III: 认知内核

## Chapter 12: 内核架构

### 12.1 概述

源文件：`kernel/cognitive_kernel.py` — 875 行

CognitiveKernel 是 OpenTrace 系统的**唯一中枢**。所有用户请求必须经过内核处理，不允许任何模块直接调用 LLM 或绕过内核执行认知任务。

### 12.2 四大核心原则

```python
"""
核心原则:
  1. 所有输出必须由认知内核生成
  2. 所有插件返回的数据只是「候选认知材料」
  3. LLM 不是回答器，而是「认知执行器」
  4. Prompt 不是模板，而是「认知协议（Cognitive Protocol）」
"""
```

### 12.3 多 Prompt 链执行流

内核采用"多 Prompt 链 + 并行插件执行"的核心逻辑：

```
Step 1: intent_prompt  — 意图识别（PLANNING 小模型，<100ms）
Step 2: plan_prompt    — 任务规划（PLANNING 小模型）
Step 3: tool_select    — 工具选择（PLANNING 小模型）
         + asyncio.gather(memory, doc, web) 并行执行插件
Step 4: reasoning      — 推理生成（QUERY 大模型，五层 Prompt）
Step 5: reflection     — 反思优化（QUERY 大模型）
Step 6: meta_cognition — 质量门控（三级）
Step 7: memory.store() — 异步写回（不阻塞响应）
```

### 12.4 内核入口：CognitiveKernel.run()

```python
class CognitiveKernel:
    async def run(self, request: KernelRequest) -> KernelResponse:
        """同步执行：支持 v1/v2 编排器分流。"""
```

**处理流程**：

1. **意图识别**：使用 IntentEngine 或 `classify_intent` 分类用户意图
2. **身份查询快速路径**：判定是否为"你是谁"类问题，走缓存或 IDENTITY 模型
3. **V5 路由检查**：L0 规则路由 → 语义缓存 → L1 TinyRouter
4. **工具快速路径**：天气/时间/计算器等简单工具绕过完整管线
5. **回合增强**：`turn_enrichment` 加载偏好、记忆、上下文
6. **委托 RuntimeGateway**：`get_runtime_gateway().run(request)` 或 `.stream(request)`

### 12.5 与 RuntimeGateway 的委托关系

```
CognitiveKernel.run()
  → V5 路由检查
  → 回合增强
  → get_runtime_gateway().run(request)
      → CognitiveSupervisor.prepare_run(request)
      → RuntimeTurnDispatcher.run_turn(request, prepared)
          → cognitive_executive | data_intelligence | multi_goal
```

---

## Chapter 13: V5 分层路由

### 13.1 概述

V5 分层路由是请求进入认知管线前的第一道关卡，通过三层递进式路由策略，将简单请求快速分流，避免不必要的 LLM 调用。

源文件：
- `kernel/query_router_v2.py` — L0 规则路由
- `kernel/semantic_cache.py` — 语义缓存
- `kernel/tiny_router.py` — L1 TinyRouter
- `kernel/fast_tool_path.py` — 工具快速路径

### 13.2 三层路由架构

```
用户查询
  ↓
L0: 规则路由（关键词/模式匹配）
  ├── 匹配身份查询 → 走 IDENTITY 路径
  ├── 匹配工具查询 → 走工具快速路径
  ├── 匹配 SQL 检索 → 走 Tier-0 数据库直接路径
  └── 未匹配 → 继续
  ↓
语义缓存检查
  ├── 命中缓存 → 直接返回缓存答案
  └── 未命中 → 继续
  ↓
L1: TinyRouter（qwen3-1.7b 轻量分类）
  ├── 分类为简单 → 走 FAST 路径
  ├── 分类为复杂 → 走完整认知管线
  └── 分类为数据库 → 走数据认知管线
```

### 13.3 L0 规则路由

L0 层使用纯规则匹配（关键词、正则模式），不调用任何 LLM，延迟 < 1ms：

- **身份查询**：匹配"你是谁"、"你叫什么"、"who are you" 等
- **工具查询**：匹配天气、时间、计算器等关键词
- **SQL 检索**：匹配数据库查询模式（`_is_sql_retrieval_intent`）
- **SQL 生成**：匹配"帮我写SQL"等生成模式（`_is_sql_generation_intent`）

### 13.4 语义缓存

```python
# kernel/semantic_cache.py
class SemanticCache:
    """基于向量相似度的语义缓存。"""
```

- 使用向量嵌入计算查询与历史缓存的相似度
- 相似度超过阈值时直接返回缓存答案
- 大幅降低重复查询的 LLM 调用成本

### 13.5 L1 TinyRouter

```python
# kernel/tiny_router.py
# 使用 qwen3-1.7b (JuniorShort) 进行轻量级分类
# 输出：{"route": "complex", "difficulty": "simple"}
```

- 使用最小的 LLM（qwen3-1.7b, max_tokens=100）进行分类
- 输出路由决策：`complex`（完整管线）或 `simple`（FAST 路径）
- 成本极低（~100 tokens），延迟 < 200ms

### 13.6 工具快速路径

```python
# kernel/fast_tool_path.py
def should_use_tool_fast_path(lock_dict, force_mode=None) -> bool:
    """判断是否应使用工具快速路径。"""

async def run_tool_fast_path(request) -> Any:
    """执行工具快速路径，绕过完整认知管线。"""
```

- 天气查询、时间查询、简单计算器等工具走此路径
- 绕过完整的认知管线（Rewrite → Understand → Plan → Constraint → ...）
- 直接调用 ToolAgent 执行并返回结果

---

## Chapter 14: CognitiveExecutive — 认知执行中枢

### 14.1 概述

源文件：`kernel/runtime/cognitive_executive.py` — 1560 行

`CognitiveExecutive` 是认知运行时管线的**唯一入口**，编排完整的 12+ 阶段认知流水线。所有请求经此完成认知决策（CognitivePlan），投影为 ExecutionPlan 后由运行时执行。

### 14.2 核心原则

```python
class CognitiveExecutive:
    """认知执行中枢 — 所有请求的统一入口。
    请求经此完成一次认知决策（CognitivePlan），投影为 ExecutionPlan 后由运行时执行。
    无自主 Agent 回退、无分散认知逻辑。
    模块间仅通过 RuntimeContext 通信，禁止跨模块直接 import。
    """
```

### 14.3 12+ 阶段认知管线

```
IntentLock → Rewrite → Understand → Policy
  → Plan(V2) → Constraint → Execute → Evidence
  → Rank → Fuse(V2) → Critic(V2)
  → CognitiveIteration → Artifact → Archive
```

#### 阶段详解

| 阶段 | 引擎 | 说明 | LLM 角色 |
|------|------|------|----------|
| **IntentLock** | IntentEngine | 意图锁定，确定 task_type 和 complexity_level | ROUTER (1.7b) |
| **Rewrite** | RewriteEngine | 查询改写（HyDE、分解、消歧） | PLANNING |
| **Understand** | UnderstandingEngine | 深度语义理解、实体识别、消歧 | PLANNING |
| **Policy** | UnifiedPolicyEngine | 策略评估，确定执行约束和权限 | 确定性规则 |
| **Plan** | CognitivePlannerV2 | 策略构建 → 认知图 → 执行投影 | PLANNING |
| **Constraint** | PlannerConstraintLayer | 五项确定性检查（预算/策略/风险/能力/历史） | 无 LLM |
| **Execute** | AgentRuntimeExecutor | 并行 Agent 执行 | QUERY |
| **Evidence** | EvidenceBus | 证据发布、验证、注册 | 无 LLM |
| **Rank** | EvidenceRanking | 多维度证据排序 | 确定性规则 |
| **Fuse** | FusionEngineV2 | LLM 驱动语义融合 | QUERY |
| **Critic** | CriticEngineV2 | 结构化质量评估 | CHEAP_CRITIC |
| **Iteration** | CognitiveIteration | 认知迭代（需改进时重规划） | PLANNING |
| **Artifact** | ArtifactComposer | 最终制品合成 | 无 LLM |
| **Archive** | FinalizeTurn | 回合收尾（记忆/缓存/计费） | 无 LLM |

### 14.4 RuntimeContext 传递

所有阶段通过 `RuntimeContext` 通信，禁止跨模块直接 import。RuntimeContext 是单次认知回合中流经每一层的**唯一真相来源**（Single Source of Truth）。

```python
async def execute(
    self,
    query: str,
    ctx: Any,  # RuntimeContext — 40+ 结构化字段
    event_cb: Callable | None = None,
) -> CognitiveExecutiveResult:
```

### 14.5 运行时织物演化

每个阶段边界处执行 `_runtime_fabric_evolve(ctx, phase=...)`，记录阶段快照供确定性回放与审计。

---

## Chapter 15: 改写与理解引擎

### 15.1 RewriteEngine — 查询改写

源文件：`kernel/runtime/rewrite_engine.py`

改写引擎对用户查询进行预处理，提升后续检索和推理的质量：

- **HyDE（Hypothetical Document Embeddings）**：生成假设性文档以提升向量检索召回率
- **查询分解**：将复杂查询拆分为多个子查询
- **消歧**：解析模糊指代和歧义表达
- **多轮补齐**：结合对话历史补全省略信息

### 15.2 UnderstandingEngine — 深度理解

源文件：`kernel/runtime/understanding_engine.py`

理解引擎对改写后的查询进行深度语义分析：

- **实体识别**：识别查询中的实体（人物、组织、地点、时间等）
- **意图分类**：细粒度意图分类（qa / data_query / web_search / tool_call / ...）
- **约束提取**：从查询中提取隐式约束（时间范围、排序偏好、过滤条件等）
- **领域识别**：识别查询所属领域（金融、医疗、技术等）

### 15.3 CognitivePlannerV2 — 认知规划

源文件：`kernel/runtime/cognitive/cognitive_planner_v2.py`

```python
class CognitivePlannerV2:
    """V2 认知规划器：策略构建 → 认知图 → 执行投影"""
```

规划流程：

```
StrategyBuilder → CognitiveGraph → ExecutionProjection
      ↓                ↓                  ↓
  策略构建         认知图构建          执行投影
  (选择策略)    (节点+边+依赖)    (ExecutionPlan)
```

---

## Chapter 16: 约束层

### 16.1 概述

源文件：`kernel/runtime/constraint_layer.py` — 361 行

约束层是认知管线中的**确定性护栏**，在 Agent 执行前对计划进行五项检查。**不调用 LLM**，纯规则 + 查表。

### 16.2 PlannerConstraintLayer

```python
class PlannerConstraintLayer:
    """确定性约束评估器。不调用模型，不含歧义。"""

    def evaluate(
        self,
        plan: CognitivePlan,
        ctx: RuntimeContext,
        capability_names: list[str] | None = None,
    ) -> ConstraintDecision:
        """对计划运行全部五项约束检查。返回通过/拒绝/修改。"""
```

### 16.3 五项确定性检查

| 检查项 | 说明 | 判定逻辑 |
|--------|------|---------|
| **预算约束** | 检查计划是否超出 Token/时间/成本预算 | 累计 Token 估算 vs 预算上限 |
| **策略合规** | 检查计划是否符合安全策略 | 与 UnifiedPolicyEngine 对账 |
| **风险评估** | 评估计划的风险等级 | 与 AdaptiveRiskEngine 对账 |
| **能力可用性** | 检查所需能力是否已注册且可用 | 查询 CapabilityRegistry |
| **历史先验** | 检查是否有类似计划的失败先例 | 查询 FailureMemory |

### 16.4 决策结果

```python
class ConstraintDecision:
    ALLOW = "allow"        # 通过
    DENY = "deny"          # 拒绝
    MODIFY = "modify"      # 修改后通过
```

---

## Chapter 17: 证据总线

### 17.1 概述

源文件：`kernel/runtime/evidence_bus.py` — 318 行

证据总线（EvidenceBus）是进程内证据发布/订阅总线，负责管理所有 Agent 执行结果的证据生命周期。Agent 在执行后发布 Evidence，融合/批评引擎收集并处理。

### 17.2 EvidenceBus 核心接口

```python
class EvidenceBus:
    """进程内证据发布/订阅总线，含生命周期管理。"""

    async def publish_results(self, results: list[AgentResult]) -> list[Evidence]:
        """将 AgentResults 转换为 Evidence，发布并注册到生命周期。"""
```

### 17.3 证据生命周期状态机

```
CREATED → VALIDATED → RANKED → MERGED → ARCHIVED
   ↓          ↓          ↓
 REJECTED  EXPIRED   CONFLICTED
```

| 状态 | 说明 |
|------|------|
| `CREATED` | 证据刚创建，未经验证 |
| `VALIDATED` | 通过真实性验证 |
| `REJECTED` | 验证失败，证据被拒绝 |
| `RANKED` | 完成多维度排序 |
| `EXPIRED` | 证据过期（超过 TTL） |
| `CONFLICTED` | 与其他证据存在冲突 |
| `MERGED` | 冲突已解决，证据已合并 |
| `ARCHIVED` | 证据已归档 |

### 17.4 多维度排序

证据排序考虑以下维度：

- **相关性**：与查询的语义相似度
- **新鲜度**：证据的时间衰减
- **权威性**：来源的可信度评分
- **一致性**：与其他证据的一致性

### 17.5 冲突解决

- 使用版本向量（Version Vector）追踪证据来源
- LWW（Last-Writer-Wins）策略解决时间冲突
- 语义冲突委托 FusionEngine 处理

---

## Chapter 18: 融合与审校引擎

### 18.1 FusionEngineV2 — 证据融合

源文件：`kernel/runtime/fusion.py` — 281 行

```python
class FusionEngineV2:
    """LLM 驱动的证据融合。
    简单/FAQ 查询走快速路径（启发式）。
    复杂多源证据走 LLM 路径（QUERY 角色）。
    """

    async def fuse(
        self,
        query: str,
        ctx: Any,  # RuntimeContext
        evidence_list: list[Any],  # list[Evidence]
    ) -> FusionResult:
        """将证据融合为连贯的回答。"""
```

**融合策略**：
- **简单查询**（单证据、高置信度）：启发式模板拼接，零 LLM 调用
- **复杂查询**（多证据、低置信度）：LLM 驱动语义融合，考虑矛盾检测
- **矛盾检测**：当多源证据冲突时，标记不确定性并解释差异

### 18.2 CriticEngineV2 — 质量审校

源文件：`kernel/runtime/critic.py` — 204 行

```python
class CriticEngineV2:
    """LLM 驱动的质量批评（不触发重规划）。
    速度配置走启发式快速路径；质量配置走 LLM 评估。
    """

    async def evaluate(
        self,
        query: str,
        answer: str,
        evidence_count: int = 0,
        adaptive_profile: dict[str, Any] | None = None,
    ) -> CriticResult:
        """结构化评估回答质量。"""
```

**评估维度**：

| 维度 | 说明 |
|------|------|
| `factuality` | 事实准确性 |
| `completeness` | 回答完整性 |
| `evidence_coverage` | 证据覆盖率 |
| `hallucination_risk` | 幻觉风险评估 |
| `relevance` | 与查询的相关性 |

**输出格式**：
```json
{
    "verdict": "pass",
    "confidence": 0.85,
    "issues": [],
    "scores": {
        "factuality": 0.9,
        "completeness": 0.8,
        "evidence_coverage": 0.85,
        "hallucination_risk": 0.1
    }
}
```

### 18.3 ArtifactComposer — 制品合成

源文件：`kernel/runtime/artifact_composer.py`

将融合后的回答与证据引用、引用标注、执行图等组合为最终制品（Artifact），包含：
- 最终回答文本
- 证据引用列表（citations）
- 推理过程可视化（execution_graph）
- 置信度标注
- 不确定性说明

---

## Chapter 19: 工作空间与记忆织物

### 19.1 Workspace — 运行时工作区

源文件：`kernel/runtime/workspace.py`

每个认知回合拥有独立的工作空间，用于存储中间产物：

- 改写后的查询
- 认知规划结果
- Agent 执行结果
- 证据列表
- 融合结果
- 批评结果

工作空间在回合结束时自动清理。

### 19.2 记忆织物

源文件：`kernel/runtime/memory/`

记忆织物是认知管线中的记忆管理子系统，包括：

#### 真值维护系统（TMS）

```python
# kernel/runtime/memory/truth_maintenance.py
class TruthMaintenanceSystem:
    """维护记忆的一致性，处理冲突和更新。"""
```

#### 置信度衰减

```python
# kernel/runtime/memory/confidence_decay.py
# 记忆随时间衰减，衰减速率取决于记忆类型和来源权威性
```

#### 事实取代

```python
# kernel/runtime/memory/fact_supersession.py
# 当新事实与旧事实冲突时，基于权威性和新鲜度决定是否取代
```

### 19.3 回合收尾

源文件：`kernel/runtime/finalize_turn.py`

每个认知回合结束时执行：

1. **记忆写入**：将重要事件写入 Working/Episodic/Semantic Memory
2. **缓存更新**：更新语义缓存
3. **世界模型终结**：`world_turn_finalize` 更新世界状态
4. **回合计费**：`post_turn_enterprise_accounting` 记录用量

---

## Chapter 20: 运行时回合分派器

### 20.1 RuntimeGateway — 瘦路由层

源文件：`kernel/runtime_gateway.py` — 165 行

```python
class RuntimeGateway:
    """Runtime lookup, lifecycle, dispatch only."""

    async def run(self, request: Any) -> Any:
        await self._ensure_turn_enrichment(request)
        supervisor = get_cognitive_supervisor()
        prepared = supervisor.prepare_run(request)
        response = await get_runtime_turn_dispatcher().run_turn(request, prepared, t0=t0)
        # 回合收尾
        post_turn_enterprise_accounting(request, response)
        return response
```

**职责**：
1. 回合增强（turn_enrichment）：偏好/记忆/上下文织网
2. Tier-0 快速路径尝试：SQL 检索、工具快速路径
3. 委托 CognitiveSupervisor.prepare_run
4. 委托 RuntimeTurnDispatcher.run_turn
5. 回合收尾

### 20.2 RuntimeTurnDispatcher — 回合分派

源文件：`kernel/runtime/runtime_turn_dispatcher.py`

```python
class RuntimeTurnDispatcher:
    async def run_turn(self, request, prepared, t0) -> Any:
        """按 runtime_type 分派到对应运行时。"""
```

**分派逻辑**：

| runtime_type | 运行时 | 说明 |
|-------------|--------|------|
| `cognitive_executive` | CognitiveExecutive | 完整认知管线（默认） |
| `data_intelligence` | DataIntelligenceRuntime | 数据认知管线 |
| `multi_goal` | MultiGoalScheduler | 多目标调度 |

### 20.3 注册表与治理

源文件：`kernel/runtime/registry.py`, `kernel/runtime/registry_governance.py`

```python
# registry.py — 运行时注册表
def ensure_runtimes_registered():
    """确保所有 Tier-1 运行时已注册。"""

def list_runtimes() -> list[str]:
    """列出所有已注册的运行时。"""

# registry_governance.py — 注册表治理
class RegistryGovernance:
    """服务间访问控制与认证策略。"""
```

- 运行时注册表管理所有可用的运行时类型
- 注册表治理确保只有授权的运行时可以被调用
- vNext 健康检查验证所有 Tier-1 运行时是否就绪

---

# Part IV: 智能体系统

## Chapter 21: Agent 架构

### 21.1 概述

智能体系统是 OpenTrace 的任务执行层，采用基于能力类型（capability_type）的分配机制，而非按 Agent 名称硬编码路由。

源文件：
- `agents/base.py` — Agent 基类与契约
- `agents/bootstrap.py` — 引导注册
- `agents/registry.py` — Agent 注册表
- `kernel/agent_runtime/agent_topology_manifest.yaml` — 拓扑清单（SSOT）

### 21.2 核心契约

#### TaskMessage — 任务消息

```python
class TaskMessage(BaseModel):
    task_id: str
    agent_type: str
    query: str
    params: dict[str, Any] = Field(default_factory=dict)
    session_id: str | None = None
    user_id: str | None = None
```

#### AgentResult — 执行结果

```python
class AgentResult(BaseModel):
    task_id: str
    agent_type: str
    status: str  # success | error | timeout
    content: str
    confidence: float = 0.5
    metadata: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    evidence_objects: list[Evidence] = Field(default_factory=list)
    agent_trace: dict[str, Any] | None = None
```

#### BaseAgent — 抽象基类

```python
class BaseAgent(ABC):
    def __init__(self, agent_type: str) -> None:
        self.agent_type = agent_type

    @abstractmethod
    async def execute(self, task: TaskMessage) -> AgentResult:
        pass

    async def execute_as_capability(self, task: TaskMessage) -> list[Evidence]:
        """Execute and return structured Evidence — the Capability Executor contract."""
```

### 21.3 Agent 引导注册

`bootstrap.py` 中的 `register_builtin_agents()` 在应用启动时注册所有内置 Agent：

```python
bootstrap_agent_types:
  - data          # DataAgent V2
  - rag           # RAGAgent
  - web_intelligence  # WebIntelligenceAgent
  - tool          # ToolAgent
  - vision        # VisionAgent
  - skills        # SkillsAgent
  - rules         # RulesAgent
```

### 21.4 Agent Topology Manifest

`agent_topology_manifest.yaml` 是能力/Agent 拓扑的**唯一真相来源**（SSOT），定义了四层运行时架构：

| 层级 | 运行时 | 说明 |
|------|--------|------|
| `tier0_kernel` | Cognitive Kernel | 认知内核 + 网关 + 监督器 |
| `tier1_executive` | Cognitive Executive | 认知执行能力分派 |
| `tier1_data` | Data Intelligence | DataAgent V2 监督器 + DAG |
| `tier2_nodes` | DAG/Pipeline Nodes | 内部 DAG 节点（非直接能力分派） |

每个能力条目包含：运行时层级、能力类型、注册名称、风险等级、最大延迟、依赖关系。

### 21.5 AgentRuntimeExecutor

```python
# kernel/agent_runtime/executor.py
class AgentRuntimeExecutor:
    """Enterprise agent execution facade (tier-1 CapabilityRegistry agents)."""
    async def execute_task(
        self,
        agent: BaseAgent,
        task: TaskMessage,
        *,
        goal_id: str = "",
        goal_description: str = "",
        capability_type: str = "",
        trace_id: str = "",
        evidence_bus: Any | None = None,
    ) -> AgentContribution:
```

- 统一的 Tier-1 能力执行门面
- 每个 Agent 执行后贡献 AgentContribution（含 GoalContribution 元数据）
- 结果通过 EvidenceBus 发布

---

## Chapter 22: DataAgent V2

### 22.1 概述

源文件：`agents/data_agent_v2/`（25+ 子代理）

DataAgent V2 是 OpenTrace 最复杂的 Agent，实现完整的认知管线用于 Text2SQL 和数据分析。采用五层认知架构。

### 22.2 五层认知管线

```
知识层 (Knowledge)  → 推理层 (Reasoning) → 规划层 (Planning)
  → 验证层 (Verification) → 学习层 (Learning)
```

### 22.3 核心子代理

| 子代理 | 文件 | 功能 |
|--------|------|------|
| **supervisor** | `supervisor.py` | 任务分解与调度 |
| **error_classifier** | `error_classifier.py` | 错误分类与恢复策略 |
| **knowledge_retriever** | `knowledge_retriever.py` | 知识检索（Schema/业务语义/历史） |
| **planner_agent** | `planner_agent.py` | SQL 规划 |
| **sql_compiler_agent** | `sql_compiler_agent.py` | SQL 编译 |
| **verification_agent** | `verification_agent.py` | 结果验证 |
| **reflection_agent** | `reflection_agent.py` | 反思与改进 |
| **insight_agent** | `insight_agent.py` | 数据洞察生成 |
| **statistical_agent** | `statistical_agent.py` | 统计分析 |

### 22.4 执行流程

```
用户查询 → supervisor 分解
  → knowledge_retriever 获取 Schema 上下文
  → planner_agent 生成 SQL 候选
  → sql_compiler_agent 编译 SQL
  → verification_agent 验证结果
  → reflection_agent 反思改进
  → insight_agent 生成洞察
```

### 22.5 错误分类与恢复

`error_classifier.py` 实现智能错误分类：
- SQL 语法错误 → 自动修正
- Schema 不匹配 → 重新获取 Schema
- 结果为空 → 放宽条件重试
- 超时 → 拆分查询

---

## Chapter 23: RAGAgent

### 23.1 概述

源文件：`agents/rag_agent.py` — 1156 行

RAGAgent 实现文档检索增强生成（Retrieval-Augmented Generation），支持混合检索、证据质量控制和多源融合。

### 23.2 混合检索策略

```
向量检索 (pgvector) + 关键词检索 (BM25) → RRF 融合 → Rerank
```

- **向量检索**：基于 DashScope text-embedding-v3（1024 维）
- **关键词检索**：BM25 算法
- **RRF 融合**：Reciprocal Rank Fusion，合并两种检索结果
- **Rerank**：BAAI/bge-reranker-v2-m3 或启发式重排序

### 23.3 证据质量控制

- 相关性评分：评估检索结果与查询的相关性
- 来源可信度：评估文档来源的权威性
- 信息完整性：检查是否覆盖查询的所有方面

### 23.4 集成能力

- **LLMWiki 查询**：从知识图谱中检索结构化知识
- **记忆检索**：从用户记忆中检索相关偏好和事实
- **文档检索**：从用户上传的文档中检索

---

## Chapter 24: WebAgent & WebIntelligenceAgent

### 24.1 WebAgent — 网页搜索

源文件：`agents/web_agent.py`

```python
class WebAgent(BaseAgent):
    """执行网页搜索与抓取，提供结构化内容格式化。"""
```

- 基于 Serper API 的网页搜索
- 搜索结果结构化格式化
- 证据对象生成

### 24.2 WebIntelligenceAgent — 智能搜索

源文件：`agents/web_intelligence_agent.py`

```python
class WebIntelligenceAgent(BaseAgent):
    """增强版网页搜索 — 证据排名、信任评估、声明图生成。"""
```

- 在 WebAgent 基础上增加智能处理
- 证据排名：按可信度排序搜索结果
- 信任评估：评估来源的可信度
- 声明图生成：构建知识声明图
- 覆盖评估器：评估搜索结果的覆盖度

### 24.3 拓扑关系

在 `agent_topology_manifest.yaml` 中，`web_intelligence` 标记为 `web` 的优先替代：
```yaml
web:
    topology:
      superseded_by: web_intelligence
web_intelligence:
    topology:
      preferred_over: web
```

---

## Chapter 25: 其他 Agent

### 25.1 ToolAgent — 工具调用

源文件：`agents/tool_agent.py`

```python
class ToolAgent(BaseAgent):
    """调用插件工具处理特定任务。"""
```

- 天气查询：调用天气 API
- 时间查询：返回当前时间
- 计算器：执行数学表达式

### 25.2 VisionAgent — 视觉分析

源文件：`agents/vision_agent.py`

```python
class VisionAgent(BaseAgent):
    """图像理解，基于 Qwen3-VL。"""
```

- 图像识别：识别图片内容
- OCR：文字提取
- 图表分析：分析图表数据

### 25.3 SkillsAgent — 技能执行

源文件：`agents/skills_agent.py`

- 执行已安装的市场技能
- 与 Skills Runtime 集成

### 25.4 CognitiveAgent — 认知工作流

源文件：`agents/cognitive_agent.py`

- 认知工作流基类
- 实现执行计划和工作流管理

### 25.5 RulesAgent — 规则引擎

源文件：`agents/rule_engine_agent.py`

- 关键词 + LLM 规则解释
- 规则触发和事件响应

### 25.6 Worker — Agent Worker

源文件：`agents/worker.py`

- 分布式 Agent Worker
- 通过 Agent Bus（Redis Stream/PubSub）接收任务

---

# Part V: 认知子系统

## Chapter 26: 目标系统

### 26.1 概述

源文件：`kernel/goal/`

目标系统将用户查询投影为 GoalGraph（目标图），后续所有执行围绕目标进行。

### 26.2 GoalGraph 结构

```python
@dataclass
class GoalGraph:
    root_goal_id: str
    goals: list[Goal] = field(default_factory=list)
    intent_category: str = "general"
    protected_intent: str = ""
```

### 26.3 GoalSupervisor — 目标监督器

```python
# kernel/goal/goal_supervisor.py
class GoalSupervisor:
    """任务查询识别、目标合并、分解、冲突检测。"""
```

### 26.4 目标驱动规划器

```python
# kernel/goal/goal_driven_planner.py
async def plan_from_goal_context(
    canonical_query: str,
    ctx: Any,
    understanding: Any = None,
) -> tuple[Any, Any, Any]:
    """Return (cognitive_plan, execution_plan, execution_graph) bound to goal_graph."""
```

### 26.5 目标生命周期

```
ACTIVE → IN_PROGRESS → COMPLETED → ARCHIVED
```

- `goal_lifecycle.py`：管理绑定与状态转换
- `goal_progress.py`：追踪目标进度
- `goal_recovery.py`：目标失败恢复
- `multi_goal_scheduler.py`：多目标调度

---

## Chapter 27: 治理中心

### 27.1 概述

源文件：`kernel/governance/`

GovernanceCenter 是统一治理入口，在请求处理各阶段执行治理检查。

### 27.2 五层治理器

| 治理器 | 文件 | 职责 |
|--------|------|------|
| **RiskGovernor** | `risk_governor.py` | 风险评估与控制 |
| **EvidenceGovernor** | `evidence_governor.py` | 证据质量治理 |
| **PolicyGovernor** | `policy_governor.py` | 策略合规检查 |
| **MemoryGovernor** | `memory_governor.py` | 记忆访问控制 |
| **CapabilityGovernor** | `capability_governor.py` | 能力使用治理 |

### 27.3 AdaptiveRiskEngine

```python
# kernel/governance/adaptive_risk_engine.py
class AdaptiveRiskEngine:
    """自适应风险评估 — 基于历史数据动态调整风险阈值。"""
```

---

## Chapter 28: 认知监督器

### 28.1 概述

源文件：`kernel/cognitive_supervisor/`

CognitiveSupervisor 位于认知内核和运行时网关之间，负责请求的预处理和治理。

### 28.2 prepare_run 流程

```python
# kernel/cognitive_supervisor/supervisor.py
class CognitiveSupervisor:
    def prepare_run(self, request) -> PreparedRun:
        """准备运行时执行：
        1. GoalGraph 构建
        2. 治理评估（风险/证据/策略）
        3. 策略记忆加载
        4. RuntimeContext 构建（40+ 字段）
        5. 世界状态注入
        6. 上下文织物种子
        """
```

### 28.3 控制平面门控

```python
# kernel/cognitive_supervisor/control_plane_gate.py
# 预检、配额检查
```

---

## Chapter 29: 上下文系统

### 29.1 RuntimeContext

源文件：`kernel/runtime/context.py`

RuntimeContext 是单次认知回合中流经每一层的**唯一真相来源**，包含 40+ 结构化字段：

- 用户信息（user_id, tenant_id, workspace_id）
- 会话信息（session_id, conversation_state）
- 查询信息（original_query, rewritten_query, intent）
- 认知状态（cognitive_plan, execution_plan, goal_graph）
- 证据信息（evidence_list, fusion_result, critic_result）
- 安全信息（risk_level, permission_token）

### 29.2 ContextFabric

源文件：`kernel/context_fabric.py`

```python
class ContextFabric:
    """统一上下文组装 — 替代分散的上下文处理模块。"""
```

- 上下文组装器：将多种上下文源组装为统一的 Prompt 上下文
- 图谱演化：基于上下文反馈演化知识图谱

---

## Chapter 30: 对话状态与多轮

### 30.1 ConversationState

源文件：`kernel/conversation_state.py` — 346 行

```python
class ConversationState:
    """结构化持久会话状态 — 替代扁平 metadata 字典。"""
    # 包含：主题、意图、约束、对话阶段等
```

### 30.2 回合增强

源文件：`kernel/turn_enrichment.py` — 396 行

```python
async def enrich_turn_before_dispatch(request, skip_multi_turn=False):
    """多轮对话、偏好注入、记忆处理、上下文织网装配。"""
```

### 30.3 澄清门控

源文件：`kernel/clarification_gate.py`

当系统无法确定用户意图时触发澄清机制，向用户提出澄清问题。

### 30.4 其他多轮组件

- `multi_turn_resolution.py`：多轮指代消解
- `history_retriever.py`：语义历史检索
- `refine_planner.py`：有界局部重规划

---

## Chapter 31: 能力智能

### 31.1 概述

源文件：`kernel/capability_intelligence/`

能力智能层负责系统能力的画像、推理、反馈和演化。

### 31.2 核心组件

| 组件 | 文件 | 功能 |
|------|------|------|
| **Profiler** | `profiler.py` | 5D 能力画像 |
| **Reasoner** | `reasoner.py` | 知识图谱拓扑 + 画像匹配 + 执行历史推理 |
| **KnowledgeGraph** | `knowledge_graph.py` | 能力知识图谱 |
| **ExecutionMemory** | `execution_memory.py` | 执行记忆 |
| **StrategyMemory** | `strategy_memory.py` | 策略记忆 |
| **FailureMemory** | `failure_memory.py` | 失败记忆 |
| **CapabilityScore** | `capability_score.py` | 多目标能力评分 |
| **Evolution** | `evolution.py` | 能力演化引擎 |
| **Adapter** | `adapter.py` | 能力画像 → LLM 提示格式化 |

---

## Chapter 32: 记忆系统

### 32.1 概述

源文件：`memory/` 全部模块

OpenTrace 实现了七种记忆类型，覆盖从短期到长期、从事实到程序的全方位记忆。

### 32.2 记忆类型

#### WorkingMemory — 工作记忆

```python
# memory/working_memory/working_memory.py
class WorkingMemory:
    """环形缓冲区对话窗口 + 键值临时存储。Redis 持久化（24h TTL）。"""
```

- 环形缓冲区：max_turns=32
- Redis 持久化：24h TTL
- 支持 get_or_create / load_or_create

#### EpisodicMemory — 情景记忆

```python
# memory/episodic_memory/episodic_memory.py
class EpisodicMemory:
    """基于 Redis 列表的会话事件存储。"""
```

#### SemanticMemory — 语义记忆

```python
# memory/semantic_memory/semantic_memory.py
class SemanticMemory:
    """基于 pgvector 的长期知识存储，余弦相似度匹配。"""
```

#### ProceduralMemory — 程序记忆

```python
# memory/procedural_memory/procedural_memory.py
class ProceduralMemory:
    """基于 Redis Hash 的可重用过程模板存储。"""
```

#### TemporalMemoryIndex — 时间记忆

```python
# memory/temporal_memory/temporal_index.py
class TemporalMemoryIndex:
    """时间衰减评分索引 — 指数衰减使近期事件权重更高。"""
```

#### MemoryRouter — 记忆路由

```python
# memory/memory_router/router.py
class MemoryRouter:
    """联邦式记忆：语义搜索 + 图搜索 + 事件检索 + 关键词检索 → 统一重排序。"""
```

#### MemoryGraph — 记忆织物

```python
# memory/fabric/memory_graph.py
class MemoryGraphStore:
    """节点/边操作，图快照加载与持久化。"""
```

### 32.3 记忆进化

```python
# memory/evolution/evolution.py
class MemoryEvolution:
    """从记忆中抽象模式（Pattern）和技能（Skill）：
    记忆压缩 → 聚类 → 模式生成 → 技能生成。"""
```

---

## Chapter 33: 世界模型与认知

### 33.1 WorldModel

源文件：`kernel/cognition/world_model.py` — 267 行

```python
class WorldModel:
    """语义接地与消歧 — 实体注册、时间短语处理。"""
```

### 33.2 PredictiveWorld

源文件：`kernel/cognition/predictive_world.py`

预测世界状态变化，用于主动式上下文管理。

### 33.3 RuntimeGrounding

源文件：`kernel/cognition/runtime_grounding.py`

运行时接地 — 将抽象概念映射到具体执行上下文。

---

## Chapter 34: 协议与契约系统

### 34.1 RuntimeContract

源文件：`kernel/protocol/runtime_contract.py`

```python
@dataclass
class GoalGraph:
    root_goal_id: str
    goals: list[Goal]
    intent_category: str = "general"

@dataclass
class Constraint:
    budget: BudgetConstraint
    policy: PolicyConstraint
    risk: RiskConstraint
```

### 34.2 CognitionProtocol

源文件：`kernel/protocol/cognition_protocol.py`

定义认知操作的协议规范。

### 34.3 AgentProtocol

源文件：`kernel/protocol/agent_protocol.py`

定义 Agent 间通信的协议规范。

---

## Chapter 35: 其他认知子系统

### 35.1 元认知

源文件：`kernel/meta_cognition/meta_cognition.py` — 181 行

```python
class MetaCognition:
    """三层质量控制：接受、精炼与重试。"""
```

### 35.2 意图引擎

源文件：`kernel/intent_engine/engine.py` — 155 行

```python
class IntentEngine:
    """将原始用户查询解析为结构化意图对象。"""
```

### 35.3 推理引擎

源文件：`kernel/reasoning/engine.py`

高层逻辑推理 — 与认知内核直接交互，支持执行、计划和反思。

### 35.4 系统身份

源文件：`kernel/identity/system_identity.py`

管理系统的身份响应，包括缓存和上下文指纹验证。

### 35.5 其他子系统

| 子系统 | 目录 | 说明 |
|--------|------|------|
| 认识论 | `kernel/epistemology/` | 知识验证 |
| 策略引擎 | `kernel/policy/` | 策略执行 |
| Prompt 引擎 | `kernel/prompt_engine/` | Prompt 管理 |
| Web 引擎 | `kernel/web_engine/` | Web 处理 |
| 内核工具 | `kernel/tools/` | 内置工具 |

---

# Part VI: 安全与防护

## Chapter 36: 安全架构

### 36.1 零信任模型

源文件：`infra/security/zero_trust.py`

```python
def assess_query_risk(query: str) -> RiskAssessment:
    """评估查询风险等级。"""

def issue_permission_token(user_id: str, scope: str) -> str:
    """签发工具调用权限 Token。"""

def validate_permission_token(token: str) -> bool:
    """验证权限 Token。"""

def tool_anomaly_detector(tool_name: str, params: dict) -> bool:
    """检测工具调用异常。"""
```

**核心原则**：
- 最小权限：每次工具调用需要显式权限 Token
- 持续验证：每个请求重新评估风险
- 工具异常检测：监控异常调用模式

### 36.2 权限 Token 管理

- 高危操作（如数据删除、SQL 执行）需要用户确认（`confirmation_granted=True`）
- Token 有时效性，过期需重新签发
- 异常检测器监控调用频率和参数模式

---

## Chapter 37: PII 脱敏与护栏

### 37.1 NER Masker

源文件：`safety/masking/ner_masker.py` — 153 行

```python
class NERMasker:
    """命名实体识别与脱敏：人名、组织、日期、电话号码等。"""
```

### 37.2 Guardrails

源文件：`safety/guardrails/guardrails.py` — 131 行

```python
class Guardrails:
    """基于上下文的规则控制，自动安全检查。"""
    def check_output(self, text: str) -> GuardrailResult:
        """检查输出内容，返回 sanitized 文本。"""
```

### 37.3 SafetyPolicyEngine

源文件：`safety/policy_engine/engine.py` — 107 行

```python
class SafetyPolicyEngine:
    """安全策略决策流程 — 防止有害或不当行为。"""
```

---

## Chapter 38: 沙箱运行时

### 38.1 代码解释器

源文件：`plugins/code/interpreter.py`

- AST 守卫：在代码执行前进行 AST 级别的安全检查
- 禁止危险操作：文件系统访问、网络请求、进程管理
- 资源限制：超时、内存限制

### 38.2 文件沙箱

源文件：`plugins/file/sandbox.py`

- 隔离文件系统：每个会话独立临时目录
- 路径安全校验：`resolve_readable_sandbox_file` 防止路径遍历

### 38.3 多级隔离

| 级别 | 方案 | 说明 |
|------|------|------|
| Level 1 | AST 守卫 | 静态代码分析 |
| Level 2 | gVisor | 用户态内核隔离 |
|- Level 3 | Firecracker | MicroVM 完全隔离

---

# Part VII: 基础设施

## Chapter 39: 数据库与存储

### 39.1 概述

OpenTrace 使用 **PostgreSQL 16 + pgvector** 作为主存储引擎，通过 **SQLAlchemy 2.0 async** 提供异步 ORM 访问，并使用 **Alembic** 管理数据库迁移。

源文件：`infra/storage/database.py`, `infra/config/settings.py` (DatabaseSettings)

### 39.2 数据库配置

```python
class DatabaseSettings(BaseSettings):
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/opentrace_v2"
    token_db_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/opentrace_v2"
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 1800  # 30 分钟回收
```

**连接池策略**：
- 基础连接池大小 10，最大溢出 20，总计最多 30 并发连接
- 连接超时 30 秒，连接回收周期 1800 秒（防止连接泄漏）
- 自动将 `postgresql://` 驱动修正为 `postgresql+asyncpg://`
- 自动将 `host.docker.internal` 替换为 `postgres`（Docker 环境）

### 39.3 异步引擎与会话

```python
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

engine = create_async_engine(
    settings.database_url,
    pool_size=settings.pool_size,
    max_overflow=settings.max_overflow,
    pool_timeout=settings.pool_timeout,
    pool_recycle=settings.pool_recycle,
    echo=settings.debug,
    future=True,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)
```

**Session 获取模式**：

```python
@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

### 39.4 ORM 基类

```python
class Base(DeclarativeBase):
    """所有 ORM 模型共享的声明基类。"""
    pass
```

所有模型定义在 `infra/storage/models.py` 中，统一继承自 `Base`。

### 39.5 pgvector 扩展

PostgreSQL 通过 `pgvector/pgvector:pg16` 镜像启用向量扩展，支持：
- **向量存储**：`VECTOR(1536)` 或 `VECTOR(1024)` 列类型
- **向量检索**：`<=>` 余弦距离操作符
- **IVFFlat 索引**：加速近似最近邻搜索

### 39.6 数据库迁移（Alembic）

- 迁移脚本位于 `alembic/versions/` 目录
- 使用 `alembic upgrade head` 执行迁移
- 支持单头迁移链（`test_alembic_single_head_contract.py` 验证）
- 幂等迁移（`test_alembic_idempotent_contract.py` 验证）

### 39.7 多数据库支持

除了主 PostgreSQL 数据库外，DataAgent V2 支持连接外部数据库进行 Text2SQL 查询：

| 数据库 | 驱动 | 用途 |
|--------|------|------|
| PostgreSQL | asyncpg | 主存储 + 外部数据源 |
| MySQL | asyncmy | 外部数据源 |
| ClickHouse | clickhouse-driver | 分析查询 |

---

## Chapter 40: Redis 与缓存

### 40.1 概述

OpenTrace 使用 **Redis 7** 作为缓存、会话存储、消息队列和分布式协调的中心。系统采用 **6-DB 分区架构**，每个 DB 服务于独立的目的，避免键冲突和数据耦合。

源文件：`infra/cache/redis_client.py`, `infra/cache/redis_shadow_store.py`

### 40.2 6-DB 分区架构

```python
class RedisSettings(BaseSettings):
    redis_url: str = "redis://localhost:6379/10"
    redis_session_db: int = 10    # 会话状态
    redis_cache_db: int = 11      # 通用缓存
    redis_memory_db: int = 12     # 记忆存储
    redis_queue_db: int = 13      # 任务队列
    redis_rate_limit_db: int = 14 # 速率限制
    redis_pubsub_db: int = 15     # 发布订阅
```

| DB | 用途 | 典型键模式 | TTL |
|----|------|-----------|-----|
| 10 | Session | `session:{id}`, `ws:{session_id}` | 24h |
| 11 | Cache | `cache:{key}`, `semantic_cache:{hash}` | 按策略 |
| 12 | Memory | `opentrace:memory:*`, `opentrace:perm:*` | 持久化 |
| 13 | Queue | `opentrace:agent:stream:*`, DLQ | 按消费 |
| 14 | Rate Limit | `ratelimit:{user_id}:{endpoint}` | 窗口期 |
| 15 | PubSub | `opentrace:agent:task:*`, `opentrace:agent:result:*` | 实时 |

### 40.3 连接池管理

```python
async def get_redis_client(db: int) -> aioredis.Redis:
    """获取指定 DB 的 Redis 连接（带连接池复用）。"""
    async with _lock:
        if db not in _pools:
            _pools[db] = aioredis.from_url(
                settings.redis_url, db=db,
                max_connections=20,
                decode_responses=True,
            )
        return _pools[db]
```

- 每个 DB 维护独立的连接池（最多 20 连接）
- 连接池使用 `asyncio.Lock` 保证线程安全
- 支持 `decode_responses=True` 自动解码

### 40.4 ShadowRedis（影子存储）

`ShadowPipeline` 提供 Redis 写操作的影子同步机制，确保关键数据在 Redis 和持久化存储之间的最终一致性：

```python
class ShadowPipeline:
    """Redis pipeline 的影子同步包装器。
    每次写操作同时记录到 shadow_store，用于持久化和审计。
    """
    def __init__(self, db: int, r: aioredis.Redis):
        self.db, self.r = db, r
        self.p = r.pipeline()
        self.ops: list[tuple[str, tuple[Any, ...]]] = []

    async def execute(self):
        out = await self.p.execute()
        await self._sync()  # 影子同步
        return out
```

支持的影子操作：`zremrangebyscore`, `zadd`, `zcard`, `expire`, `lpop`

### 40.5 语义缓存

`kernel/semantic_cache.py` 提供基于向量相似度的语义缓存，避免重复 LLM 调用：

```python
class SemanticCache:
    """语义缓存 — 通过向量相似度匹配缓存历史回答。"""
    async def lookup(self, query: str, embedding: list[float]) -> CacheHit | None: ...
    async def store(self, query: str, embedding: list[float], answer: str) -> None: ...
```

- 使用 embedding 向量的余弦相似度匹配
- 可配置相似度阈值
- 缓存命中直接返回，跳过完整认知管线

### 40.6 Redis 健康检查

Docker Compose 中配置了 Redis 健康检查：
```yaml
healthcheck:
  test: ["CMD", "redis-cli", "ping"]
  interval: 10s
  timeout: 3s
  retries: 5
```

最大内存限制 512MB，溢出策略 `allkeys-lru`。

---

## Chapter 41: 消息总线与事件

### 41.1 概述

OpenTrace 使用 **AgentMessageBus** 实现分布式 Agent 调度，使用 **CognitiveEventBus** 实现认知事件的实时传播。支持 PubSub 和 Redis Stream 双模式。

源文件：`infra/message_bus/agent_bus.py`, `infra/message_bus/cognitive_event_bus.py`

### 41.2 AgentMessageBus

Agent 消息总线是分布式 Agent 调度的核心，支持 PubSub（低延迟）和 Stream（持久化）双模式：

```python
class AgentMessageBus:
    def __init__(self, namespace: str = "opentrace:agent") -> None:
        self.ns = namespace
        self.mode = "pubsub"  # pubsub | stream
        self.group = "agent-workers"
        self.consumer = "worker-1"

    def task_channel(self, agent_type: str) -> str:
        return f"{self.ns}:task:{agent_type}"

    def task_stream(self, agent_type: str) -> str:
        return f"{self.ns}:stream:task:{agent_type}"

    def dlq_stream(self) -> str:
        return f"{self.ns}:stream:dlq"  # 死信队列

    def result_channel(self, task_id: str) -> str:
        return f"{self.ns}:result:{task_id}"
```

**核心数据结构 — AgentTaskEnvelope**：

```python
@dataclass
class AgentTaskEnvelope:
    task_id: str
    agent_type: str
    query: str
    params: dict[str, Any]
    session_id: str | None = None
    user_id: str | None = None
    attempt: int = 0
```

**核心方法**：
- `publish_task(task)` — 发布任务到 Agent 专用频道/流
- `consume_tasks(agent_type)` — 消费指定 Agent 类型的任务
- `publish_result(task_id, result)` — 发布任务结果
- `dead_letter(task)` — 将失败任务发送到死信队列 (DLQ)

### 41.3 死信队列 (DLQ)

失败任务自动进入 DLQ 流，支持：
- 重试次数追踪 (`attempt` 字段)
- 延迟重试策略
- 手动干预和重新入队

### 41.4 CognitiveEventBus

认知事件总线传播认知管线中的关键事件，用于实时监控和调试：

```python
class EventType(Enum):
    TURN_START = "turn_start"
    TURN_COMPLETE = "turn_complete"
    TURN_ERROR = "turn_error"
    REASONING_START = "reasoning_start"
    REASONING_STEP = "reasoning_step"
    REASONING_COMPLETE = "reasoning_complete"
    TOOL_CALL_START = "tool_call_start"
    TOOL_CALL_COMPLETE = "tool_call_complete"
    TOOL_CALL_ERROR = "tool_call_error"
    MEMORY_UPDATE = "memory_update"
    MEMORY_RETRIEVE = "memory_retrieve"
    SYSTEM_HEARTBEAT = "system_heartbeat"
    SYSTEM_ERROR = "system_error"
    PLANNING = "planning"
    EXECUTION = "execution"
    FUSION = "fusion"
    CRITIC = "critic"
    LEARNING = "learning"
```

**事件结构**：

```python
@dataclass
class CognitiveEvent:
    event_type: EventType
    session_id: str
    data: Dict[str, Any]
    timestamp: datetime
```

**EventBus 特性**：
- 最大队列大小 1000（防止内存溢出）
- 异步订阅/发布模式
- 事件类型路由分发

### 41.5 消息总线拓扑

```
AgentMessageBus (PubSub/Stream)
  ├── task:{agent_type}      → Agent Worker 消费
  ├── result:{task_id}       → 调用方等待结果
  └── stream:dlq             → 死信队列

CognitiveEventBus (内存)
  ├── turn_start/complete    → 回合生命周期
  ├── reasoning_step         → 推理进度
  ├── tool_call_*            → 工具调用追踪
  ├── planning/execution     → 管线阶段
  └── learning               → 学习事件
```

---

## Chapter 42: 可观测性

### 42.1 概述

OpenTrace 的观测体系包含三个层次：**结构化日志**（structlog）、**分布式追踪**（OpenTelemetry）、**指标导出**（Prometheus）。所有组件均支持优雅降级——当对应依赖未安装时自动回退为空操作。

源文件：`infra/observability/tracer.py`, `infra/observability/logger.py`

### 42.2 结构化日志（structlog）

```python
# 核心特性
- 自动绑定请求上下文（request_id, session_id, user_id, tenant_id）
- 敏感信息脱敏：password, token, authorization, api_key, secret → "***"
- Bearer Token 自动脱敏：Bearer xxxx → Bearer ***
- 支持 structlog 和 stdlib logging 双模式
```

**日志上下文注入**：

```python
from infra.observability.request_context import get_log_context

# 每个请求自动注入：
# - request_id: 请求唯一标识
# - session_id: 会话标识
# - user_id: 用户标识
# - tenant_id: 租户标识
```

**敏感信息脱敏规则**：

```python
_SENSITIVE_KEYS = {"password", "token", "authorization", "api_key", "secret"}

def _mask_sensitive(v: Any) -> Any:
    if isinstance(v, dict):
        out = {}
        for k, val in v.items():
            if str(k).lower() in _SENSITIVE_KEYS:
                out[k] = "***"
            else:
                out[k] = _mask_sensitive(val)
        return out
    # Bearer token 自动脱敏
    if isinstance(v, str):
        return re.sub(r"(Bearer\s+)[A-Za-z0-9\-\._~\+/]+=*", r"\1***", v)
    return v
```

### 42.3 分布式追踪（OpenTelemetry）

```python
def setup_tracing(
    service_name: str = "opentrace",
    otlp_endpoint: str = "http://localhost:4317",
    enabled: bool = True,
    console_fallback: bool = False,
) -> Any:
    """配置 OpenTelemetry 追踪。
    - 支持 OTLP gRPC 导出到 Jaeger/Tempo
    - 控制台回退模式用于本地调试
    - 未安装 OpenTelemetry 时优雅降级为 NoopTracer
    """
```

**追踪覆盖范围**：
- `cognitive_kernel.run` — 内核完整执行
- `cognitive_executive.execute` — 认知管线各阶段
- 所有 Agent 执行（RAG/Web/Data/Tool/Vision）
- HTTP 请求（FastAPI 自动插桩）
- 数据库查询（SQLAlchemy 自动插桩）
- Redis 操作（Redis 自动插桩）

**NoopTracer 降级**：

```python
class _NoopTracer:
    def start_as_current_span(self, name: str, **kwargs):
        return _NoopSpan()  # 空操作，不影响业务逻辑
```

### 42.4 Prometheus 指标导出

API 网关通过 `/api/v1/prometheus` 端点（`gateway/api_gateway/routers/prometheus.py`）导出指标：

- `LLM_CALLS_TOTAL` — LLM 调用总数（按角色/模型）
- `LLM_LATENCY` — LLM 调用延迟
- `TURN_DURATION` — 回合处理时长
- `AGENT_TASK_DURATION` — Agent 任务执行时长
- `EVIDENCE_COUNT` — 证据收集数量

### 42.5 认知追踪（Cognitive Trace）

`kernel/runtime` 中的 `RuntimeSnapshot` 机制提供比 OpenTelemetry 更细粒度的认知追踪：
- 在 5 个关键阶段捕获完整运行时状态
- 包含 Prompt 快照和运行时快照
- 支持确定性回放和审计

---

## Chapter 43: 企业多租户

### 43.1 概述

OpenTrace 提供完整的多租户支持，涵盖租户注册、配额管理、计费归因和用量计量。租户隔离在数据库级别（RLS）和 Redis 级别实现。

源文件：`tenant/tenant_manager.py`, `tenant/quota_manager.py`, `tenant/billing_manager.py`

### 43.2 租户管理

```python
@dataclass
class TenantRecord:
    tenant_id: str
    name: str = ""
    tier: str = "standard"              # standard | premium | enterprise
    data_residency: str = "global"       # 数据驻留区域
    compliance_frameworks: list[str] = ["soc2"]  # 合规框架
    max_monthly_cost: float = 10_000.0  # 月度成本上限
    metadata: dict[str, Any] = field(default_factory=dict)

class TenantManager:
    def register(self, record: TenantRecord) -> None: ...
    def get(self, tenant_id: str) -> TenantRecord | None: ...
    def ensure_default(self) -> TenantRecord: ...
    def list_all(self) -> list[TenantRecord]: ...
```

**租户层级**：

| 层级 | 日配额 | 月度成本上限 | 特性 |
|------|--------|-------------|------|
| Standard | 10,000 turns | $500 | 基础功能 |
| Premium | 50,000 turns | $2,000 | 高级分析 + 自定义模型 |
| Enterprise | 无限制 | $10,000+ | 专属部署 + 合规框架 |

### 43.3 配额管理

```python
@dataclass
class QuotaDecision:
    allowed: bool
    violations: list[str]     # 违规原因列表
    turns_used: int = 0        # 已用回合数
    cost_used: float = 0.0     # 已用成本

class QuotaManager:
    def set_limits(self, isolation_key: str, *, daily_turns: int, daily_cost: float) -> None: ...
    def check(self, ctx: TenantContext) -> QuotaDecision: ...
    def consume(self, ctx: TenantContext, cost: float = 0.0) -> QuotaDecision: ...
```

配额检查在控制平面门控 (`control_plane_gate.py`) 中执行，在请求进入认知管线之前完成。

### 43.4 计费归因

```python
@dataclass
class CostAttribution:
    tenant_id: str
    capability_type: str = ""    # 能力类型
    goal_id: str = ""            # 目标 ID
    cost: float = 0.0            # 成本（USD）
    currency: str = "USD"
    dimensions: dict[str, float] # 多维度成本分解

class BillingManager:
    def attribute_turn(self, ctx: TenantContext, *, capability_type: str = "",
                       estimated_cost: float = 0.0) -> CostAttribution: ...
```

计费维度包括：
- **按能力类型**：data_query / rag / web_search / tool / vision
- **按目标**：每个 GoalGraph 中的 goal 独立计费
- **按 Token**：LLM Token 消耗折算为成本

### 43.5 用量计量

`tenant/usage_metering.py` 追踪每租户的用量指标：
- 每日 API 调用次数
- 每日 Token 消耗量
- 存储使用量（文档 + 记忆）
- 活跃会话数

### 43.6 工作空间管理

`tenant/workspace_manager.py` 提供工作空间级别的隔离：
- 每个租户可以有多个工作空间
- 工作空间内独立管理文档、知识库、记忆
- 支持跨工作空间共享（需显式授权）

---

## Chapter 44: 模型网关与 LLM 适配器

### 44.1 概述

Model Gateway 是所有 LLM 调用的唯一入口，提供 **9 角色路由**、**CircuitBreaker 熔断器**、**离线降级**和**模型调用追踪**。所有 LLM 调用必须通过 Gateway，禁止直接调用 LLM API。

源文件：`model/model_gateway/gateway.py`, `model/llm_adapter/openai_adapter.py`

### 44.2 9 角色路由

```python
class LLMRole(Enum):
    QUERY = "query"             # 主推理：qwen3.7-max
    COMPRESS = "compress"       # 上下文压缩：qwen3.6-plus
    PLANNING = "planning"       # 规划/分类：qwen3.6-plus
    ROUTER = "router"           # 路由决策：qwen3-1.7b
    FAST = "fast"               # 快速响应：qwen3-1.7b
    CHEAP_CRITIC = "cheap_critic"  # 廉价审校：qwen3.6-plus
    KNOWLEDGE = "knowledge"     # 知识编译：qwen3.6-plus
    IDENTITY = "identity"       # 身份生成：qwen3.6-plus
    VISION = "vision"           # 视觉分析：qwen3-vl
```

| 角色 | 模型 | 用途 | 延迟要求 |
|------|------|------|---------|
| QUERY | qwen3.7-max | 主推理、复杂回答生成 | <30s |
| COMPRESS | qwen3.6-plus | 上下文压缩 | <5s |
| PLANNING | qwen3.6-plus | 意图分类、规划生成 | <3s |
| ROUTER | qwen3-1.7b | 快速路由决策 | <500ms |
| FAST | qwen3-1.7b | 简单问答、工具调用 | <1s |
| CHEAP_CRITIC | qwen3.6-plus | 经济型审校 | <5s |
| KNOWLEDGE | qwen3.6-plus | 知识图谱编译 | <10s |
| IDENTITY | qwen3.6-plus | 系统身份问答 | <3s |
| VISION | qwen3-vl | 图像/图表分析 | <15s |

### 44.3 CircuitBreaker（熔断器）

每个 LLM 角色有独立的熔断器，防止级联故障：

```
状态转换：
  CLOSED ──(失败次数 > 阈值)──> OPEN
  OPEN   ──(冷却时间到期)────> HALF_OPEN
  HALF_OPEN ──(成功)─────────> CLOSED
  HALF_OPEN ──(失败)─────────> OPEN
```

**熔断器配置**：
- 失败阈值：3 次连续失败
- 冷却时间：30 秒
- 半开状态允许 1 个探测请求

### 44.4 离线降级

当 LLM 服务不可用时，Gateway 提供 `_offline_fallback_response()` 多角色覆盖：

```python
def _offline_fallback_response(role: LLMRole, messages: list) -> str:
    """离线降级回答 — 根据角色返回适当的降级消息。"""
```

- **QUERY 角色**：返回 "I'm temporarily unable to process complex queries"
- **PLANNING 角色**：返回默认计划（direct_answer）
- **ROUTER 角色**：返回默认路由（general_qa）

### 44.5 OpenAICompatibleAdapter

```python
class OpenAICompatibleAdapter(BaseLLMAdapter):
    """适配所有 OpenAI 兼容 API：
    OpenAI, DashScope/Qwen, Azure OpenAI, vLLM, Ollama 等。
    """
    def __init__(self, config: LLMConfig) -> None:
        self._client = None  # AsyncOpenAI 客户端
        self._http_client = None  # httpx.AsyncClient
```

**连接配置**：
- 连接超时：15 秒
- 读写超时：按角色配置
- 连接池：最大保活 10，最大连接 50
- 支持 HTTP 代理（通过 `trust_env=True`）

### 44.6 模型调用追踪

```python
@contextmanager
def capture_model_calls() -> Iterator[list[dict[str, Any]]]:
    """捕获一次用户回合中所有成功的模型调用。"""
    calls: list[dict[str, Any]] = []
    token = _model_call_capture.set(calls)
    try:
        yield calls
    finally:
        _model_call_capture.reset(token)
```

每次模型调用记录：`{id, role, model, latency_ms}`，用于回合级成本归因和性能分析。

### 44.7 系统身份守卫

```python
def _post_process_identity_response(messages: list[LLMMessage], content: str) -> str:
    """身份响应后处理 — 确保系统身份一致性。"""
```

- 检测用户是否在询问系统身份
- 强制使用 `CANONICAL_IDENTITY_RESPONSE` 模板
- 防止 LLM 幻觉出错误身份信息

---

## Chapter 45: 数据认知层

### 45.1 概述

数据认知层（Data Cognition Layer）是 Text2SQL 能力的核心抽象层，将自然语言查询转换为结构化 SQL 查询。它由 **SemanticLayer**（语义层）、**SQLPlanner**（SQL 规划器）、**SQLBuilder**（SQL 构建器）和 **SQLValidator**（SQL 验证器）组成。

源文件：`kernel/data_cognition/semantic_layer.py`, `kernel/data_cognition/types.py`

### 45.2 SemanticLayer（语义层）

语义层将业务术语映射到数据库构造，使用户可以用自然语言查询而不需要了解底层表结构：

```python
@dataclass
class DimensionMapping:
    column: str          # 数据库列名
    table: str = ""      # 表名
    value_map: dict[str, str] = field(default_factory=dict)  # 值映射
    description: str = ""  # 描述

@dataclass
class TimeMacroDef:
    pattern: str         # 如 "今天", "本周", "上个月"
    column: str          # 时间列名
    table: str = ""
    operator: str = ">="
    days: int = 0
    sql_template: str = ""

class SemanticLayer:
    def __init__(self, semantic_config: dict[str, Any] | None = None): ...
    def resolve(self, query: str, dialect: SQLDialectSpec | None = None) -> SemanticContext: ...
```

**语义配置结构**：
```yaml
dimensions:
  地区:
    column: region_name
    table: sales
    value_map:
      华东: east_china
      华南: south_china
metrics:
  销售额: SUM(amount)
  订单数: COUNT(DISTINCT order_id)
time_macros:
  - pattern: 今天
    column: created_at
    days: 0
    sql_template: "DATE(created_at) = CURRENT_DATE"
```

### 45.3 核心类型

```python
@dataclass
class SQLPlan:
    tables: list[str]     # 涉及的表
    metrics: list[str]    # 指标
    filters: list[str]    # 过滤条件
    sql: str = ""         # 最终 SQL

@dataclass
class DataQueryResult:
    sql: str
    rows: list[dict[str, Any]]
    summary: str = ""
    confidence: float = 0.0
    db_id: str = "default"

@dataclass
class SemanticContext:
    dimension_mappings: dict[str, dict[str, Any]]
    metric_defs: dict[str, str]
    time_macros: list[dict[str, Any]]
    resolved_sql_fragments: list[str]

@dataclass
class CandidateSQL:
    sql: str
    score: float = 0.0
    features: dict[str, Any]
    source_template: str = ""

@dataclass
class LogicalPlan:
    """意图与 SQL 之间的中间表示。"""
    tables: list[str]
    columns: list[str]
    conditions: list[str]
    group_by: list[str]
    order_by: list[str]
    limit: int = 0
```

### 45.4 SQL 方言支持

`kernel/data_cognition/sql_dialect.py` 提供多数据库方言支持：

| 方言 | 数据库 | 特性 |
|------|--------|------|
| PostgreSQL | PostgreSQL 14+ | 窗口函数、CTE、JSONB |
| MySQL | MySQL 8.0+ | 窗口函数、CTE |
| ClickHouse | ClickHouse 22+ | 聚合引擎、物化视图 |

### 45.5 Text2SQL 认知管线

```
用户查询 → SemanticLayer.resolve()
  → SQLPlanner.plan() → LogicalPlan
  → SQLBuilder.build() → CandidateSQL[]
  → SQLRanker.rank() → 最佳 SQL
  → SQLValidator.validate() → 安全校验
  → execute() → DataQueryResult
```

---

## Chapter 46: 插件系统

### 46.1 概述

OpenTrace 的插件系统采用统一接口设计，所有外部能力（记忆、文档、Web、工具、知识）均通过插件接入认知内核。插件返回的数据被视为「候选认知材料」，经证据总线排序融合后才形成最终回答。

源文件：`plugins/base.py`, `plugins/selector.py`

### 46.2 插件基类

```python
@dataclass
class PluginResult:
    plugin_name: str
    content: str
    confidence: float = 1.0        # 0.0 - 1.0
    source_type: str = "unknown"   # memory|document|web|tool|knowledge
    metadata: dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0

class BasePlugin(ABC):
    name: str = "base"
    description: str = ""
    version: str = "1.0"

    @abstractmethod
    async def execute(self, query: str, context: "UnifiedContext") -> PluginResult:
        """所有插件必须实现此接口。"""
        ...

    async def health_check(self) -> bool:
        return True
```

### 46.3 插件清单

| 插件 | 文件 | 类型 | 说明 |
|------|------|------|------|
| MemoryPlugin | `plugins/memory_plugin.py` | memory | 记忆检索与存储 |
| DocumentPlugin | `plugins/document_plugin.py` | document | 文档检索（RAG） |
| WebPlugin | `plugins/web_plugin.py` | web | 联网搜索 |
| ToolPlugin | `plugins/tool_plugin.py` | tool | 工具调用 |
| KnowledgePlugin | `plugins/knowledge_plugin.py` | knowledge | 知识库查询 |
| DocumentRetrieval | `plugins/document_retrieval.py` | document | 文档混合检索 |
| StructuredTool | `plugins/structured_tool.py` | tool | 结构化工具调用 |
| CodePlugin | `plugins/code/interpreter.py` | code | 代码解释器 |
| ChartPlugin | `plugins/chart/` | chart | 图表生成 |
| FilePlugin | `plugins/file/sandbox.py` | file | 文件沙箱 |

### 46.4 插件选择器

`PluginSelector` 根据路由决策自动选择插件组合：

```python
PLUGIN_RULES: dict[str, list[str]] = {
    "FAST":        ["memory"],                          # 快速路径：仅记忆
    "REASON":      ["memory", "document", "knowledge"], # 推理：记忆+文档+知识
    "TOOL":        ["tool", "memory"],                  # 工具：工具+记忆
    "WEB":         ["web", "memory"],                   # 搜索：Web+记忆
    "MULTI_AGENT": ["memory", "document", "web", "tool"], # 多智能体：全部
    "direct":      ["memory"],                          # 直答：仅记忆
}
```

### 46.5 插件注册

插件通过 `_build_registry()` 延迟注册到 `CapabilityRegistry`：

```python
def _build_registry() -> dict[str, type[BasePlugin]]:
    reg: dict[str, type[BasePlugin]] = {}
    reg["memory"] = MemoryPlugin
    reg["document"] = DocumentPlugin
    reg["web"] = WebPlugin
    # 可选插件（ImportError 时跳过）
    reg["tool"] = ToolPlugin
    reg["knowledge"] = KnowledgePlugin
    return reg
```

---

## Chapter 47: 技能与规则系统

### 47.1 概述

OpenTrace 提供 **Skills Marketplace**（技能市场）和 **Rule Engine**（规则引擎），允许用户通过可安装的技能包和可配置的规则扩展系统能力。

源文件：`skills/store/marketplace.py`, `skills/runtime/`, `kernel/tools/`

### 47.2 Skills Marketplace

```python
@dataclass
class InstalledSkill:
    skill_id: str          # name@version
    name: str
    version: str
    entrypoint: str        # 入口函数
    path: str              # 安装路径
    description: str = ""
    skill_type: str = "generic"  # generic | data_query | text_analysis
    code: str = ""
    test_cases: list[dict[str, Any]] = field(default_factory=list)
    created_at: str = ""
    data_source_id: str = ""

class SkillMarketplace:
    def install_from_git(self, git_url: str, ref: str = "main") -> InstalledSkill: ...
    def install_from_code(self, name: str, code: str, description: str = "") -> InstalledSkill: ...
    def list_installed(self) -> list[InstalledSkill]: ...
    def uninstall(self, skill_id: str) -> None: ...
```

**技能安装流程**：
1. 从 Git 仓库克隆或从代码字符串创建
2. 签名验证（SHA256 哈希）
3. 测试用例验证
4. 注册到 Skill Runtime

### 47.3 Skill Runtime

```python
class SkillLoader:
    def load_manifest(self, skill_dir: Path) -> SkillManifest:
        """加载技能清单（skill.json 或 skill.yaml）。"""
        # 支持 JSON 和 YAML 两种格式
        # 自动签名验证

class SkillVerifier:
    def verify(self, manifest: SkillManifest) -> bool:
        """验证技能签名和完整性。"""
```

技能清单结构：
```json
{
    "name": "my_skill",
    "version": "1.0.0",
    "entrypoint": "main.py:run",
    "description": "技能描述",
    "skill_type": "data_query",
    "test_cases": [
        {"input": "...", "expected": "..."}
    ]
}
```

### 47.4 Rule Engine（规则引擎）

规则引擎通过 `agents/rule_engine_agent.py` 实现，支持：
- **关键词匹配**：快速规则触发
- **LLM 解释**：复杂规则语义理解
- **灰度发布**：`kernel_rule_grayscale_enabled` 控制规则灰度
- **事件响应**：规则触发后的自动动作

### 47.5 内置工具集

`kernel/tools/` 提供内置工具：

| 工具 | 功能 | 快速路径 |
|------|------|---------|
| Weather | 天气查询 | ✅ `tool.weather` |
| DateTime | 时间日期 | ✅ `tool.datetime` |
| Calculator | 数学计算 | ✅ 表达式求值 |
| CodeExecutor | 代码执行 | 需沙箱权限 |

---

## Chapter 48: 连接器与 SDK

### 48.1 概述

OpenTrace 的连接器系统提供与外部服务（如 Google Drive、Notion、Slack 等）的标准化集成，支持 OAuth 2.0 认证和资源同步。

源文件：`connectors/registry.py`, `connectors/sdk/protocol.py`, `connectors/security.py`

### 48.2 ConnectorRegistry

```python
class ConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, BaseConnector] = {}

    def register(self, name: str, connector: BaseConnector) -> None: ...
    def get(self, name: str) -> BaseConnector: ...
    def list(self) -> list[dict[str, Any]]: ...

connector_registry = ConnectorRegistry()
```

### 48.3 BaseConnector SDK 协议

```python
@dataclass
class CredentialRef:
    provider: str
    account_id: str
    access_token: str = ""
    refresh_token: str = ""
    expires_at: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class ConnectorResource:
    id: str
    type: str
    title: str
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

@dataclass
class SyncResult:
    items: list[ConnectorResource] = field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False

class BaseConnector(Protocol):
    name: str

    async def authorize_url(self, user_id: str, redirect_uri: str, state: str) -> str: ...
    async def exchange_code(self, user_id: str, code: str, redirect_uri: str) -> CredentialRef: ...
    async def refresh_token(self, credential: CredentialRef) -> CredentialRef: ...
    async def list_resources(self, credential: CredentialRef, cursor: str | None = None,
                             limit: int = 20) -> list[ConnectorResource]: ...
    async def fetch_resource(self, credential: CredentialRef, resource_id: str) -> ConnectorResource: ...
    async def sync(self, credential: CredentialRef, cursor: str | None = None,
                   limit: int = 20) -> SyncResult: ...
```

### 48.4 OAuth 安全

```python
def validate_connector_redirect_uri(redirect_uri: str) -> str:
    """验证重定向 URI 是否在白名单中。"""
    # 检查 scheme (http/https)
    # 检查 origin 是否在 connector_redirect_origin_list 中

def issue_connector_oauth_state(*, user_id: str, provider: str,
                                redirect_uri: str, tenant_id: str = "default",
                                workspace_id: str = "default",
                                client_state: str = "") -> str:
    """签发 OAuth state token（JWT 编码）。"""
```

**OAuth 安全特性**：
- 重定向 URI 白名单验证
- State 参数 JWT 签名防 CSRF
- Token 加密存储
- 自动 Token 刷新

### 48.5 连接器 API

API 端点（`gateway/api_gateway/routers/connectors.py`）：
- `GET /api/v1/connectors` — 列出可用连接器
- `POST /api/v1/connectors/{name}/authorize` — 发起 OAuth 授权
- `POST /api/v1/connectors/{name}/callback` — OAuth 回调
- `GET /api/v1/connectors/{name}/resources` — 列出资源
- `POST /api/v1/connectors/{name}/sync` — 触发同步

---

## Chapter 49: 演化与学习

### 49.1 概述

OpenTrace 的演化与学习系统包含两个维度：**运行时自优化**（SelfOptimizingRuntime）和**记忆演化**（MemoryEvolution），通过反馈闭环持续提升系统表现。

源文件：`kernel/runtime/self_optimizing_runtime.py`, `memory/evolution/evolution.py`

### 49.2 运行时自优化

```python
@dataclass
class OptimizationHint:
    dimension: str   # replan_budget | critic_threshold | capability_preference | context_tokens
    action: str      # tighten | relax | prefer | avoid
    delta: float = 0.0
    reason: str = ""
    capped: bool = False  # 是否被治理上限约束

@dataclass
class SelfOptimizationReport:
    hints: list[OptimizationHint] = field(default_factory=list)
    applied: bool = False
    session_id: str = ""
```

**优化维度**：
- `replan_budget` — 调整重规划预算
- `critic_threshold` — 调整审校严格度
- `capability_preference` — 调优能力偏好
- `context_tokens` — 调整上下文 Token 分配

**确定性优化逻辑**：

```python
def compute_optimization_hints(*, health: dict, adaptive_risk_score: float = 0.0,
                                replanned: bool = False, reflection_round: int = 0,
                                coverage_score: float | None = None) -> SelfOptimizationReport:
    """确定性优化提示 — 不绕过治理，仅生成元数据建议。"""
    hints = []
    drift = float(health.get("reasoning_drift", 0.0) or 0.0)
    saturation = float(health.get("cognitive_saturation", 0.0) or 0.0)

    if drift > 0.55 or adaptive_risk_score > 0.65:
        hints.append(OptimizationHint(dimension="critic_threshold", action="tighten",
                                      delta=0.1, reason="High reasoning drift detected"))
    # ...
```

**安全约束**：
- `kernel_self_optimizing_runtime_apply: bool = False` — 默认不自动应用优化
- 所有优化建议需经治理中心审批
- 优化幅度有上限（`capped=True`）

### 49.3 记忆演化

记忆演化系统实现了 **Case → Pattern → Skill** 的三级抽象管线：

```python
@dataclass
class MemoryPattern:
    pattern_id: str
    description: str
    strategy: str
    source_cases: list[str]    # 来源案例
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)

@dataclass
class MemorySkill:
    skill_id: str
    name: str
    description: str
    trigger_conditions: list[str]  # 触发条件
    action_template: str = ""      # 动作模板
    weight: float = 1.0
    use_count: int = 0
    created_at: float = field(default_factory=time.time)
```

**演化管线**：
```
MemoryCompressor: 对话记忆 → 压缩案例
MemoryEvolution: 案例聚类 → 识别模式
MemoryReinforcement: 模式抽象 → 生成技能
```

### 49.4 Data Flywheel（数据飞轮）

数据飞轮通过以下闭环实现持续改进：
1. **收集**：每次回合的反馈信号（用户评分、审校评分、覆盖率）
2. **分析**：识别成功模式和失败模式
3. **优化**：生成优化提示和策略调整
4. **验证**：A/B 测试或灰度验证优化效果
5. **推广**：将验证通过的优化全局应用

---

## Chapter 50: 确定性重放与审计

### 50.1 概述

OpenTrace 的确定性重放系统在认知管线的每个关键阶段边界捕获完整运行时状态，支持时间点回放和认知决策调试。这对于审计合规、问题排查和行为复现至关重要。

源文件：`kernel/runtime/replay/runtime_snapshot.py`

### 50.2 RuntimeSnapshot（运行时快照）

```python
@dataclass
class RuntimeSnapshot:
    """决策点处运行时状态的完整快照。"""
    snapshot_id: str        # UUID
    phase: str              # pre_rewrite | post_understanding | post_planning |
                            # post_execution | post_fusion
    timestamp: str          # ISO 8601
    request_id: str
    session_id: str

    # 查询状态
    query: str = ""
    rewritten_query: str = ""
    conversation_turn: int = 0

    # 认知状态
    understanding_summary: dict[str, Any] = field(default_factory=dict)
    cognitive_plan_summary: dict[str, Any] = field(default_factory=dict)
    execution_plan_summary: dict[str, Any] = field(default_factory=dict)

    # 证据状态
    evidence_count: int = 0
    evidence_summary: dict[str, int] = field(default_factory=dict)  # source → count

    # 指标
    total_latency_ms: int = 0
    total_tokens: int = 0
    error: str = ""
```

### 50.3 快照捕获点

在认知管线中，5 个阶段边界触发快照捕获：

| 阶段 | 快照 ID | 捕获内容 |
|------|---------|---------|
| 改写后 | post_rewrite | 原始查询 + 改写后查询 |
| 理解后 | post_understanding | 理解摘要（目标 + 风险） |
| 规划后 | post_planning | 认知计划 + 执行计划摘要 |
| 执行后 | post_execution | 证据状态 + 来源分布 |
| 融合后 | post_fusion | 融合结果 + 审校评分 |

### 50.4 RuntimeSnapshotStore

```python
class RuntimeSnapshotStore:
    """运行时快照的内存存储。"""
    def __init__(self, max_per_session: int = 20) -> None:
        self._snapshots: list[RuntimeSnapshot] = []
        self._by_session: dict[str, list[RuntimeSnapshot]] = {}
        self.max_per_session = max_per_session

    def capture(self, phase: str, request_id: str = "",
                session_id: str = "", **kwargs) -> RuntimeSnapshot: ...

    def get_by_session(self, session_id: str) -> list[RuntimeSnapshot]: ...

    def get_by_request(self, request_id: str) -> list[RuntimeSnapshot]: ...
```

### 50.5 执行重放

重放能力通过 `kernel/runtime/replay/execution_replay.py` 实现：
- 基于快照的时间点状态恢复
- 支持 Prompt 级别的重放
- 支持运行时状态差异对比
- 用于审计合规和行为调试

### 50.6 审计事件

审计 API（`gateway/api_gateway/routers/audit.py`）提供：
- `GET /api/v1/audit/events` — 查询审计事件
- `GET /api/v1/audit/snapshots/{session_id}` — 查看会话快照
- `POST /api/v1/audit/replay/{request_id}` — 触发重放

---

# Part VIII: 运维与开发

## Chapter 51: 配置参考

### 51.1 概述

OpenTrace 的所有配置通过 `infra/config/settings.py` 集中管理，基于 **pydantic-settings** 从环境变量和 `.env` 文件加载。配置分为多个子块，支持生产环境覆盖。

源文件：`infra/config/settings.py`

### 51.2 数据库配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `database_url` | `postgresql+asyncpg://postgres:password@localhost:5432/opentrace_v2` | 主数据库连接 |
| `token_db_url` | 同上 | Token 数据库连接 |
| `pool_size` | 10 | 连接池基础大小 |
| `max_overflow` | 20 | 最大溢出连接数 |
| `pool_timeout` | 30 | 连接超时（秒） |
| `pool_recycle` | 1800 | 连接回收周期（秒） |

### 51.3 Redis 配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `redis_url` | `redis://localhost:6379/10` | Redis 连接 URL |
| `redis_session_db` | 10 | 会话 DB |
| `redis_cache_db` | 11 | 缓存 DB |
| `redis_memory_db` | 12 | 记忆 DB |
| `redis_queue_db` | 13 | 队列 DB |
| `redis_rate_limit_db` | 14 | 限流 DB |
| `redis_pubsub_db` | 15 | 发布订阅 DB |

### 51.4 LLM 模型配置（9 角色）

| 角色 | 模型配置前缀 | 默认模型 |
|------|-------------|---------|
| QUERY | `default_llm_query_*` | qwen3.7-max |
| COMPRESS | `default_llm_compress_*` | qwen3.6-plus |
| PLANNING | `default_llm_planing_*` | qwen3.6-plus |
| SeniorShort | `default_llm_seniorshort_*` | qwen3.6-plus |
| MiddleShort | `default_llm_middleshort_*` | qwen3-8b |
| JuniorShort | `default_llm_juniorshort_*` | qwen3-1.7b |
| IDENTITY | `default_llm_identity_*` | qwen3.6-plus |
| KNOWLEDGE | `default_llm_knowledge_*` | qwen3.6-plus |
| VISION | `default_llm_vision_*` | qwen3-vl |

每个角色配置包含：`provider`, `model`, `base_url`, `api_key`。

### 51.5 Feature Flag 分类参考

**Agent 控制**（20+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `kernel_agent_enabled` | True | Agent 主开关 |
| `kernel_agent_data_enabled` | True | DataAgent 开关 |
| `kernel_agent_tool_enabled` | True | ToolAgent 开关 |
| `kernel_agent_web_enabled` | True | WebAgent 开关 |
| `kernel_agent_rag_enabled` | True | RAGAgent 开关 |
| `kernel_agent_vision_enabled` | True | VisionAgent 开关 |
| `kernel_agent_max_parallel` | 5 | 最大并行 Agent 数 |
| `kernel_agent_max_retry` | 1 | Agent 最大重试次数 |
| `kernel_agent_timeout_sec` | 30 | Agent 超时（秒） |
| `kernel_agent_dag_scheduling_enabled` | True | DAG 调度 |
| `kernel_agent_speculative_execution_enabled` | True | 推测执行 |
| `kernel_agent_runtime_supervisor_enabled` | True | 运行时监督器 |
| `kernel_agent_capability_executor_mode` | True | 能力执行器模式 |

**认知运行时**（30+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `kernel_runtime_rewrite_enabled` | True | 查询改写 |
| `kernel_runtime_understanding_enabled` | True | 深度理解 |
| `kernel_cognitive_planner_v2_enabled` | True | V2 认知规划器 |
| `kernel_runtime_capability_graph_enabled` | True | 能力图构建 |
| `kernel_runtime_evidence_fusion_critic_enabled` | True | 证据融合+审校 |
| `kernel_runtime_artifact_composer_enabled` | True | 制品合成 |
| `kernel_runtime_workspace_enabled` | True | 工作空间 |
| `kernel_cognitive_iteration_enabled` | True | 认知迭代 |
| `kernel_cognitive_iteration_max` | 2 | 最大迭代次数 |
| `kernel_context_compressor_enabled` | True | 上下文压缩 |
| `kernel_evidence_lifecycle_enabled` | True | 证据生命周期 |
| `kernel_runtime_replay_enabled` | True | 确定性重放 |
| `kernel_runtime_phase_transition_strict` | True | 阶段转换严格模式 |

**V5 路由层**（10+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `kernel_v5_routing_enabled` | True | V5 路由主开关 |
| `kernel_l0_rule_router_enabled` | True | L0 规则路由 |
| `kernel_l1_tiny_router_enabled` | True | L1 TinyRouter |
| `kernel_semantic_cache_enabled` | True | 语义缓存 |
| `kernel_semantic_cache_threshold` | 0.92 | 缓存相似度阈值 |
| `kernel_semantic_cache_ttl_seconds` | 3600 | 缓存 TTL |
| `kernel_semantic_cache_max_entries` | 10000 | 最大缓存条目 |
| `kernel_tool_fast_path_enabled` | True | 工具快速路径 |

**多轮对话**（10+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `kernel_conversation_state_enabled` | True | 对话状态管理 |
| `kernel_clarification_gate_enabled` | True | 澄清门控 |
| `kernel_correction_detection_enabled` | True | 纠错检测 |
| `kernel_dst_enabled` | True | 对话状态追踪 |
| `kernel_context_composer_enabled` | True | 上下文组装 |
| `kernel_conversation_branching_enabled` | True | 对话分支 |
| `kernel_revise_loop_enabled` | True | 修订循环 |
| `kernel_user_profiling_enabled` | True | 用户画像 |
| `context_window_max_tokens` | 8192 | 上下文窗口上限 |
| `context_max_history_tokens` | 4096 | 历史消息 Token 上限 |

**能力智能**（10+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `kernel_capability_intelligence_enabled` | True | 能力智能主开关 |
| `kernel_capability_knowledge_graph_enabled` | True | 能力知识图谱 |
| `kernel_capability_reasoner_enabled` | True | 能力推理器 |
| `kernel_capability_execution_memory_enabled` | True | 执行记忆 |
| `kernel_capability_strategy_memory_enabled` | True | 策略记忆 |
| `kernel_capability_evolution_enabled` | True | 能力演化 |
| `kernel_capability_score_ranking_enabled` | True | 能力评分排序 |
| `kernel_claim_graph_enabled` | True | 声明图 |
| `kernel_web_coverage_evaluator_enabled` | True | Web 覆盖评估 |

**DataAgent V2**（20+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `data_agent_v2_enabled` | True | DataAgent V2 主开关 |
| `data_agent_v2_knowledge_retriever_enabled` | True | 知识检索 |
| `data_agent_v2_intent_enabled` | True | 意图识别 |
| `data_agent_v2_entity_enabled` | True | 实体识别 |
| `data_agent_v2_metric_enabled` | True | 指标识别 |
| `data_agent_v2_planner_enabled` | True | SQL 规划 |
| `data_agent_v2_compiler_enabled` | True | SQL 编译 |
| `data_agent_v2_verifier_enabled` | True | SQL 验证 |
| `data_agent_v2_dag_parallel_enabled` | True | DAG 并行 |
| `data_agent_v2_learning_enabled` | True | 学习层 |

**安全与防护**（10+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `kernel_ner_masking_enabled` | True | PII 脱敏 |
| `kernel_rule_grayscale_enabled` | True | 规则灰度 |
| `kernel_canary_auto_rollback_enabled` | True | 金丝雀自动回滚 |
| `kernel_canary_error_rate_threshold` | 0.10 | 错误率阈值 |
| `kernel_canary_latency_multiplier` | 2.0 | 延迟倍数阈值 |
| `kernel_governance_evidence_gate_enabled` | True | 证据门控 |
| `kernel_governance_risk_gate_enabled` | True | 风险门控 |

**企业多租户**（5+ flags）：

| Flag | 默认值 | 说明 |
|------|--------|------|
| `enterprise_quota_redis_enabled` | False | Redis 配额 |
| `enterprise_usage_redis_enabled` | False | Redis 用量 |
| `enterprise_tenant_rls_enabled` | False | 租户 RLS |
| `enterprise_billing_persist_enabled` | False | 计费持久化 |
| `enterprise_billing_prompt_per_million` | 0.15 | Prompt 百万 Token 价格 |
| `enterprise_billing_completion_per_million` | 0.60 | Completion 百万 Token 价格 |

### 51.6 环境变量映射

完整环境变量模板见 `.env.example`，关键环境变量：

```bash
# 数据库
DATABASE_URL=postgresql://postgres:PASSWORD@postgres:5432/opentrace_v2
TOKEN_DB_URL=postgresql://postgres:PASSWORD@postgres:5432/opentrace_v2

# Redis
REDIS_URL=redis://localhost:6379/10

# LLM
DEFAULT_LLM_QUERY_MODEL=qwen3.7-max
DEFAULT_LLM_QUERY_API_KEY=sk-xxx

# 应用
JWT_SECRET=your_jwt_secret
APP_SECRET_KEY=your_app_secret
REGISTRATION_ENABLED=true
ADMIN_EMAIL=admin@example.com

# 可观测性
TRACE_ENABLED=true
OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317
```

---

## Chapter 52: 部署指南

### 52.1 概述

OpenTrace 支持 Docker Compose 一键部署，包含 4 个核心服务：PostgreSQL、Redis、API Gateway、可选的 Jaeger/Frontend。

源文件：`docker-compose.yml`, `deploy/docker/Dockerfile`

### 52.2 Docker Compose 服务

```yaml
services:
  postgres:    # PostgreSQL 16 + pgvector
  redis:       # Redis 7 Alpine
  api:         # OpenTrace API Gateway (port 14100)
  # 可选:
  # jaeger:    # 分布式追踪 UI
  # frontend:  # 前端开发服务器 (port 14108)
```

### 52.3 快速部署

```bash
# 1. 克隆项目
git clone <repository_url>
cd opentrace

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key 等配置

# 3. 启动服务
docker compose up -d

# 4. 验证
curl http://localhost:14100/api/v1/health
```

### 52.4 Dockerfile 详解

```dockerfile
ARG PYTHON_BASE_IMAGE=python:3.11-slim
FROM ${PYTHON_BASE_IMAGE}

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl build-essential libpq-dev

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONPATH=/app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

EXPOSE 14100

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:14100/api/v1/health || exit 1

CMD ["python", "-m", "uvicorn", "gateway.api_gateway.main:app", \
     "--host", "0.0.0.0", "--port", "14100", "--workers", "2"]
```

### 52.5 健康检查

| 服务 | 检查方式 | 间隔 | 超时 |
|------|---------|------|------|
| PostgreSQL | `pg_isready -U postgres` | 10s | 5s |
| Redis | `redis-cli ping` | 10s | 3s |
| API | `curl /api/v1/health` | 30s | 10s |

### 52.6 生产环境配置

**关键安全配置**：
- 修改 `POSTGRES_PASSWORD` 默认密码
- 设置强随机 `JWT_SECRET` 和 `APP_SECRET_KEY`
- 限制 `REGISTRATION_ALLOWED_EMAIL_DOMAIN`
- 关闭 `REGISTRATION_ENABLED`（仅管理员创建用户）

**性能调优**：
- API Workers：默认 2，可增加到 `CPU 核心数 * 2`
- PostgreSQL 连接池：`pool_size=20, max_overflow=40`
- Redis 最大内存：生产环境建议 2GB+
- 关闭 `debug` 模式

**Nginx 反向代理**（推荐）：
```nginx
server {
    listen 80;
    server_name api.opentrace.example.com;
    client_max_body_size 20M;

    location / {
        proxy_pass http://localhost:14100;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_buffering off;  # 支持 SSE 流式响应
    }
}
```

### 52.7 扩缩容策略

- **API 层**：水平扩展（无状态），通过 Nginx 负载均衡
- **PostgreSQL**：读写分离、连接池（PgBouncer）
- **Redis**：哨兵模式 / 集群模式
- **Agent Worker**：独立扩展，通过 AgentMessageBus 解耦

---

## Chapter 53: 开发者指南

### 53.1 环境搭建

**前置要求**：
- Python ≥ 3.11
- PostgreSQL 16 + pgvector 扩展
- Redis 7
- Docker（可选，用于本地基础设施）

**本地开发环境**：

```bash
# 1. 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 启动基础设施
docker compose up -d postgres redis

# 4. 数据库迁移
alembic upgrade head

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 填入配置

# 6. 启动开发服务器
python -m uvicorn gateway.api_gateway.main:app --reload --port 14100
```

### 53.2 项目依赖

核心依赖见 `pyproject.toml`：

```toml
[project]
name = "opentrace"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "fastapi>=0.111.0",          # Web 框架
    "uvicorn[standard]>=0.29.0", # ASGI 服务器
    "sqlalchemy[asyncio]>=2.0.30", # ORM
    "asyncpg>=0.29.0",           # PostgreSQL 驱动
    "redis[hiredis]>=5.0.4",     # Redis 客户端
    "openai>=1.30.0",            # LLM 客户端
    "dashscope>=1.20.10",        # 阿里云 DashScope
    "pydantic>=2.7.0",           # 数据验证
    "pydantic-settings>=2.2.1",  # 配置管理
    "python-jose[cryptography]", # JWT
    "passlib[bcrypt]",           # 密码哈希
    "opentelemetry-*",           # 可观测性
    "structlog",                 # 结构化日志
    "httpx>=0.27.0",             # HTTP 客户端
]
```

### 53.3 代码规范

- **格式化**：black (line-length=100)
- **Lint**：ruff
- **类型检查**：mypy
- **Pre-commit**：自动检查

### 53.4 架构约束（必须遵守）

1. **模块间禁止直接 import**：模块间仅通过 `RuntimeContext` 通信
2. **LLM 调用必须通过 Gateway**：禁止直接调用 LLM API
3. **插件返回仅为候选材料**：不得直接作为用户回答
4. **所有回答必须由认知内核生成**：Agent 不得自行生成最终回答
5. **一次规划到位**：不允许运行时试探性 Agent 回退

### 53.5 新增 API 端点

```python
# 1. 在 gateway/api_gateway/routers/ 创建新路由文件
# 2. 在 gateway/api_gateway/main.py 中注册路由
# 3. 编写契约测试（tests/test_xxx_contract.py）
# 4. 确保通过所有测试
```

### 53.6 新增 Agent

```python
# 1. 继承 agents/base.py 中的 BaseAgent
# 2. 实现 async def execute(self, task: TaskMessage) -> AgentResult
# 3. 在 agents/bootstrap.py 中注册
# 4. 在 kernel/agent_runtime/agent_topology_manifest.yaml 中声明
# 5. 编写契约测试
```

### 53.7 新增 Feature Flag

```python
# 1. 在 infra/config/settings.py 中添加配置项
# 2. 命名规范：kernel_<subsystem>_<feature>_enabled
# 3. 默认值：生产安全优先（危险功能默认 False）
# 4. 在代码中使用：settings.kernel_xxx_enabled
# 5. 更新文档 Chapter 51 配置参考
```

---

## Chapter 54: 测试策略

### 54.1 概述

OpenTrace 采用 **契约测试（Contract Test）** 为主的测试策略，辅以单元测试和集成测试。测试文件位于 `tests/` 目录，使用 `pytest` + `pytest-asyncio`。

### 54.2 测试层次

| 层次 | 数量 | 说明 | 示例 |
|------|------|------|------|
| 契约测试 | 150+ | 验证模块间接口契约 | `test_agent_runtime_v3_contract.py` |
| 单元测试 | 30+ | 验证单个函数/类 | `test_semantic_layer.py` |
| 集成测试 | 15+ | 验证多模块协作 | `test_cognitive_core.py` |
| E2E 测试 | 5+ | 验证完整流程 | `test_chat_api_v2.py` |

### 54.3 关键测试文件

**核心契约测试**：

| 测试文件 | 验证内容 |
|---------|---------|
| `test_vnext_architecture_contract.py` | vNext 主路径架构 |
| `test_agent_runtime_v3_contract.py` | Agent Runtime V3 契约 |
| `test_cognitive_supervisor_contract.py` | 认知监督器契约 |
| `test_runtime_gateway_tier0_contract.py` | Tier 0 运行时网关 |
| `test_evidence_runtime_contract.py` | 证据运行时契约 |
| `test_fusion_critic_adaptive_contract.py` | 融合审校自适应 |
| `test_goal_driven_dag_contract.py` | 目标驱动 DAG |
| `test_v5_routing_contract.py` | V5 路由契约 |
| `test_control_plane_gate_contract.py` | 控制平面门控 |
| `test_data_agent_v2_dag_manifest_contract.py` | DataAgent V2 DAG 清单 |

**安全测试**：

| 测试文件 | 验证内容 |
|---------|---------|
| `test_zero_trust_contract.py` | 零信任安全 |
| `test_pii_and_memory_compression_contract.py` | PII 脱敏 |
| `test_connector_security.py` | 连接器安全 |
| `test_enterprise_p0_security.py` | 企业安全 |

**基础设施测试**：

| 测试文件 | 验证内容 |
|---------|---------|
| `test_alembic_single_head_contract.py` | 迁移单头 |
| `test_alembic_idempotent_contract.py` | 迁移幂等 |
| `test_quota_redis_atomic_contract.py` | 配额原子性 |
| `test_memory_graph_redis_contract.py` | 记忆图 Redis |

### 54.4 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定测试文件
pytest tests/test_agent_runtime_v3_contract.py -v

# 运行特定测试
pytest tests/ -k "test_v5_routing" -v

# 带覆盖率
pytest tests/ --cov=. --cov-report=html

# 异步测试（自动启用）
# pytest-asyncio 已配置为 auto 模式
```

### 54.5 编写测试规范

1. **测试文件命名**：`test_<module>_contract.py` 或 `test_<module>.py`
2. **测试函数命名**：`test_<feature>_<scenario>`
3. **每个测试应独立**：不依赖其他测试的状态
4. **使用 fixture**：共享设置逻辑
5. **Mock 外部依赖**：LLM 调用、外部 API 需 mock

---

## Chapter 55: 故障排查

### 55.1 常见问题

**Q: API 启动失败，报数据库连接错误**

```bash
# 检查 PostgreSQL 是否运行
docker compose ps postgres
# 检查连接配置
echo $DATABASE_URL
# 测试连接
python -c "import asyncpg; ..."
```

**Q: LLM 调用返回空或超时**

```bash
# 检查 API Key 配置
echo $DEFAULT_LLM_QUERY_API_KEY
# 检查网络连通性
curl -I https://dashscope.aliyuncs.com
# 查看熔断器状态（日志中搜索 CircuitBreaker）
```

**Q: Redis 连接失败**

```bash
# 检查 Redis 是否运行
docker compose ps redis
# 测试连接
redis-cli -p 6380 ping
```

**Q: 认知管线执行缓慢**

- 检查 `kernel_cognitive_iteration_max` 是否过大（建议 ≤ 2）
- 检查 `context_window_max_tokens` 是否过大（建议 ≤ 8192）
- 查看 Prometheus 指标中的 `TURN_DURATION`

### 55.2 调试认知管线

**启用详细日志**：

```bash
export LOG_LEVEL=DEBUG
python -m uvicorn gateway.api_gateway.main:app --reload
```

**查看运行时快照**：

```python
# 通过审计 API 获取会话快照
GET /api/v1/audit/snapshots/{session_id}
```

**追踪模型调用**：

```python
# 在回合元数据中查看 model_calls 字段
# 包含每次 LLM 调用的角色、模型、延迟
```

### 55.3 性能调优

| 问题 | 建议 |
|------|------|
| LLM 延迟高 | 使用更小的 PLANNING/ROUTER 模型 |
| 数据库慢 | 增加连接池、添加索引 |
| 内存高 | 减少 `context_max_history_tokens` |
| Agent 超时 | 增加 `kernel_agent_timeout_sec` |
| 语义缓存命中率低 | 降低 `kernel_semantic_cache_threshold` |

### 55.4 错误码参考

| 错误码 | 说明 | 解决方案 |
|--------|------|---------|
| `AUTH_001` | 认证失败 | 检查 JWT Token |
| `AUTH_002` | Token 过期 | 刷新 Token |
| `QUOTA_001` | 日配额超限 | 升级套餐或等待次日 |
| `POLICY_001` | 策略拒绝 | 检查请求内容 |
| `AGENT_001` | Agent 执行超时 | 简化查询或增加超时 |
| `AGENT_002` | Agent 执行失败 | 查看 DLQ 死信队列 |
| `LLM_001` | LLM 调用失败 | 检查 API Key 和网络 |
| `LLM_002` | 熔断器开启 | 等待冷却后自动恢复 |
| `DB_001` | 数据库连接失败 | 检查 PostgreSQL 状态 |
| `REDIS_001` | Redis 连接失败 | 检查 Redis 状态 |

---

## 附录

### 附录 A: 完整 API 端点参考

#### A.1 认证 (auth.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/auth/register` | 用户注册 |
| POST | `/api/v1/auth/login` | 用户登录 |
| POST | `/api/v1/auth/token` | 刷新 Token |
| GET | `/api/v1/auth/me` | 获取当前用户信息 |

#### A.2 Chat (chat.py, chat_v2.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/chat` | 发送消息（SSE 流式响应） |
| POST | `/api/v1/chat/v2` | V2 Chat 端点 |

#### A.3 会话 (conversations.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/conversations` | 列出会话 |
| POST | `/api/v1/conversations` | 创建会话 |
| GET | `/api/v1/conversations/{id}` | 获取会话详情 |
| DELETE | `/api/v1/conversations/{id}` | 删除会话 |
| POST | `/api/v1/conversations/{id}/archive` | 归档会话 |
| POST | `/api/v1/conversations/{id}/unarchive` | 取消归档 |
| GET | `/api/v1/conversations/{id}/messages` | 获取消息历史 |
| POST | `/api/v1/conversations/{id}/branch` | 创建分支 |

#### A.4 数据查询 (data.py, databases.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/data/query` | 自然语言查询 |
| POST | `/api/v1/data/query/stream` | 流式数据查询 |
| GET | `/api/v1/databases` | 列出数据库连接 |
| POST | `/api/v1/databases` | 添加数据库连接 |
| DELETE | `/api/v1/databases/{id}` | 删除数据库连接 |
| POST | `/api/v1/databases/{id}/sync` | 同步 Schema |
| POST | `/api/v1/databases/{id}/test` | 测试连通性 |

#### A.5 文档 (documents.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/documents/upload` | 上传文档 |
| GET | `/api/v1/documents` | 列出文档 |
| DELETE | `/api/v1/documents/{id}` | 删除文档 |
| POST | `/api/v1/documents/search` | 向量检索 |

#### A.6 知识库 (knowledge.py, knowledge_v2.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/knowledge` | 列出知识源 |
| POST | `/api/v1/knowledge` | 创建知识源 |
| DELETE | `/api/v1/knowledge/{id}` | 删除知识源 |
| POST | `/api/v1/knowledge/{id}/compile` | 编译知识 |

#### A.7 记忆 (memories.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/memories` | 查询记忆 |
| DELETE | `/api/v1/memories/{id}` | 删除记忆 |

#### A.8 技能 (skills.py, analytical_skills.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/skills` | 列出已安装技能 |
| POST | `/api/v1/skills/install` | 安装技能 |
| DELETE | `/api/v1/skills/{id}` | 卸载技能 |
| GET | `/api/v1/analytical-skills` | 列出分析技能 |

#### A.9 任务 (tasks.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/tasks` | 列出任务 |
| GET | `/api/v1/tasks/{id}` | 获取任务详情 |

#### A.10 连接器 (connectors.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/connectors` | 列出连接器 |
| POST | `/api/v1/connectors/{name}/authorize` | 发起 OAuth |
| POST | `/api/v1/connectors/{name}/callback` | OAuth 回调 |
| GET | `/api/v1/connectors/{name}/resources` | 列出资源 |
| POST | `/api/v1/connectors/{name}/sync` | 触发同步 |

#### A.11 管理 (admin.py, enterprise_admin.py)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/admin/users` | 列出用户 |
| GET | `/api/v1/admin/tenants` | 列出租户 |
| GET | `/api/v1/admin/metrics` | 系统指标 |
| GET | `/api/v1/enterprise/quotas` | 配额管理 |
| GET | `/api/v1/enterprise/billing` | 计费管理 |

#### A.12 系统 (health.py, prometheus.py, audit.py, sandbox.py, etc.)

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/prometheus` | Prometheus 指标 |
| GET | `/api/v1/audit/events` | 审计事件 |
| GET | `/api/v1/audit/snapshots/{session_id}` | 查看快照 |
| POST | `/api/v1/audit/replay/{request_id}` | 触发重放 |
| POST | `/api/v1/sandbox/execute` | 沙箱代码执行 |
| POST | `/api/v1/feedback` | 提交反馈 |
| GET | `/api/v1/cognitive/events` | 认知事件 |
| GET | `/api/v1/personalization` | 个性化设置 |
| GET | `/api/v1/ui-settings` | UI 设置 |
| GET | `/api/v1/responses` | V2 响应 |
| GET | `/api/v1/metrics` | 业务指标 |
| GET | `/api/v1/rules` | 规则管理 |

### 附录 B: 术语表

| 术语 | 英文 | 定义 |
|------|------|------|
| 认知内核 | Cognitive Kernel | 系统唯一中枢，协调所有认知能力 |
| 认知管线 | Cognitive Pipeline | 请求处理的完整阶段序列 |
| 认知执行器 | Cognitive Executive | 认知管线的运行时执行引擎 |
| 证据 | Evidence | 结构化知识单元，带来源和置信度 |
| 证据总线 | Evidence Bus | 证据的收集、排序、融合中心 |
| 融合引擎 | Fusion Engine | 多源证据的语义融合 |
| 审校引擎 | Critic Engine | 输出质量的评估与改进 |
| 认知规划 | Cognitive Planning | 将查询投影为执行计划 |
| 目标图 | GoalGraph | 用户意图的分层目标表示 |
| 意图锁 | IntentLock | 保护用户原始意图不被修改 |
| 上下文织物 | Context Fabric | 统一上下文组装系统 |
| 能力拓扑 | Capability Topology | Agent 和能力的注册与路由 |
| 真理维护 | Truth Maintenance | 记忆置信度衰减和矛盾检测 |
| 确定性重放 | Deterministic Replay | 基于快照的认知决策回放 |
| 数据飞轮 | Data Flywheel | 反馈驱动的持续改进闭环 |
| 语义层 | Semantic Layer | 业务术语到数据库的映射 |
| 契约测试 | Contract Test | 验证模块间接口契约的测试 |

### 附录 C: 架构决策记录（ADR）索引

| 编号 | 主题 | 文件路径 |
|------|------|----------|
| ADR-001 | vNext 主路径架构 | `docs/adr/001-vnext-main-path.md` |
| ADR-002 | 治理分层架构 | `docs/adr/002-governance-layers.md` |
| ADR-003 | 记忆织网架构 | `docs/adr/003-memory-fabric.md` |

### 附录 D: 项目文件结构

```
opentrace/
├── agents/                    # 智能体系统
│   ├── base.py               # Agent 基类
│   ├── bootstrap.py          # Agent 引导注册
│   ├── rag_agent.py          # RAG Agent
│   ├── web_agent.py          # Web Agent
│   ├── data_agent_v2/        # DataAgent V2 (25+ 子代理)
│   ├── tool_agent.py         # 工具 Agent
│   ├── vision_agent.py       # 视觉 Agent
│   └── ...
├── gateway/
│   └── api_gateway/
│       ├── main.py           # FastAPI 应用入口
│       └── routers/          # 29 个路由模块
├── kernel/                    # 认知内核
│   ├── cognitive_kernel.py   # 内核入口
│   ├── runtime_gateway.py    # 运行时网关
│   ├── runtime/              # 认知运行时
│   ├── goal/                 # 目标系统
│   ├── governance/           # 治理中心
│   ├── cognitive_supervisor/ # 认知监督器
│   ├── capability_intelligence/ # 能力智能
│   ├── cognition/            # 认知模型
│   ├── protocol/             # 协议契约
│   └── ...
├── memory/                    # 记忆系统
│   ├── working_memory/       # 工作记忆
│   ├── episodic_memory/      # 情景记忆
│   ├── semantic_memory/      # 语义记忆
│   ├── procedural_memory/    # 程序记忆
│   ├── fabric/               # 记忆织网
│   └── evolution/            # 记忆演化
├── model/                     # 模型服务
│   ├── model_gateway/        # 模型网关
│   └── llm_adapter/          # LLM 适配器
├── infra/                     # 基础设施
│   ├── config/               # 配置管理
│   ├── storage/              # 数据库
│   ├── cache/                # Redis 缓存
│   ├── message_bus/          # 消息总线
│   ├── observability/        # 可观测性
│   └── security/             # 安全
├── plugins/                   # 插件系统
├── skills/                    # 技能系统
├── connectors/                # 连接器
├── tenant/                    # 多租户
├── safety/                    # 安全防护
├── tests/                     # 测试 (200+)
├── docs/                      # 文档
│   ├── service/              # 服务文档
│   └── adr/                  # 架构决策记录
├── deploy/                    # 部署配置
│   └── docker/               # Dockerfile
├── docker-compose.yml        # Docker Compose
├── pyproject.toml            # 项目配置
└── .env.example              # 环境变量模板
```

---

> **文档结束** — OpenTrace v2.0.0 完整项目文档
>
> 本文档涵盖 8 个 Part、55 个 Chapter、4 个附录，总计 4500+ 行。
> 所有内容均从项目源码直接分析得出，可追溯至具体源文件。
> 最后更新：2026-07-12

