# OpenTrace 项目技术文档

> 从零开始，基于实际代码逐行梳理生成。最后更新：2026-05-26。

---

## 目录

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [系统架构](#3-系统架构)
4. [目录结构](#4-目录结构)
5. [Gateway 层](#5-gateway-层)
6. [认知内核](#6-认知内核)
7. [V5 分层路由](#7-v5-分层路由)
8. [V4 编排器](#8-v4-编排器)
9. [Cognitive Runtime V2](#9-cognitive-runtime-v2)
10. [Agent 集群](#10-agent-集群)
11. [Model Gateway](#11-model-gateway)
12. [Memory System](#12-memory-system)
13. [Data Agent V2](#13-data-agent-v2)
14. [Capability Intelligence](#14-capability-intelligence)
15. [Safety 安全层](#15-safety-安全层)
16. [Infrastructure 基础设施](#16-infrastructure-基础设施)
17. [Execution Plane](#17-execution-plane)
18. [Feature Flags 总览](#18-feature-flags-总览)
19. [配置说明](#19-配置说明)
20. [Docker 部署](#20-docker-部署)
21. [测试体系](#21-测试体系)
22. [开发规范](#22-开发规范)

---

## 1. 项目概述

OpenTrace 是一个**认知内核驱动的 Agent 系统**。核心理念：所有 LLM 调用由认知内核统一管理，Agent/Tool/Plugin 只是"候选认知材料"的提供者。

**核心能力**：
- 对话式问答（同步 + SSE 流式）、工具调用（时间/天气/计算器/代码）
- RAG 文档问答（pgvector 向量检索 + 动态分数阈值 + 自动 Web 降级）
- Text2SQL 数据查询（V1 + V2 双管线）
- 联网搜索（Serper API）
- 多层记忆（工作/语义/情节/程序 + 演进 + 时序索引 + 治理）
- 推理链可视化、规则引擎、技能系统
- 安全防护（NER PII 脱敏、金丝雀测试、XAI 审计）

### 1.1 版本演进

| 版本 | 核心能力 |
|------|---------|
| V4 | Plan → Dispatcher → Agent Cluster → Fusion → Critic（稳定默认） |
| V5 | V4 + L0 规则路由 + L0.5 语义缓存 + L1 小模型路由 + 复杂度引擎 |
| V6 | V5 + 多轮对话增强（ConversationState/ResultRef/ReferenceResolver/ContextCompressor） |
| V7 | V6 + Runtime 统一运行时（RuntimeContext + UnifiedOrchestrator + EvidenceBus） |
| V8 | V7 + CognitiveExecutive 单一入口 + 10 阶段认知管线 |
| V9 | V8 + Capability Intelligence Phase 1（能力画像 + 自认知） |
| V10 | V9 + Capability Intelligence Phase 2（KG/Reasoner/ExecutionMemory/StrategyMemory/Evolution） |
| V11 | V10 + MemoryGovernance（信心衰减/矛盾检测/来源追踪）+ TemporalMemoryIndex |

### 1.2 核心设计原则

1. **唯一中枢**：所有输出由认知内核生成，禁止绕过内核直接调用 LLM
2. **候选材料**：所有插件返回的数据只是「候选认知材料」
3. **LLM 是执行器**：LLM 负责理解、编排、融合、生成
4. **协议驱动**：Prompt 是结构化、可版本化、可治理的「认知协议」
5. **Evidence First > Answer First**：信息以 Evidence 对象流通，经 Fusion→Critic→Artifact 产生最终答案
6. **Capability First > Agent First**：以能力类型而非 Agent 类型进行任务分发
7. **一次性规划**：顶级模型看全量上下文一次生成 ExecutionPlan，无 "先试 A 再补 B" 的 fallback
8. **向后兼容**：新字段有默认值，双写双读并行，零破坏性变更

---

## 2. 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| 语言 | Python 3.11+ | — |
| Web 框架 | FastAPI >=0.111.0 | Uvicorn 服务器 |
| 数据库 ORM | SQLAlchemy 2.0 (async) | PostgreSQL + pgvector |
| 数据库迁移 | Alembic | idempotent migrations |
| 缓存/队列 | Redis (hiredis) | 6 个逻辑 DB 分库 |
| LLM SDK | openai >=1.30.0 | OpenAI-compatible adapter |
| 向量嵌入 | DashScope / OpenAI / local / hash | 可配置 provider |
| 重排序 | DashScope qwen3-vl-rerank / BM25 | — |
| 配置管理 | pydantic-settings | .env 文件加载 |
| 链路追踪 | OpenTelemetry | OTLP gRPC exporter |
| 指标 | prometheus-client | counters + histograms |
| Token 计数 | tiktoken (cl100k_base) | CJK 启发式 fallback |
| 包管理 | pip (editable install) | pyproject.toml |
| 前端 | React + TypeScript + Vite | Zustand 状态管理，Vitest 测试 |
| 容器化 | Docker Compose | 6 个 service |

---

## 3. 系统架构

### 3.1 分层架构

```
Frontend (React/Vite, port 14108)
    │
    ▼
Gateway (FastAPI, port 14100)
    ├── api_gateway/routers/chat.py     ← 主聊天端点 (sync + SSE stream)
    ├── api_gateway/routers/auth.py     ← 认证
    ├── api_gateway/routers/documents.py ← 文档管理
    ├── api_gateway/routers/databases.py ← 数据源管理
    ├── ... (20 个 router)
    └── cognitive_gateway/gateway.py    ← 轻量兼容网关
    │
    ▼
Cognitive Kernel (kernel/)
    ├── cognitive_kernel.py             ← 中枢入口 run()/stream()
    │
    ├── [V5 路由层]
    │   ├── query_router_v2.py          ← L0 规则路由 (零 LLM)
    │   ├── complexity_engine.py        ← 启发式复杂度评分
    │   ├── tiny_router.py              ← L1 小模型路由 (1.7B)
    │   ├── semantic_cache.py           ← 语义缓存
    │   └── context_assembler.py        ← 上下文装配
    │
    ├── [V4 编排器]
    │   └── orchestrator_v4.py          ← Plan → Dispatch → Fusion → Critic
    │
    ├── [V8 Cognitive Runtime V2]
    │   └── runtime/
    │       ├── cognitive_executive.py  ← 10 阶段统一管线
    │       ├── orchestrator.py         ← UnifiedOrchestrator
    │       ├── executor.py             ← ExecutionRuntime
    │       ├── evidence_bus.py         ← EvidenceBus
    │       ├── fusion.py               ← FusionEngineV2
    │       └── critic.py               ← CriticEngineV2
    │
    └── [V9/V10 Capability Intelligence]
        └── capability_intelligence/
            ├── profiler.py             ← CapabilityProfiler
            ├── knowledge_graph.py      ← CapabilityKnowledgeGraph
            ├── reasoner.py             ← CapabilityReasoner
            ├── execution_memory.py     ← ExecutionMemory
            ├── strategy_memory.py      ← StrategyMemory
            └── evolution.py            ← EvolutionEngine
    │
    ▼
Agent Cluster (agents/)
    ├── data_agent.py / data_agent_v2/  ← Text2SQL
    ├── rag_agent.py                    ← 文档检索
    ├── web_agent.py                    ← 联网搜索
    ├── tool_agent.py                   ← 工具调用
    ├── rule_engine_agent.py            ← 规则引擎
    ├── vision_agent.py                 ← 视觉分析
    ├── skills_agent.py                 ← 技能执行
    └── worker.py                       ← Redis 消费者
    │
    ▼
Model Gateway (model/)
    ├── model_gateway/gateway.py        ← 9 角色 LLM 路由 + 熔断器
    ├── llm_adapter/openai_adapter.py   ← OpenAI-compatible 适配器
    ├── embedding/base.py               ← 嵌入模型工厂
    └── reranker/base.py                ← 重排序工厂
    │
    ▼
Memory System (memory/)
    ├── working_memory/                 ← 会话环形缓冲
    ├── semantic_memory/                ← 向量检索
    ├── episodic_memory/                ← Redis 事件序列
    ├── evolution/router.py             ← EvolutionMemoryRouter (9 特性)
    ├── evolution/evolution.py          ← Case→Pattern→Skill
    ├── evolution/governance.py         ← MemoryGovernance
    ├── temporal_memory/                ← 时序衰减索引
    └── value_scorer.py                 ← 价值评分
    │
    ▼
Infrastructure (infra/)
    ├── config/settings.py              ← 统一配置 (60+ flags)
    ├── storage/ (database + models)    ← PostgreSQL + 30+ ORM 模型
    ├── cache/redis_client.py           ← ShadowRedis
    ├── message_bus/agent_bus.py        ← Agent Bus (pubsub/stream)
    ├── observability/ (logger/metrics/tracer)
    ├── errors/                         ← 结构化异常
    └── security/zero_trust.py          ← 零信任 + 工具异常检测
```

### 3.2 完整请求处理链路

```
HTTP POST /api/v1/chat {query, session_id, ...}
  │
  ├─ 1. Guardrails.check_input()              ← 安全门禁
  ├─ 2. 解析 session、加载历史                  ← ChatSession + Message/TraceLog
  ├─ 3. 加载记忆/偏好/数据源/附件                ← 200+ 行上下文装配
  ├─ 4. RiskAssessment + permission token      ← 零信任
  ├─ 5. RuntimeContext 构建                    ← 统一上下文对象
  │
  ├─ 6. CognitiveKernel.run() 或 .stream()
  │     │
  │     ├─ 6a. WorkingMemory 恢复              ← Redis 持久化
  │     ├─ 6b. Identity cache 检查             ← 5 轮 TTL
  │     ├─ 6c. V5 Routing Tier:
  │     │     L0 Rule Router (零 LLM, <1ms)
  │     │       → hit: 直接返回 (identity/faq/force_mode)
  │     │       → miss: 继续
  │     │     L0.5 Semantic Cache (向量相似度 ≥0.92)
  │     │       → hit: 返回缓存答案
  │     │       → miss: 继续
  │     │     L1 ComplexityEngine + TinyRouter (1.7B)
  │     │       → simple: FAST (8B) 直接回答
  │     │       → complex: 进入全管线
  │     │
  │     ├─ 6d. Memory Context 注入             ← EvolutionMemoryRouter.retrieve()
  │     │
  │     ├─ 6e. [V8 路径] CognitiveExecutive.execute()
  │     │     Phase 1:  RewriteEngine      ← 查询规范化
  │     │     Phase 2:  UnderstandingEngine ← 深度理解
  │     │     Phase 3:  PolicyEngine        ← 安全策略
  │     │     Phase 4:  CognitivePlannerV2  ← 一次 LLM 生成 ExecutionPlan
  │     │     Phase 5:  CapabilityGraph     ← 能力图构建
  │     │     Phase 6:  ExecutionRuntime    ← DAG 并行执行
  │     │     Phase 7:  EvidenceBus         ← 证据收集 + 生命周期
  │     │     Phase 8:  FusionEngineV2      ← 证据融合
  │     │     Phase 9:  CriticEngineV2      ← 质量审校
  │     │     Phase 9.5: Capability Feedback ← 学习闭环
  │     │     Phase 10: ArtifactComposer     ← 最终产物
  │     │
  │     └─ 6f. [V4 回退路径] CognitiveOrchestratorV4.process()
  │           PlanAgent → Dispatcher → Fusion → Critic → ClarificationGate
  │
  ├─ 7. 后处理: 保存 Trace/Message/ConversationState
  ├─ 8. 异步: 记忆写入 + 语义缓存存储 + 历史索引
  └─ 9. 返回 KernelResponse (或 SSE 流)
```

---

## 4. 目录结构

```
opentrace/
├── gateway/                     # API 网关层
│   ├── api_gateway/
│   │   ├── main.py              # FastAPI app + 20 个 router 挂载
│   │   └── routers/             # 20 个路由模块 (chat/auth/documents/...)
│   └── cognitive_gateway/       # 轻量兼容网关 (Redis session)
│
├── kernel/                      # 认知内核 (~100 个文件)
│   ├── cognitive_kernel.py      # 中枢入口 CognitiveKernel
│   ├── orchestrator_v4.py       # V4 编排器 (主力)
│   ├── plan_agent.py            # 任务规划
│   ├── dispatcher.py            # 并发分发
│   ├── dag_plan.py / dag_scheduler.py  # DAG 规划
│   ├── query_router_v2.py       # L0 规则路由
│   ├── tiny_router.py           # L1 小模型路由
│   ├── complexity_engine.py     # 复杂度评分
│   ├── semantic_cache.py        # 语义缓存
│   ├── context_assembler.py     # 上下文装配
│   ├── clarification_gate.py    # 澄清追问
│   ├── conversation_state.py    # 多轮状态
│   ├── adaptive_profiles.py     # 自适应配置
│   ├── plan_memory.py           # 计划记忆
│   ├── runtime/                 # Cognitive Runtime V2 (20+ 文件)
│   │   ├── cognitive_executive.py  # 中央执行器
│   │   ├── orchestrator.py      # UnifiedOrchestrator
│   │   ├── context.py           # RuntimeContext
│   │   ├── objects.py           # Evidence/Provenance/ExecutionPlan
│   │   ├── executor.py          # ExecutionRuntime
│   │   ├── evidence_bus.py      # EvidenceBus + 生命周期
│   │   ├── fusion.py            # FusionEngineV2
│   │   ├── critic.py            # CriticEngineV2
│   │   ├── capability.py        # CapabilityRegistry
│   │   ├── rewrite_engine.py    # RewriteEngine
│   │   ├── understanding_engine.py  # UnderstandingEngine
│   │   ├── artifact_composer.py # ArtifactComposer
│   │   ├── constraint_layer.py  # 约束层
│   │   ├── event_store.py       # 事件溯源
│   │   ├── cognitive/           # CognitivePlannerV2/StrategyBuilder/...
│   │   ├── evidence/            # EvidenceLifecycle/StateMachine/Ranker
│   │   ├── memory/              # MemoryFabric/TruthMaintenance
│   │   ├── context_runtime/     # ContextCompressor/Ranker/Distiller
│   │   └── replay/              # PromptSnapshot/RuntimeSnapshot/Replay
│   ├── capability_intelligence/ # 能力智能层 (12 文件)
│   ├── cognition/               # SelfModel/EntityRegistry/TaskModel
│   ├── data_cognition/          # SemanticParser/SQLBuilder/SQLValidator
│   ├── fusion_engine/           # FusionEngine + SequenceFusion
│   ├── critic_engine/           # CriticEngine
│   ├── context/                 # QueryRewriter/ContextCompressor
│   ├── intent_engine/           # 意图识别
│   ├── epistemology/            # ContentAnnotator/OutputValidator
│   ├── meta_cognition/          # 元认知
│   ├── identity/                # 身份问答
│   ├── protocol/                # 事件/MCP/治理协议
│   └── prompt_engine/           # Prompt 引擎
│
├── agents/                      # Agent 集群
│   ├── base.py                  # BaseAgent (抽象基类)
│   ├── registry.py              # 兼容旧 API 的 AgentRegistry
│   ├── worker.py                # AgentWorker (Redis 消费者)
│   ├── data_agent.py            # DataAgent (V1/V2 wrapper)
│   ├── data_agent_v2/           # Data Agent V2 (20+ 文件)
│   ├── rag_agent.py             # RAG 检索
│   ├── web_agent.py             # Web 搜索
│   ├── tool_agent.py            # 工具调用
│   ├── rule_engine_agent.py     # 规则引擎
│   ├── vision_agent.py          # 视觉分析
│   └── skills_agent.py          # 技能执行
│
├── model/                       # Model Gateway
│   ├── model_gateway/gateway.py # 9 角色 LLM 路由 + 熔断器
│   ├── llm_adapter/             # OpenAI-compatible 适配器
│   ├── embedding/base.py        # 嵌入模型工厂
│   └── reranker/base.py         # 重排序工厂
│
├── memory/                      # Memory System
│   ├── working_memory/          # 工作记忆
│   ├── semantic_memory/         # 语义记忆 (向量检索)
│   ├── episodic_memory/         # 情节记忆 (Redis)
│   ├── memory_router/           # 基础 MemoryRouter
│   ├── evolution/               # 记忆演进
│   │   ├── evolution.py         # MemoryEvolution/Compressor/Reinforcement
│   │   ├── router.py            # EvolutionMemoryRouter (9 特性)
│   │   └── governance.py        # MemoryGovernance
│   ├── temporal_memory/         # 时序衰减索引
│   └── value_scorer.py          # 价值评分
│
├── infra/                       # Infrastructure
│   ├── config/settings.py       # 统一配置 (60+ feature flags)
│   ├── storage/                 # Database + 30+ ORM Models
│   ├── cache/redis_client.py    # ShadowRedis (6 DB)
│   ├── message_bus/             # AgentBus + CognitiveEventBus
│   ├── observability/           # Logger/Metrics/Tracer
│   ├── errors/                  # AppException + ErrorCodes
│   ├── security/zero_trust.py   # 零信任
│   └── guards/kernel_guard.py   # 内核守卫
│
├── execution/                   # Execution Plane
│   ├── dag_engine/              # DAGEngine + DAGGraph + ResourceScheduler
│   ├── data/                    # SQLExecutor + DBRouter
│   ├── tool_router/             # ToolRouter
│   └── sandbox/                 # Python 沙箱
│
├── safety/                      # Safety Layer
│   ├── masking/ner_masker.py    # PII 脱敏
│   ├── guardrails/              # 输入/输出守卫
│   ├── policy_engine/           # 安全策略引擎
│   ├── xai/cognitive_trace.py   # XAI 审计追踪
│   └── audit/                   # 审计日志
│
├── evolution/                   # 系统演进 (data_flywheel/learning/...)
├── agent_runtime/               # Agent 运行时 (planner/executor/critic/...)
├── connectors/                  # 连接器 SDK (GitHub connector)
├── plugins/                     # 插件系统 (chart/code/data/file/tool)
├── skills/                      # 技能 (runtime/store/installed)
├── tools/                       # 工具 (adapters/builtin_tools/registry)
├── services/                    # 微服务
├── sdk/                         # SDK (plugin_sdk/python_sdk)
├── sandbox_runtime/             # 沙箱运行时
├── frontend/                    # React/Vite 前端
├── tests/                       # 测试 (~90 个测试文件)
├── alembic/                     # 数据库迁移
├── scripts/                     # 运维脚本
├── deploy/                      # Docker/Helm/K8s 部署
├── .env.example                 # 环境变量模板 (~150 vars)
├── docker-compose.yml           # Docker Compose 配置
├── start.sh / stop.sh / restart.sh  # 服务管理脚本
└── CLAUDE.md                    # Claude Code 指令
```

---

## 5. Gateway 层

### 5.1 FastAPI 主应用 (`gateway/api_gateway/main.py`)

- 创建 `FastAPI(title="OpenTrace API", version="0.1.0")` 实例
- CORS 全部允许 (`allow_origins=["*"]`)
- 中间件注入 `x-request-id` 和 `x-response-time-ms` 响应头
- 两个异常处理器：`AppException` → 结构化 JSON 错误 / `Exception` → 通用错误
- 启动时：`ensure_runtime_schema()` + 启动 `memory_event_subscriber`
- 关闭时：停止 subscriber
- 挂载 20 个 Router，均在 `/api/v1` 前缀下

### 5.2 Chat Router (`gateway/api_gateway/routers/chat.py`) — 核心端点

**ChatRequest 关键字段**：
- `query`, `session_id`, `stream` (bool)
- `force_mode`: 可选值 `rag|data_query|data_analysis|anomaly_tracking|product|rule_engine|tool|skills|web|vision`
- `data_source_id`, `data_source_name`, `force_database`
- 多轮字段: `clarify_context`, `clarify_question_id`, `parent_message_id`, `attachment_ids`, `reference_id`, `state_version`
- 技能: `enabled_skills`, `disabled_skills`
- 安全: `tool_permission_token`, `confirmation_granted`

**`POST /chat` 核心流程**：
1. Guardrails 输入检查
2. 创建/验证 ChatSession
3. 加载对话历史（Message 表优先，TraceLog 回退）
4. 对话分支处理（从 parent_message_id 截断历史，加载 branch checkpoint）
5. 用户记忆/偏好加载（PreferenceLayer 分类）
6. 风险评估 (`assess_query_risk()`)
7. 数据源上下文（auto-detect 或显式指定）
8. 附件加载（最多 10 文件, 50KB 限制）
9. ConversationState 加载
10. RuntimeContext 构建
11. 发布 `chat.request.received` 事件到 CognitiveEventBus

**三种路由路径**：
- **SQL 快速路径**：用户追问 "SQL语句是什么" → 直接返回上一轮 SQL
- **Database 快速路径**：`force_database=true` → 直接 `data_query()`
- **全核路径**：`kernel.stream()` / `kernel.run()`

**流式处理**：SSE 事件队列 + Task 管理 + 取消支持 (`/chat/stop`)

**其他端点**：附件上传/列表/删除、流控停止、Graph 控制、重新生成、编辑重生成、反馈（like/dislike）

### 5.3 Cognitive Gateway (`gateway/cognitive_gateway/gateway.py`)

轻量兼容网关。`CognitiveGateway.handle()` 从 Redis 加载 session → 调用 `CognitiveOrchestrator.process()`（旧版 V3 编排器）→ 保存 session 回 Redis → 返回 `KernelResponse` 兼容包装。

---

## 6. 认知内核 (`kernel/cognitive_kernel.py`)

### 6.1 CognitiveKernel — 系统唯一中枢

**核心数据类**：
- `KernelRequest(query, session_id, user_id, history, stream, web_enabled, metadata, trace_ctx, conversation_state)` — 统一请求
- `KernelResponse(content, session_id, route, validation_score, passed_validation, hallucination_risk, intent_category, total_latency_ms, state_patch, result_refs, prompt_tokens, completion_tokens, model)` — 统一响应

**`async run(request) -> KernelResponse`** — 同步路径：

```
1. WorkingMemory 恢复       ← load_or_create_session_memory() (Redis)
2. Identity cache 检查       ← 5 轮 TTL 缓存
3. V5 Routing Tier:
   ├─ L0 RuleRouter         ← 零 LLM，<1ms
   ├─ L0.5 SemanticCache    ← 相似度 ≥0.92 命中
   └─ L1 ComplexityEngine + TinyRouter  ← 1.7B/8B 路由
4. Memory Context 注入       ← EvolutionMemoryRouter.retrieve()
5. SelfModel introspection   ← 能力检查 + 域分类
6. ContextAssembler         ← 上下文装配
7. CognitiveExecutive.execute()  ← V8 路径 (优先)
8. [回退] CognitiveOrchestratorV4.process()  ← V4 路径
9. 后处理: 缓存/记忆/语义缓存存储
```

**`async stream(request) -> AsyncIterator[dict]`** — 流式路径：
- 跳过 CognitiveExecutive，直接 V4 orchestrator 流式
- L0 缓存命中直接流式返回
- SSE delta 分块 (24 字符, 8ms 延迟)

---

## 7. V5 分层路由

V5 路由层是一个多级查询管道，逐步升级处理能力。目标：30%+ 请求免 LLM。

```
Query → L0 (RuleRouter, 零 LLM) → L0.5 (SemanticCache) → L1 (ComplexityEngine + TinyRouter) → V4 全管线
```

### 7.1 L0 规则路由器 (`query_router_v2.py`)

**核心类**：`L0RuleRouter`

纯正则/规则匹配，零 LLM，亚毫秒级延迟。5 类规则按优先级：

| 优先级 | 规则 | 处理 |
|--------|------|------|
| 1 | 斜杠命令 (`/rag`, `/data`, `/web`, `/tool`, `/vision`, `/anomaly`, `/rule`) | 去掉前缀，设置 force_mode |
| 2 | 身份查询 ("你是谁") | 返回 identity 标记 (可 LLM 增强) |
| 3 | 问候语 ("你好", "hi") | 返回预设 FAQ |

**结果**：`L0RouteResult(hit, answer, route, force_mode, metadata)`
- `hit=True` → 短路，不进入后续管道
- `hit=False` → 继续

### 7.2 语义缓存 (`semantic_cache.py`)

**核心类**：`SemanticCache`

- `lookup(query, ctx_hash)` → 计算嵌入向量 → 余弦相似度匹配 → ≥0.92 返回缓存
- `store(query, content, ctx_hash)` → 嵌入 → 存储 → LRU 淘汰 → TTL 淘汰
- 默认：10000 条, 3600 秒 TTL
- 降级方案：`_FallbackEmbedder` SHA256 哈希转伪嵌入

### 7.3 复杂度引擎 (`complexity_engine.py`)

**核心类**：`ComplexityEngine`

纯启发式（无 LLM），4 维度评分：

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| 长度 | 35% | 字符数/500, 上限 1.0 |
| 实体数 | 25% | 英文专有名词 + 中文二元组 + 数字, 每个 +0.1 |
| 分句数 | 20% | 逗号/句号/分隔符, 每个 +0.15 |
| 推理关键词 | bonus | "分析"/"compare"/"趋势", 每个 +0.2 |

评分阈值：<0.3 → L0, <0.6 → L1, ≥0.6 → V4

### 7.4 L1 Tiny Router (`tiny_router.py`)

**核心类**：`TinyRouter`

- 分类：`LLMRole.ROUTER` (qwen3-1.7b) → "simple"|"knowledge"|"complex"
- 简单回答：`LLMRole.FAST` (qwen3-8b) → ≤100 字中文回答
- 快捷路径：身份查询强制为 "complex"，短问候语 (<20字) 直接预设回答

### 7.5 上下文装配器 (`context_assembler.py`)

**核心类**：`ContextAssembler`

纯装配，无 LLM。将多轮历史/记忆/附件/对话状态装配成结构化上下文块（Markdown 格式），含 Token 预算控制和压缩标记。

**Token 预算**：history 4096, attachments 2048, memory 1024（均可配置）

---

## 8. V4 编排器 (`kernel/orchestrator_v4.py`)

系统的主力编排引擎，实现完整管线：Plan → Dispatch → Fusion → Critic → ClarificationGate。

### 8.1 核心类 `CognitiveOrchestratorV4`

**完整管线** (`process()`, ~1500 行)：

```
1. PII masking (NERMasker.mask_input)
2. XAI 追踪开始
3. Identity 查询快路径 → _handle_identity_query()
4. TaskModel + WorldModel 实体接地
5. 自适应 profile 选择 (speed/quality/balanced)
6. [Phase 2] UnifiedOrchestrator/CognitiveExecutive (可选)
7. DialogueStateTracker 追踪
8. ReferenceResolver 指代消解
9. 多问题检测 → SequenceFusionEngine
10. 纠正路径 (RefinePlanner)
11. Plan 生成
    a. force_mode → 直接映射 agent type
    b. correction_plan → 增量重规划
    c. PlanAgent.generate_plan() → LLM 完整规划
12. hard-guard 子任务注入 (文档/数据意图缺失时自动补)
13. Agent dispatch (Dispatcher, DAG 依赖调度)
14. RAG 质量重规划 (低质量时 QueryRewriter 重写 + 重分发)
15. ToolResult 构造 (source tagging: sql/web_search/document/tool/memory/attachment)
16. Fusion → FusionEngine.run()
17. 答案生成 (多条路径: RAG/Data/Web/Tool/Attachment)
18. ContentAnnotator + OutputValidator 验证
19. Critic → CriticEngine.run() (不合格则用 improved_answer)
20. ClarificationGate (confidence<0.4 → 澄清, 中等 → 建议)
21. 工具卡片注入 (天气/时间 JSON)
22. StatePatch 构建 → ConversationState 持久化
23. 运行时指标发布
```

### 8.2 核心组件

- **PlanAgent**：LLM 驱动的任务规划，支持单/多问题，DST/clarify 上下文注入
- **Dispatcher**：并发任务分发 + DAG 依赖调度。`asyncio.Semaphore` 并发控制
- **FusionEngine**：多源证据加权融合（attachment/web/memory 权重）
- **SequenceFusionEngine**：多子问题顺序融合
- **CriticEngine**：4 维分解评分（factuality/completeness/coherence/grounding）+ 多候选选择
- **ClarificationGate**：模糊查询检测 → 反问生成

---

## 9. Cognitive Runtime V2 (`kernel/runtime/`)

下一代统一编排管线。核心原则：RuntimeContext 贯穿全部阶段, 各模块不直接相互导入。

### 9.1 10 阶段认知管线

```
RuntimeContext (全量上下文)
  → Phase 1:  RewriteEngine.rewrite()          ← 查询规范化
  → Phase 2:  UnderstandingEngine.understand()  ← 深度理解 (目标/隐藏目标/实体/约束/歧义/风险/预期输出/所需能力/执行策略/完成标准)
  → Phase 3:  PolicyEngine.evaluate()           ← 安全策略
  → Phase 3.5: ContextCompressor                ← 上下文压缩
  → Phase 4:  CognitivePlannerV2.plan()         ← 1 次 LLM → CognitivePlan
              → StrategyBuilder.build()         ← 策略构建
              → ExecutionProjection             ← 执行投影 → ExecutionPlan + ExecutionGraph
  → Phase 4.5: ConstraintLayer.evaluate()       ← 确定性守卫 (deny/simplify/modify)
  → Phase 5-6: ExecutionRuntime.execute()       ← DAG 并行执行 → list[AgentResult]
  → Phase 7:  EvidenceBus                       ← 证据收集 + 生命周期 + 冲突消解
  → Phase 8:  FusionEngineV2.fuse()             ← LLM 证据融合
  → Phase 9:  CriticEngineV2.evaluate()         ← 质量审校
  → Phase 9.5: Capability Feedback Loop         ← 记录 + 分析 + 调整权重
  → Phase 10: ArtifactComposer.compose()        ← 最终产物
  → MemoryFabric + TruthMaintenanceSystem       ← 持久化
```

### 9.2 RuntimeContext (`context.py`)

20+ 字段组的统一 dataclass，是整个管线唯一的数据载体：

| 组 | 字段 | 来源 |
|----|------|------|
| 请求标识 | request_id, session_id, user_id, query | 原始请求 |
| 多轮 | conversation_history, conversation_state | Message/TraceLog |
| 记忆 | memory_context, episodic_events | EvolutionMemoryRouter |
| 用户 | user_preferences, user_style_hints, preference_context_block | 用户画像 |
| 数据源 | data_source_context, available_data_sources | DataSource |
| 附件 | attachment_contexts | Attachment |
| 快捷键 | force_mode, web_enabled, graph_controls | 请求参数 |
| 分支 | is_branch_request, branch_checkpoint, parent_message_id | 分支控制 |
| 安全 | risk_assessment, tool_permission_token | 零信任 |

### 9.3 核心对象模型 (`objects.py`)

- **Evidence**：主要信息货币。含 evidence_id, content, content_type, provenance (source/source_type/confidence), credibility_score, relevance_score, citations, state (created→validated→ranked→merged→archived), version, superseded_by, lineage
- **Provenance**：来源追踪 (source agent, source_type, confidence, timestamp, trace_id)
- **ExecutionPlan**：plan_id, rewritten_query, intent_category, subtasks (list[ExecutionTask]), merge_strategy, risk_level, completion_criteria
- **ExecutionTask**：task_id, capability_type (如 "data.query" / "web.search"), query, depends_on, priority, reason, expected_evidence_type
- **UnderstandingResult**：explicit_goal, hidden_goal, entities, constraints, ambiguity, risk_level, expected_output_type, required_capabilities, execution_strategy, completion_criteria, domain

### 9.4 UnifiedOrchestrator (`orchestrator.py`)

**一次 LLM 调用 (QUERY role) → 完整 TaskPlan**。替代 PlanAgent + DST + ReferenceResolver + hard-guard 逻辑。

- `plan(query, ctx)` → 如果 force_mode → 直接映射 (FORCE_MODE_AGENT_MAP, 10 种模式)。否则 → 一次 LLM 调用 (temp=0, max_tokens=800)
- 用户 prompt 组装：问题 + 最近 6 轮历史 + 记忆上下文 (1500 字) + 偏好 (1000 字) + 数据源绑定 (2000 字) + 附件摘要 + 对话状态 + 启用的技能
- 解析失败 → 回退 RAG-only 计划

### 9.5 CognitiveExecutive (`cognitive_executive.py`)

**所有请求的统一入口**。`execute(query, ctx, event_cb)` 串联全部 10+ 阶段管线：

```python
CognitiveExecutiveResult(
    answer,           # 最终回答
    evidence_objects, # 所有证据对象
    artifact,         # 产物
    plan,             # 执行计划
    fusion_result,    # 融合结果
    critic_result,    # 审校结果
    rewrite_trace,    # 改写追踪
    understanding,    # 理解结果
    risk_level,       # 风险等级
    policy_denied,    # 是否被策略拒绝
    execution_reasoning, # 执行推理链
)
```

所有引擎懒加载初始化 (`_ensure_*` 方法)。

### 9.6 EvidenceBus (`evidence_bus.py`)

进程内 pub/sub 总线：

- `publish_results(agent_results)` → AgentResult 转为 Evidence，注册生命周期
- `collect()` → 非破坏读取所有 evidence
- `rank_evidence(query)` → 按 relevance + credibility + freshness 排序
- `resolve(query)` → 完整消解：排序 + 冲突检测
- `get_usable()` → 过滤出可用于融合的 evidence
- `archive_turn()` → 归档当前轮所有 evidence
- 模块级单例: `evidence_bus`

### 9.7 FusionEngineV2 (`fusion.py`)

LLM 驱动的语义证据融合：

- 空 evidence → 空结果
- 全部失败 → 错误聚合
- 有矛盾 + LLM 启用 → `_llm_fuse()` (QUERY role, temp=0.1, max_tokens=1200)
- 否则 → `_heuristic_fuse()` (按 credibility_score 排序拼接)
- LLM 融合规则：去重、矛盾检测、置信度表达、不编造
- `kernel_fusion_v2_enabled` 控制 (默认 False)

### 9.8 CriticEngineV2 (`critic.py`)

结构化质量评估 (LLMRole.CHEAP_CRITIC)：

- `evaluate(query, answer, evidence_count, adaptive_profile)` → CriticResult (factuality, completeness, evidence_coverage, hallucination_risk)
- LLM 路径 (quality profile + flag enabled) → CHEAP_CRITIC (temp=0, max_tokens=300)
- 启发式路径 → 规则评分
- 通过阈值: factuality ≥ 0.6 AND completeness ≥ 0.3
- Flag: `kernel_critic_v2_enabled` (默认 False)

### 9.9 其他 Runtime 模块

- **RewriteEngine**：查询规范化 (纠错/术语标准化/指代消解)
- **UnderstandingEngine**：深度认知理解 (显式目标/隐藏目标/实体/约束/歧义/风险)
- **CapabilityRegistry**：统一能力注册 (agents + tools + skills + plugins)，BM25 风格 CJK 匹配
- **ConstraintLayer**：确定性守卫层 (deny/simplify/modify plan)
- **ArtifactComposer**：产物组合 (将 Fusion/Critic 结果组合为最终答案)
- **WorkspaceManager**：工作区管理 (核心记忆 128KB + 最近 artifact 跟踪)
- **MemoryFabric + TruthMaintenanceSystem**：置信度衰减 + 矛盾检测 + 事实淘汰
- **Event Sourcing**：RuntimeEventStore + PromptSnapshot + RuntimeSnapshot + ExecutionReplay

---

## 10. Agent 集群

### 10.1 BaseAgent (`agents/base.py`)

抽象基类。每个 Agent 实现 `execute(task: TaskMessage) -> AgentResult`。

**新能力执行器契约**：`execute_as_capability(task) -> list[Evidence]`，绕过 AgentResult 直接产出 Evidence。

### 10.2 注册体系

- `AgentRegistry` → 兼容旧 API 的薄包装，转发到 `CapabilityRegistry`
- `CapabilityRegistry` (kernel/runtime/capability.py) → 统一注册 agents + tools + skills + plugins

### 10.3 AgentWorker (`agents/worker.py`)

**Redis 消费者**。`run_forever()` 启动心跳 + 每个 agent type 一个消费协程：

- **stream 模式**：Redis Streams + consumer group + XREADGROUP + XACK + XPENDING/XCLAIM 消息回收
- **pubsub 模式**：Redis Pub/Sub 频道
- 重试：max 2 次，失败进 DLQ (Redis Stream, maxlen=20000)
- 心跳：每 10s 写入 `{namespace}:worker:heartbeat` (60s TTL)

### 10.4 Agent 清单

| Agent | agent_type | LLM Role | 功能 |
|-------|-----------|----------|------|
| DataAgent | data | PLANNING (via sub-agents) | Text2SQL，V1/V2 wrapper，V2 失败回退 V1 |
| RagAgent | rag | (via reranker) | 多源检索：文档向量 + LLMWiki + UserMemory + 神经重排序 + 证据门控 |
| WebAgent | web | — | Serper API 联网搜索 |
| ToolAgent | tool | — | 时间/天气/计算器/通用工具 |
| RuleEngineAgent | rules | CHEAP_CRITIC | 5 类规则匹配 + LLM 解释 |
| VisionAgent | vision | VISION | qwen3.6-vl-plus 多模态分析 |
| SkillsAgent | skills | — | 技能执行 (10s timeout) |

### 10.5 RagAgent 细节

最复杂的 Agent。查询处理管线：
1. `_normalize_query()` — 去掉中文前缀
2. `_rewrite_query()` — 去语气词/规范化
3. `_classify_query_type()` — 6 类 (definition/fact/procedure/comparison/memory/general) + 策略提示
4. `_expand_query_terms()` — 100+ 中文同义词扩展

检索源：
- 文档向量搜索 (并行多查询, capped at 3)
- LLMWiki 搜索
- UserMemory 数据库回退

后处理：
- 神经重排序 (qwen3-vl-rerank, 40% 原始分 + 60% reranker 分)
- 证据质量门控 (min_score + min_gap)
- Fallback 检索

---

## 11. Model Gateway (`model/`)

### 11.1 9 角色 LLMRole

| Role | 默认模型 | 用途 |
|------|---------|------|
| QUERY | qwen3.7-max | 主力推理与答案生成 |
| COMPRESS | qwen3.6-plus | 上下文压缩与记忆总结 |
| PLANNING | qwen3.6-plus | 任务分解与意图识别 |
| ROUTER | qwen3-1.7b | L1 轻量意图分类 (最小) |
| FAST | qwen3-8b | 简单/FAQ 直接回答 |
| CHEAP_CRITIC | qwen3.6-plus | 轻量输出审校 |
| KNOWLEDGE | qwen3.6-plus | 知识问答 |
| IDENTITY | qwen3-0.6b | 个性化身份回答 (temp=0.7, max_tokens=256, timeout=8s) |
| VISION | qwen3.6-vl-plus | 多模态图像/图表分析 (temp=0.3, max_tokens=2048, timeout=60s) |

### 11.2 ModelGateway

`get_model_gateway()` 模块级单例：

- **每角色独立 adapter**：`OpenAICompatibleAdapter` 缓存
- **每角色独立熔断器**：failure_threshold=3, recovery_timeout=30s
- **回退链**：`complete(messages, role, fallback_roles)` → 按序尝试，跳过 OPEN 的熔断器
- **重试策略**：auth/model_not_found 不重试；rate_limit (1.5s backoff)；timeout/connectivity (0.6s backoff)；最多 3 次
- **离线降级**：所有角色失败 → `_offline_fallback_response()` 手工中文回复
- **身份强制**：`merge_system_identity()` 注入系统身份；`enforce_identity_output()` 后处理

### 11.3 OpenAICompatibleAdapter (唯一适配器)

- `AsyncOpenAI` + `httpx.AsyncClient` (连接池: 10 keepalive, 50 总量)
- 代理回退：先 with proxy → 失败 without proxy
- Qwen3 thinking suppression: `enable_thinking: False`
- 多模态: list content 直接透传
- 指标: LLM_CALLS_TOTAL (按 provider/model/status), LLM_LATENCY

### 11.4 Embedding & Reranker

**Embedding 工厂** (`get_embedder()`)：
- `dashscope` → DashScopeEmbedder (多层 fallback)
- `api` / `openai` → APIEmbedder
- `local` → LocalEmbedder (BAAI/bge-m3)
- fallback → HashEmbedder (确定性 hash)

**Reranker 工厂** (`get_reranker()`)：
- `dashscope` → DashScopeReranker (qwen3-vl-rerank)
- `api` / `openai` → APIReranker
- fallback → HeuristicReranker (BM25, k1=1.5, b=0.75)

---

## 12. Memory System

### 12.1 记忆层级

| 层 | 模块 | 说明 |
|----|------|------|
| L1 工作记忆 | working_memory | deque 环形缓冲 (max 32 轮) + identity 缓存 + Redis 持久化 |
| L2 语义记忆 | semantic_memory | InMemorySemanticStore 向量检索 |
| L3 情节记忆 | episodic_memory | Redis 持久化事件序列, recall(last_n=20) |
| L4 程序记忆 | procedural_memory | 成功的流程/工具链 (待接入) |
| 路由 | memory_router → evolution/router | EvolutionMemoryRouter (9 特性) |
| 时序索引 | temporal_memory | TemporalMemoryIndex 指数衰减 |
| 治理 | evolution/governance | MemoryGovernance 信心衰减/矛盾检测/来源追踪 |

### 12.2 EvolutionMemoryRouter — 9 大特性

继承 `MemoryRouter`，叠加 9 层增强：

| # | 特性 | 说明 |
|---|------|------|
| ① | 写入强化 | store() 时 reinforce + provenance track + contradiction check |
| ② | Case 累积 | 每次写入推入 _pending_cases，≥20 条触发演化 |
| ③ | Case→Pattern→Skill | MemoryEvolution.evolve() → Redis 持久化 |
| ④ | 会话压缩 | compress_session() → LLM 压缩为摘要 |
| ⑤ | 技能检索 | skill_retrieve() → trigger_conditions 匹配 |
| ⑥ | 检索注入 | 技能按权重插入检索结果最前面 |
| ⑦ | 自动衰减 | 连续 N 轮无反馈 → score × 0.1 |
| ⑧ | 显式反馈 | like/dislike 写入 Redis，重置 streak |
| ⑨ | 治理集成 | store 时 provenance + contradiction；retrieve 时 confidence refresh |

### 12.3 MemoryGovernance

三大核心机制：

**① 信心衰减**：
- 公式：`current = score × 2^(-age / half_life)`，默认 7 天
- `refresh_confidence(boost=0.05)` — 访问时小幅提升
- `get_stale_chunks()` / `prune_stale()` — 清理信心 <0.15 的记忆

**② 矛盾检测**：
- 关键词反向对：增加/减少, 上升/下降, 增长/衰退, 盈利/亏损, 成功/失败, 启用/禁用
- 数值矛盾：同实体数值差异 >3× 倍 → +0.15
- 总矛盾分 >0.3 → 冲突 → 保留置信度高的

**③ 来源追踪 (Provenance)**：
- `MemoryProvenance(source_agent, session_id, turn_index, created_at, last_accessed_at, access_count, original_query)`
- 全程 try/except 保护，静默降级

### 12.4 TemporalMemoryIndex

时间感知记忆检索。指数衰减公式：`adjusted = base × 2^(-age / half_life)` (默认 7 天)。附加关键词重叠加分 (每词 +0.1)。

### 12.5 价值评分

三元加权：`final = 0.5×base + 0.3×recency + 0.2×feedback`

- recency: `exp(-0.01 × turn_gap)` (半衰期 ~70 轮)
- feedback: like=+0.3, dislike=-0.5, 无反馈=0
- 自动衰减: 连续 N 轮无反馈 → ×0.1

---

## 13. Data Agent V2 (`agents/data_agent_v2/`)

企业级认知数据智能体。三层架构：Knowledge → Reasoning → Learning。

### 13.1 Supervisor 管线 (11 步)

```
1. 初始化 CognitiveContext
2. 加载数据源元数据 (schema, tables, DSN)
3. Knowledge Layer: KnowledgeRetrieverAgent (5 类知识检索)
4. Fast path 检查: pattern_hit 或 compiled_sql 已存在 → 跳过 DAG
5. DAG 执行 (5 层依赖):
   Level 0 (并行): IntentAgent + EntityAgent + MetricAgent + TimeReasoningAgent + JoinAgent
   Level 1: SemanticAgent (depends on Intent + Entity)
   Level 2: PlannerAgent (depends on all L0/L1)
   Level 3: SQLCompilerAgent (depends on Planner)
   Level 4: VerificationAgent (depends on Compiler)
6. Clarification Gate: 模糊查询 → 澄清卡片
7. SQL 执行: SQLValidator → SQLExecutor
8. Reflection: 观察结果 → 诊断 → 修复 (最多 2 次)
9. Advanced Analytics: StatisticalAgent + InsightAgent + VisualizationAgent
10. Critic: DataCriticAdapter → 可解释置信度
11. Learning Pipeline: FeedbackCollector → PatternExtractor → KnowledgeUpdater
```

### 13.2 核心 Sub-Agent

- **KnowledgeRetrieverAgent**：检索 5 类知识 (metric_definitions, schema_metadata, table_relationships, analytical_skills, query_patterns)
- **IntentAgent**：12 种意图类型分类 + 结构化意图快速路径
- **EntityAgent**：实体识别 + 标准化 + 表映射
- **MetricAgent**：指标识别 + 公式提取
- **TimeReasoningAgent**：时间窗口解析 (绝对/相对/对比)
- **JoinAgent**：表连接路径推理
- **PlannerAgent**：分析型意图确定性规划 (bypass LLM) + LLM 通用规划
- **SQLCompilerAgent**：确定性 LogicalPlan → SQL 转换 (无 LLM)
- **VerificationAgent**：6 维 SQL 校验 (结构/语义/时间覆盖/指标覆盖/实体覆盖/业务指标接地)

### 13.3 知识资产表 (6 张)

| 表 | 关键字段 |
|----|---------|
| metric_definitions | name, aliases[], formula, underlying_columns[], agg_function, sensitivity, status |
| schema_metadata | table_name, column_name, business_name, semantic_type, is_primary_key, is_metric_column |
| table_relationships | left_table, right_table, join_type, cardinality, amplification_risk, success_rate |
| analytical_skills | skill_type, required_intent_types[], plan_template (JSON), sql_template |
| query_patterns | pattern_hash, intent_type, entities[], metrics[], successful_sql, success_count |
| metric_lineage | metric_id, depends_on_metric_id, transformation, lineage_type |

---

## 14. Capability Intelligence

运行时自认知层。从 "tool calling" 升级到 "capability cognition"。

### 14.1 Phase 1 模块

| 模块 | 文件 | 说明 |
|------|------|------|
| CapabilityProfile | profile.py | 富语义能力画像: strengths/weaknesses/ideal_queries/anti_patterns/reliability/latency |
| CapabilityProfiler | profiler.py (583 行) | 构建画像 + CJK 匹配 (二元组) + 复合评分 (5 维度) |
| CapabilityAdapter | adapter.py | 画像 → LLM prompt 格式化 (~50-80 tokens/entry) |
| CapabilityFeedbackLoop | feedback.py | deque(200) 执行记录 + profiler 增量更新 |

### 14.2 Phase 2 模块

| 模块 | 文件 | 说明 |
|------|------|------|
| CapabilityOntology | ontology.py | 13 种能力类型枚举 + 延迟/质量/资源 schema |
| CapabilityKnowledgeGraph | knowledge_graph.py (273 行) | 15 条种子关系 → BFS 路径查找 + 拓扑排序 + 替代路径 |
| CapabilityReasoner | reasoner.py (170 行) | 加权推荐 (profiler + KG 依赖惩罚 + execution_memory 退化惩罚) |
| ExecutionMemory | execution_memory.py (195 行) | 500 条 deque + 时间窗口统计 + 模式检测 + 退化检测 |
| StrategyMemory | strategy_memory.py (222 行) | 300 条 deque + 4 层匹配 (精确→部分→跨领域→fallback) |
| EvolutionEngine | evolution.py (252 行) | 每 10 轮分析: 退化/改进/模式验证 → adjust_weights (防重复 + 衰减) |
| FailureMemory | failure_memory.py (250 行) | 500 条 deque + 7 种失败类型 + should_avoid() 查询 |

### 14.3 集成点

- **CognitivePlannerV2._build_system_prompt()** → adapter.format_for_cognitive_planner()
- **StrategyBuilder._gap_to_capability()** → reasoner.recommend_capability()
- **StrategyBuilder._determine_execution_strategy()** → strategy_memory.recommend()
- **CognitiveExecutive Phase 9.5** → feedback_loop.record() + execution_memory.record() + evolution_engine.on_turn_complete()

---

## 15. Safety 安全层

### 15.1 NER PII 脱敏 (`safety/masking/ner_masker.py`)

- `NERMasker`：正则 9 种实体类型 (EMAIL, PHONE_CN, PHONE_INTL, CREDIT_CARD, ID_CN, IP_ADDRESS, PERSON_CN, LOCATION_CN, ORG_CN)
- 可逆脱敏：`{MASK_PERSON_CN_0}` 占位符 + mapping dict → `unmask_output()` 恢复
- 模块级单例: `get_ner_masker()`

### 15.2 安全守门 (`safety/guardrails/guardrails.py`)

- `Guardrails.check_input()`: 攻击/注入拦截 → PII 脱敏 → PolicyEngine 评估
- `Guardrails.check_output()`: 攻击模式脱敏 + PII 脱敏

### 15.3 安全策略引擎 (`safety/policy_engine/engine.py`)

- Redis 滑动窗口限流 (zset)
- 默认规则: 拒绝空查询, 匿名用户限速 (20 rpm), 审计敏感关键词 (delete/drop/truncate)
- PolicyAction: ALLOW/DENY/REDACT/AUDIT/RATE_LIMIT

### 15.4 XAI 认知追踪 (`safety/xai/cognitive_trace.py`)

- `CognitiveTracer`：记录完整决策链 (TraceEvent per decision point)
- 内存存储: OrderedDict, max 200 traces, 500 events/trace

---

## 16. Infrastructure 基础设施

### 16.1 配置 (`infra/config/settings.py`)

`pydantic-settings` 单例，10 个子 settings 类继承。配置优先级: env var > .env > 默认值。

### 16.2 数据库 (`infra/storage/`)

- AsyncPG + SQLAlchemy 2.0 async engine (连接池: 10 + 20 overslow)
- 30+ ORM 模型 (Core: User/ChatSession/Message/TraceLog/Attachment/ConversationState; Knowledge: Document/DocumentChunk/DocumentLLMWiki; Data V2: 6 张知识资产表; System: RedisShadowKV/ReasoningTrace/ToolStat/AuditLog/CognitiveEvent)
- Alembic 迁移 (idempotent, 20+ versions)

### 16.3 Redis (`infra/cache/redis_client.py`)

`ShadowRedis`：所有写入镜像到 PostgreSQL `redis_shadow_kv` 表 (shadow-write pattern)。6 个逻辑 DB 分库 (session=10, cache=11, memory=12, queue=13, rate_limit=14, pubsub=15)。

### 16.4 Agent Bus (`infra/message_bus/agent_bus.py`)

- `AgentMessageBus`：按 agent_type 分频道/流发布任务
- Stream 模式：consumer group + XACK + pending reclaim (XCLAIM)
- 结果 TTL 120s
- DLQ：失败任务 XADD 到 dlq_stream (maxlen=20000)
- 所有发布/结果 publish 到 `cognitive_event_bus`

### 16.5 可观测性 (`infra/observability/`)

- **Logger**：structlog 结构化 JSON + 请求上下文注入 + 敏感值脱敏
- **Tracer**：OpenTelemetry OTLP gRPC (no-op fallback)
- **Metrics**：Prometheus counters (HTTP_REQUESTS_TOTAL, LLM_CALLS_TOTAL, AGENT_TASKS_TOTAL, MEMORY_HITS, DAG_EXECUTIONS_TOTAL) + histograms
- **RequestContext**：ContextVar 跨 async 传播 request_id/trace_id/user_id/session_id

### 16.6 错误处理 (`infra/errors/`)

- `AppException(code, message, details, http_status)` → 从 ErrorSpec 解析
- `ValidationException(error_code=1003)`, `NotFoundException(3001)`, `DependencyException(904001)`, `TimeoutException(206001)`
- 20+ ErrorSpec (Global/Auth/Registration/Chat/Document/System)

### 16.7 零信任 (`infra/security/zero_trust.py`)

- `assess_query_risk(query)` → 匹配 HIGH 模式 (delete file/send email/transfer/drop table) 和 MEDIUM 模式 (run code/execute/sandbox)
- SHA-256 permission token → Redis 存储 (session-scoped)
- `ToolAnomalyDetector`: IsolationForest (30+ 样本后拟合)

---

## 17. Execution Plane

### 17.1 DAG Engine (`execution/dag_engine/`)

- **DAGGraph**：NetworkX DAG, 动态任务注入, acyclicity 校验
- **DAGEngine**：执行循环 (ready tasks → resource slots → concurrent execution → retries max 3, exp backoff max 30s → rollback hooks)
- **ResourceScheduler**：CPU=8, GPU=2, IO=16, 优先级排序
- **StateManager**：Redis checkpoint (24h TTL), 每 5 个完成节点存一次, 可恢复
- **EventBus**：进程内 pubsub, 6 种事件类型

### 17.2 Data Execution (`execution/data/`)

- **SQLExecutor**：async SQLAlchemy, JSON-safe 类型转换 (datetime/Decimal/bytes)
- **DBRouter**：多数据源 DSN 构建 (postgresql+asyncpg, mysql+asyncmy, clickhouse+asynch, doris+mysql+asyncmy)

### 17.3 Tool Router (`execution/tool_router/`)

- `ToolRouter.execute(intent)` → `registry.match(intent)` → `inspect.signature` 匹配 → 执行
- `execute_by_name(name)` → 绕过意图匹配

### 17.4 Sandbox (`execution/sandbox/`)

- 受限 Python 执行 (42 安全 builtins)
- `asyncio.wait_for` 10s timeout, thread executor
- 生产环境建议替换为 gVisor/Firecracker

---

## 18. Feature Flags 总览

所有 flags 定义在 `infra/config/settings.py`。以下为关键 flags 和默认值：

### 编排器

| Flag | 默认值 | 说明 |
|------|--------|------|
| kernel_orchestrator_version | "v4" | 编排器版本 |
| kernel_orchestrator_unified_enabled | True | Phase 2: UnifiedOrchestrator |
| kernel_v5_routing_enabled | True | V5 分层路由总开关 |
| kernel_l0_rule_router_enabled | True | L0 规则路由器 |
| kernel_l1_tiny_router_enabled | True | L1 小模型路由器 |
| kernel_semantic_cache_enabled | True | 语义缓存 |

### Cognitive Runtime V2

| Flag | 默认值 | 说明 |
|------|--------|------|
| kernel_cognitive_planner_v2_enabled | True | CognitivePlannerV2 (3 层规划) |
| kernel_runtime_rewrite_enabled | True | RewriteEngine |
| kernel_runtime_understanding_enabled | True | UnderstandingEngine |
| kernel_runtime_capability_graph_enabled | True | CapabilityGraphBuilder |
| kernel_runtime_evidence_fusion_critic_enabled | True | Evidence/Fusion/Critic 管线 |
| kernel_runtime_artifact_composer_enabled | True | ArtifactComposer |
| kernel_runtime_workspace_enabled | False | Workspace |
| kernel_runtime_replay_enabled | True | 快照 + 确定性回放 |
| kernel_fusion_v2_enabled | False | Fusion LLM 模式 |
| kernel_critic_v2_enabled | False | Critic LLM 模式 |
| kernel_evidence_lifecycle_enabled | True | Evidence 生命周期状态机 |
| kernel_context_compressor_enabled | True | 上下文压缩 |

### Agent

| Flag | 默认值 | 说明 |
|------|--------|------|
| kernel_agent_enabled | True | Agent 总开关 |
| kernel_agent_data_enabled | True | Data Agent |
| kernel_agent_rag_enabled | True | RAG Agent |
| kernel_agent_web_enabled | True | Web Agent |
| kernel_agent_tool_enabled | True | Tool Agent |
| kernel_agent_vision_enabled | False | Vision Agent |
| kernel_agent_bus_enabled | False | Agent Bus (分布式) |
| kernel_agent_dag_scheduling_enabled | False | Agent DAG 调度 |
| data_agent_v2_enabled | True | Data Agent V2 |

### Capability Intelligence

| Flag | 默认值 | 说明 |
|------|--------|------|
| kernel_capability_intelligence_enabled | False | Phase 1 主开关 |
| kernel_capability_intelligence_phase2_enabled | False | Phase 2 主开关 |
| kernel_capability_knowledge_graph_enabled | True | Phase 2 子开关: KG |
| kernel_capability_reasoner_enabled | True | Phase 2 子开关: Reasoner |
| kernel_capability_execution_memory_enabled | True | Phase 2 子开关: ExecutionMemory |
| kernel_capability_strategy_memory_enabled | True | Phase 2 子开关: StrategyMemory |
| kernel_capability_evolution_enabled | True | Phase 2 子开关: EvolutionEngine |

### 对话与记忆

| Flag | 默认值 | 说明 |
|------|--------|------|
| kernel_memory_context_enabled | True | 记忆上下文注入 |
| kernel_conversation_state_enabled | True | 结构化对话状态 |
| kernel_clarification_gate_enabled | True | 澄清追问 |
| kernel_correction_detection_enabled | True | 纠正检测 |
| kernel_refine_replan_enabled | True | 增量重规划 |
| kernel_dst_enabled | True | 对话状态追踪 |
| kernel_context_composer_enabled | True | 上下文压缩 |
| kernel_memory_value_scoring_enabled | True | 记忆价值评分 |
| kernel_conversation_branching_enabled | True | 对话分支 |
| kernel_adaptive_mode_enabled | True | 自适应模式 |
| kernel_revise_loop_enabled | True | Critic 自我修正 |
| kernel_user_profiling_enabled | True | 用户画像 |
| kernel_identity_llm_enabled | True | 身份 LLM 动态生成 |
| kernel_memory_truth_maintenance_enabled | True | Memory TMS |

### 安全

| Flag | 默认值 | 说明 |
|------|--------|------|
| kernel_ner_masking_enabled | True | NER PII 脱敏 |
| kernel_canary_auto_rollback_enabled | True | 金丝雀自动回滚 |

---

## 19. 配置说明

### 配置优先级

env var > `.env` > `infra/config/settings.py` 默认值

### 关键 LLM 配置

```
DEFAULT_LLM_QUERY_PROVIDER=dashscope
DEFAULT_LLM_QUERY_MODEL=qwen3.7-max
DEFAULT_LLM_QUERY_BASE_URL=...
DEFAULT_LLM_QUERY_API_KEY=...

DEFAULT_LLM_PLANING_PROVIDER=dashscope
DEFAULT_LLM_PLANING_MODEL=qwen3.6-plus
...

# 其他 7 个角色: COMPRESS, JUNIORSHORT, MIDDLESHORT, SENIORSHORT, MINSHORT, VISION
```

### LLM 角色分组

| 设置前缀 | 对应 LLMRole | 默认模型 |
|---------|-------------|---------|
| default_llm_query_* | QUERY | qwen3.7-max |
| default_llm_compress_* | COMPRESS | qwen3.6-plus |
| default_llm_planning_* | PLANNING | qwen3.6-plus |
| default_llm_juniorshort_* | ROUTER | qwen3-1.7b |
| default_llm_middleshort_* | FAST | qwen3-8b |
| default_llm_seniorshort_* | CHEAP_CRITIC/KNOWLEDGE | qwen3.6-plus |
| default_llm_minshort_* | IDENTITY | qwen3-0.6b |
| default_llm_vision_* | VISION | qwen3.6-vl-plus |

### Embedding & Rerank 配置

```
EMBEDDING_PROVIDER=dashscope  # dashscope|api|openai|local|hash
EMBEDDING_DIMS=1024
EMBEDDING_BASE_URL=...
RERANK_PROVIDER=dashscope     # dashscope|api|openai|heuristic
```

### Redis 分库

| DB # | 用途 | 环境变量后缀 |
|------|------|------------|
| 10 | Session | redis_session_db |
| 11 | Cache | redis_cache_db |
| 12 | Memory | redis_memory_db |
| 13 | Queue | redis_queue_db |
| 14 | Rate Limit | redis_rate_limit_db |
| 15 | PubSub | redis_pubsub_db |

---

## 20. Docker 部署

### 服务列表 (`docker-compose.yml`)

| 服务 | 端口 | 说明 |
|------|------|------|
| postgres | 5432 | PostgreSQL + pgvector |
| redis | 6380 (host), 6379 (container) | Redis 6 DB |
| api | 14100 | FastAPI Gateway |
| agent-worker | — | Agent 消费者 (Redis Bus) |
| prometheus | 9090 | 指标采集 |
| jaeger | 16686 | 分布式追踪 |

### 常用命令

```bash
bash start.sh              # 启动所有服务
bash restart.sh            # 强制重启 (推荐)
bash stop.sh               # 停止
bash stop.sh --volumes     # 完全重置 (含数据库)
bash scripts/docker_logs.sh api       # API 日志
bash scripts/docker_logs.sh agent-worker  # Worker 日志

# 强制完整重建 (源码不生效时)
docker compose build --no-cache api agent-worker && bash restart.sh
```

### 代码部署注意

Dockerfile 使用 `COPY . .` (非 volume mount)，源码在构建时 baked into image。Docker layer cache 可能跳过 COPY 步骤，需要 `--no-cache` 强制重建。

---

## 21. 测试体系

### 测试命令

```bash
pytest                                          # 运行所有测试
pytest tests/path/to/test.py::test_function     # 运行单个测试
pytest -v -k "pattern"                          # 按名称模式运行
```

### 关键测试模块 (~90 个文件)

**编排与路由**:
- `test_orchestrator_v4_contract.py` — V4 编排
- `test_v5_routing_contract.py` (481 行) — V5 路由
- `test_force_mode_routing.py` (636 行) — force_mode 路由

**Cognitive Runtime**:
- `test_cognitive_runtime_contract.py` (793 行) — Runtime V2 管线
- `test_runtime_cognitive_executive.py` (424 行) — CognitiveExecutive

**Capability Intelligence**:
- `test_capability_intelligence.py` (1965 行) — 全量测试 (146 tests)

**Data Agent V2**:
- `test_data_agent_v2_agent_contract.py` (500 行)
- `test_data_agent_v2_supervisor_contract.py` (208 行)
- `test_data_agent_v2_deterministic_agents_unit.py` (276 行)

**Agent**:
- `test_agent_bus_e2e_contract.py` — Agent Bus 端到端
- `test_agent_stubs_contract.py` (86 行)
- `test_rag_agent_contract.py` — RAG agent

**Memory**:
- `test_memory_evolve.py` (11 行)
- `test_memory_api_contract.py`

**其他重要测试**:
- `test_clarification_gate.py` (171 行)
- `test_clarification_supervisor_integration.py` (179 行)
- `test_entity_filter_regression.py` (423 行)
- `test_data_cognition_pipeline.py` (421 行)
- `test_text2sql_regression.py` (229 行)
- `test_semantic_layer.py` (84 行)

---

## 22. 开发规范

### 代码质量

```bash
black .           # 代码格式化
ruff check .       # Lint
mypy .             # 类型检查
pre-commit install # 安装 pre-commit hooks
```

### 架构原则

1. **唯一中枢**：禁止绕过 CognitiveKernel 直接调用 LLM
2. **候选材料**：所有 Plugin/Agent 返回的数据只是「候选认知材料」
3. **LLM 是执行器**：LLM 负责理解、编排、融合、生成
4. **懒加载优先**：V5/V6/V7/V8 模块使用懒加载单例，不增加冷启动开销
5. **向后兼容**：所有新字段提供默认值，双写双读并行
6. **Runtime First > Agent First**：运行时拥有决策权，Agent 只是能力执行器

### 修改 .env 后需重启服务

### 默认开发账号

`songts@tuwan.com` / `123456`

---

> 文档版本：SERVICE_NEW.md
> 从零开始基于实际代码重新梳理生成，代表当前项目状态 (2026-05-26) 的准确参考。
