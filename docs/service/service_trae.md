# OpenTrace 完整项目文档

> 本文档是 OpenTrace 项目的唯一权威技术参考，涵盖架构设计、API 接口、配置说明、数据流程、部署方案和开发指南。所有内容均从源码直接分析得出。
> 最后更新：2026-06-15

## 目录 (120+ chapters)

1. [项目概述](#1-项目概述)
2. [技术栈](#2-技术栈)
3. [系统架构](#3-系统架构)
4. [目录结构](#4-目录结构)
5. [前端应用](#5-前端应用)
6. [API 网关](#6-api-网关)
7. [认知内核（Cognitive Kernel）](#7-认知内核cognitive-kernel)
8. [V5 分层路由](#8-v5-分层路由)
9. [L0 规则路由器](#9-l0-规则路由器)
10. [V4 编排器](#10-v4-编排器)
11. [CognitiveExecutive V2 认知执行器](#11-cognitiveexecutive-v2-认知执行器)
12. [CognitivePlanner 与 UnifiedOrchestrator](#12-cognitiveplanner-与-unifiedorchestrator)
13. [约束层（Constraint Layer）](#13-约束层constraint-layer)
14. [执行推理追踪（Execution Reasoning）](#14-执行推理追踪execution-reasoning)
15. [智能体集群](#15-智能体集群)
16. [DataAgent V2 认知管线](#16-dataagent-v2-认知管线)
17. [模型网关](#17-模型网关)
18. [记忆系统](#18-记忆系统)
19. [真值维护系统（TMS）](#19-真值维护系统tms)
20. [记忆进化与治理](#20-记忆进化与治理)
21. [执行平面](#21-执行平面)
22. [数据认知层](#22-数据认知层)
23. [能力智能层](#23-能力智能层)
24. [证据生命周期管理](#24-证据生命周期管理)
25. [策略引擎](#25-策略引擎)
26. [推理引擎](#26-推理引擎)
27. [世界模型](#27-世界模型)
28. [融合引擎](#28-融合引擎)
29. [审校引擎](#29-审校引擎)
30. [认识论层](#30-认识论层)
31. [元认知](#31-元认知)
32. [系统身份](#32-系统身份)
33. [认知协议](#33-认知协议)
34. [安全与防护](#34-安全与防护)
35. [沙箱运行时](#35-沙箱运行时)
36. [Agent Runtime 多智能体流水线](#36-agent-runtime-多智能体流水线)
37. [演化与学习系统](#37-演化与学习系统)
38. [确定性重放与审计](#38-确定性重放与审计)
39. [插件系统](#39-插件系统)
40. [技能系统](#40-技能系统)
41. [规则引擎](#41-规则引擎)
42. [治理中心](#42-治理中心)
43. [基础设施层](#43-基础设施层)
44. [API SDK](#44-api-sdk)
45. [连接器](#45-连接器)
46. [上下文系统](#46-上下文系统)
47. [对话状态管理](#47-对话状态管理)
48. [澄清门控](#48-澄清门控)
49. [自适应配置与偏好层级](#49-自适应配置与偏好层级)
50. [Web 搜索引擎](#50-web-搜索引擎)
51. [内置工具系统](#51-内置工具系统)
52. [PlanAgent 与 PlanMemory](#52-planagent-与-planmemory)
53. [RefinePlanner 有界局部重规划](#53-refineplanner-有界局部重规划)
54. [上下文运行时（Context Runtime）](#54-上下文运行时context-runtime)
55. [证据生命周期详细管理](#55-证据生命周期详细管理)
56. [Prompt 引擎](#56-prompt-引擎)
57. [意图引擎](#57-意图引擎)
58. [序列融合引擎](#58-序列融合引擎)
59. [Dispatcher 与 Runtime Supervisor](#59-dispatcher-与-runtime-supervisor)
60. [Token 计数与历史检索](#60-token-计数与历史检索)
61. [DAG 计划与调度](#61-dag-计划与调度)
62. [服务层与文件解析](#62-服务层与文件解析)
63. [嵌入模型与向量检索](#63-嵌入模型与向量检索)
64. [重排序模型](#64-重排序模型)
65. [LLM 适配器](#65-llm-适配器)
66. [ShadowRedis 双写缓存](#66-shadowredis-双写缓存)
67. [消息总线详细架构](#67-消息总线详细架构)
68. [可观测性体系](#68-可观测性体系)
69. [数据库访问与 ORM 模型](#69-数据库访问与-orm-模型)
70. [零信任安全详细架构](#70-零信任安全详细架构)
71. [DataAgent V1 管线](#71-dataagent-v1-管线)
72. [RAGAgent 详细架构](#72-ragagent-详细架构)
73. [DataAgent V2 错误分类与修复](#73-dataagent-v2-错误分类与修复)
74. [DataAgent V2 知识层与学习闭环](#74-dataagent-v2-知识层与学习闭环)
75. [DataAgent V2 高级分析](#75-dataagent-v2-高级分析)
76. [目标生命周期系统（Goal Lifecycle）](#76-目标生命周期系统goal-lifecycle)
77. [治理中心详细架构](#77-治理中心详细架构)
78. [认知监督器（Cognitive Supervisor）](#78-认知监督器cognitive-supervisor)
79. [运行时网关（Runtime Gateway）](#79-运行时网关runtime-gateway)
80. [确定性认知控制（Cognitive Controls）](#80-确定性认知控制cognitive-controls)
81. [能力链与能力运行时元数据](#81-能力链与能力运行时元数据)
82. [认知运行时状态（Cognitive Runtime State）](#82-认知运行时状态cognitive-runtime-state)
83. [多问题运行时 V2（Multi-Question Runtime V2）](#83-多问题运行时-v2multi-question-runtime-v2)
84. [上下文织物（Context Fabric）](#84-上下文织物context-fabric)
85. [记忆织物关系引擎（Memory Fabric）](#85-记忆织物关系引擎memory-fabric)
86. [能力治理（Capability Governance）](#86-能力治理capability-governance)
87. [结果引用系统（Result Reference）](#87-结果引用系统result-reference)
88. [企业多租户系统（Enterprise Tenant）](#88-企业多租户系统enterprise-tenant)
89. [企业控制平面（Enterprise Control Plane）](#89-企业控制平面enterprise-control-plane)
90. [合规运行时（Compliance Runtime）](#90-合规运行时compliance-runtime)
91. [用量计量与成本归因（Usage Metering & Cost Attribution）](#91-用量计量与成本归因usage-metering--cost-attribution)
92. [能力产品化与生命周期（CapabilityOS）](#92-能力产品化与生命周期capabilityos)
93. [工作流引擎（Workflow Engine）](#93-工作流引擎workflow-engine)
94. [认知迭代与反思重规划](#94-认知迭代与反思重规划)
95. [自优化运行时（Self-Optimizing Runtime）](#95-自优化运行时self-optimizing-runtime)
96. [运行时阶段与分派](#96-运行时阶段与分派)
97. [能力注册表详细架构](#97-能力注册表详细架构)
98. [证据总线详细架构](#98-证据总线详细架构)
99. [错误码与异常体系](#99-错误码与异常体系)
100. [配置与特性开关完整表](#100-配置与特性开关完整表)
101. [认知事件总线](#101-认知事件总线)
102. [Feature Flag Governance](#102-feature-flag-governance)
103. [语义缓存](#103-语义缓存)
104. [NER PII Masker](#104-ner-pii-masker)
105. [Safety Guardrails](#105-safety-guardrails)
106. [Safety Policy Engine](#106-safety-policy-engine)
107. [Cognitive Trace](#107-cognitive-trace)
108. [Sandbox Providers](#108-sandbox-providers)
109. [Connector Protocol](#109-connector-protocol)
110. [Data Flywheel](#110-data-flywheel)
111. [Evaluation Engine](#111-evaluation-engine)
112. [Learning Engine](#112-learning-engine)
113. [Meta-Learner](#113-meta-learner)
114. [Self-Play](#114-self-play)
115. [Capability Profiler 5D Scoring](#115-capability-profiler-5d-scoring)
116. [Capability Knowledge Graph](#116-capability-knowledge-graph)
117. [Capability Reasoner](#117-capability-reasoner)
118. [Execution/Strategy/Failure Memory](#118-executionstrategyfailure-memory)
119. [Runtime Contract](#119-runtime-contract)
120. [Capability Execution Contract](#120-capability-execution-contract)
121. [Capability Lifecycle](#121-capability-lifecycle)
122. [Adaptive Risk Engine](#122-adaptive-risk-engine)
123. [Confidence Decay](#123-confidence-decay)
124. [Fact Supersession](#124-fact-supersession)

---

## 1. 项目概述

OpenTrace 是一个基于认知内核（Cognitive Kernel）构建的企业级 AI 系统，采用多智能体架构，支持对话问答、文档检索、数据查询分析、联网搜索、工具调用等能力。系统核心设计理念是**认知运行时管线**——所有请求经过统一的认知执行流水线，从查询改写、深度理解、认知规划、约束检查、执行、证据收集、融合、批评到制品合成，每一步都有确定性护栏和治理机制。

### 核心设计原则

1. **Planning First**：一次规划到位，不做运行时试探
2. **Evidence First**：任务输出是 Evidence，不是原始文本
3. **Capability First**：按 capability_type 分配（如 `data.query`、`web.search`）
4. **Runtime First**：执行器只负责执行，不允许自主 fallback
5. **确定性护栏**：约束层不调用 LLM，纯规则 + 查表

### 认知管线完整流程

```
用户查询 → IntentLock → Rewrite → Understand → Policy → Plan(V2)
→ ConstraintLayer → Execute → EvidenceBus → Rank → Resolve
→ Fuse(V2) → Critic(V2) → Artifact → Workspace → Memory → Archive
```

---

## 2. 技术栈

### 后端
| 层次 | 技术 |
|------|------|
| Web 框架 | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| 数据库 | PostgreSQL (asyncpg) + pgvector |
| 缓存 | Redis (多 DB 分区) |
| LLM | 阿里巴巴 Qwen 系列 (DashScope API) |
| 嵌入模型 | text-embedding-v3 (1024 维) |
| 重排序 | BAAI/bge-reranker-v2-m3 / 启发式 |
| 向量检索 | pgvector |
| 认证 | JWT (HS256) |
| 可观测性 | OpenTelemetry + Prometheus |
| 数据库迁移 | Alembic |

### 前端
| 层次 | 技术 |
|------|------|
| 框架 | React 18 + TypeScript |
| 构建 | Vite 5 |
| 状态管理 | Zustand |
| 路由 | React Router v6 |
| UI | Tailwind CSS + Lucide Icons |
| 图表 | Recharts |
| Markdown | react-markdown + remark-gfm + rehype-raw |
| 代码高亮 | react-syntax-highlighter + Shiki |
| 虚拟滚动 | @tanstack/react-virtual |

### LLM 模型矩阵
| 角色 | 模型 | 用途 |
|------|------|------|
| QUERY | qwen3.7-max | 主查询/编排 |
| COMPRESS | qwen3.6-plus | 上下文压缩 |
| PLANNING | qwen3.6-plus | 规划 |
| ROUTER | qwen3-1.7b (JuniorShort) | L1 分类 |
| FAST | qwen3-8b (MiddleShort) | 简单回答 |
| CHEAP_CRITIC | qwen3.6-plus (SeniorShort) | 轻量批评 |
| KNOWLEDGE | qwen3.6-plus (SeniorShort) | 知识问答 |
| IDENTITY | qwen3-0.6b (MinShort) | 身份响应 |
| VISION | qwen3.6-vl-plus | 图像/图表理解 |

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        Frontend (React)                         │
│                   localhost:14108 (Vite Dev)                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP/SSE
┌──────────────────────────▼──────────────────────────────────────┐
│                    API Gateway (FastAPI)                         │
│                   localhost:14100                                │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Auth     │ │ Chat     │ │ Documents│ │ Data     │          │
│  │ Router   │ │ Router   │ │ Router   │ │ Router   │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐          │
│  │ Memory   │ │ Tasks    │ │ Skills   │ │ Admin    │          │
│  │ Router   │ │ Router   │ │ Router   │ │ Router   │          │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘          │
│  中间件: CORS + TenantContext + RequestContext                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                  Cognitive Kernel                                │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │              CognitiveExecutive (入口)                    │   │
│  │  Rewrite → Understand → Policy → Plan → Constraint       │   │
│  │  → Execute → Evidence → Fuse → Critic → Artifact         │   │
│  └──────────────────────────────────────────────────────────┘   │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐       │
│  │Runtime  │ │Evidence  │ │Fusion    │ │Critic        │       │
│  │Context  │ │Bus       │ │Engine V2 │ │Engine V2     │       │
│  └─────────┘ └──────────┘ └──────────┘ └──────────────┘       │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌──────────────┐       │
│  │Goal     │ │Governance│ │Capability│ │Cognitive     │       │
│  │Lifecycle│ │Center    │ │Intelligence│ │Supervisor   │       │
│  └─────────┘ └──────────┘ └──────────┘ └──────────────┘       │
└──────────────────────────┬──────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                     Agent Cluster                                │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐       │
│  │ Data │ │ RAG  │ │ Web  │ │ Tool │ │Skills│ │Vision│       │
│  │Agent │ │Agent │ │Agent │ │Agent │ │Agent │ │Agent │       │
│  └──────┘ └──────┘ └──────┘ └──────┘ └──────┘ └──────┘       │
└─────────────────────────────────────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│                    Infrastructure                                │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐      │
│  │Postgres│ │ Redis  │ │DashScope│ │OTel    │ │Sandbox │      │
│  │+pgvector│ │Multi-DB│ │(Qwen)  │ │+Prom   │ │Runtime │      │
│  └────────┘ └────────┘ └────────┘ └────────┘ └────────┘      │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. 目录结构

```
opentrace/
├── agents/                    # 智能体集群
│   ├── base.py               # AgentBase, AgentResult, TaskMessage
│   ├── registry.py           # AgentRegistry
│   ├── rag_agent.py          # RAG 检索智能体
│   ├── data_agent.py         # DataAgent V1
│   ├── data_agent_v2/        # DataAgent V2 认知管线
│   │   ├── types.py          # 类型定义
│   │   ├── supervisor.py     # 监督器
│   │   ├── error_classifier.py # 错误分类
│   │   ├── skills_engine.py  # 技能引擎
│   │   ├── knowledge_updater.py # 知识更新
│   │   └── dag_builder.py    # DAG 构建器
│   ├── web_agent.py          # 联网搜索智能体
│   ├── tool_agent.py         # 工具调用智能体
│   └── cognitive_agent.py    # 认知智能体
├── agent_runtime/             # Agent Runtime 流水线
│   ├── agent_runtime.py      # 运行时入口
│   └── agent_core/
│       └── base_agent.py     # 基础智能体
├── kernel/                    # 认知内核（核心）
│   ├── cognitive_kernel.py   # 内核入口
│   ├── dispatcher.py         # 请求分派器
│   ├── context_fabric.py     # 上下文织物
│   ├── context_fabric_graph.py # 上下文图
│   ├── semantic_cache.py     # 语义缓存
│   ├── tiny_router.py        # 轻量路由器
│   ├── refine_planner.py     # 有界重规划
│   ├── runtime/              # 运行时核心
│   │   ├── cognitive_executive.py # 认知执行器
│   │   ├── objects.py        # RuntimeObject, Evidence, ExecutionPlan
│   │   ├── orchestrator.py   # CognitivePlanner, UnifiedOrchestrator
│   │   ├── constraint_layer.py # 约束层
│   │   ├── evidence_bus.py   # 证据总线
│   │   ├── fusion.py         # FusionEngineV2
│   │   ├── critic.py         # CriticEngineV2
│   │   ├── workspace.py      # WorkspaceManager
│   │   ├── artifacts.py      # ArtifactManager
│   │   ├── context.py        # RuntimeContext
│   │   ├── executor.py       # ExecutionRuntime
│   │   ├── understanding_engine.py # 理解引擎
│   │   ├── rewrite_engine.py # 改写引擎
│   │   ├── policy.py         # UnifiedPolicyEngine
│   │   ├── registry.py       # 运行时注册表
│   │   ├── cognitive_iteration.py # 认知迭代
│   │   ├── self_optimizing_runtime.py # 自优化运行时
│   │   ├── multi_question_runtime.py # 多问题运行时
│   │   ├── finalize_turn.py  # 回合终结
│   │   ├── resume_turn.py    # 回合恢复
│   │   ├── runtime_turn_dispatcher.py # 回合分派
│   │   ├── memory_fabric.py  # 记忆织物
│   │   ├── evidence_runtime.py # 证据运行时
│   │   ├── evidence/         # 证据子系统
│   │   │   ├── lifecycle.py  # 证据生命周期
│   │   │   └── ranking.py    # 证据排序
│   │   └── memory/           # 记忆子系统
│   │       ├── confidence_decay.py # 置信度衰减
│   │       └── fact_supersession.py # 事实取代
│   ├── capability_intelligence/ # 能力智能层
│   │   ├── profiler.py       # CapabilityProfiler
│   │   ├── ontology.py       # CapabilityClass, ResourceCategory
│   │   ├── reasoner.py       # CapabilityReasoner
│   │   ├── adapter.py        # CapabilityAdapter
│   │   └── feedback.py       # CapabilityFeedbackLoop
│   ├── goal/                 # 目标系统
│   │   ├── state_machine.py  # GoalLifecycleState
│   │   ├── goal_supervisor.py # GoalSupervisor
│   │   └── goal_lifecycle.py # 目标生命周期
│   ├── governance/           # 治理系统
│   │   ├── governance_center.py # GovernanceCenter
│   │   └── adaptive_risk_engine.py # AdaptiveRiskEngine
│   ├── cognitive_supervisor/ # 认知监督
│   │   └── supervisor.py     # CognitiveSupervisor
│   ├── routing/              # 路由系统
│   │   └── v5_facade.py      # V5RoutingFacade
│   ├── cognition/            # 认知域
│   │   ├── types.py          # CapabilityLevel, TaskDomain
│   │   └── multi_question.py # 多问分解
│   ├── protocol/             # 协议层
│   │   ├── cognition_protocol.py # CognitionPhase
│   │   └── runtime_contract.py # Goal, GoalGraph, RuntimeTask
│   ├── fusion_engine/        # 融合引擎
│   │   ├── engine.py         # FusionEngine
│   │   └── models.py         # ToolResult, FusionInput, FusionOutput
│   ├── critic_engine/        # 审校引擎
│   │   ├── engine.py         # CriticEngine
│   │   └── models.py         # CriticInput, CriticOutput, CandidateScore
│   ├── data_cognition/       # 数据认知
│   │   ├── semantic_layer.py # SemanticLayer
│   │   ├── sql_planner.py    # SQLPlanner
│   │   ├── sql_validator.py  # SQL 验证
│   │   └── sql_reflector.py  # SQL 反射
│   ├── epistemology/         # 认识论
│   │   ├── evidence.py       # EvidenceLevel, AnnotatedContent
│   │   └── validator.py      # OutputValidator
│   ├── reasoning/            # 推理引擎
│   │   └── engine.py         # ReasoningEngine (DIRECT/COT/TOT)
│   ├── policy/               # 策略引擎
│   │   ├── engine.py         # PolicyEngine (Route/Strategy)
│   │   ├── rl_engine.py      # RL 策略引擎
│   │   └── bandit.py         # Multi-armed Bandit
│   ├── identity/             # 系统身份
│   │   └── system_identity.py # SYSTEM_IDENTITY, enforce_identity_output
│   ├── meta_cognition/       # 元认知
│   │   └── meta_cognition.py # MetaCognition (三层质量门控)
│   ├── prompt_engine/        # 提示词引擎
│   │   ├── engine.py         # PromptEngine
│   │   └── prompt_engine_v2.py # PromptEngineV2
│   ├── capability_runtime/   # 能力运行时
│   │   ├── capability_os.py  # CapabilityOS
│   │   ├── lifecycle.py      # CapabilityLifecycleState
│   │   └── contract.py       # CapabilityExecutionContract
│   └── strategy/             # 策略
│       └── capability_chain.py # 能力链
├── execution/                 # 执行平面
│   ├── dag_engine/           # DAG 引擎
│   │   ├── engine.py         # DAG 执行引擎
│   │   ├── graph.py          # DAGGraph, Task, TaskStatus
│   │   └── scheduler.py      # DAG 调度器
│   ├── workflow_engine/      # 工作流引擎
│   │   └── workflow.py       # Workflow
│   ├── tool_router/          # 工具路由
│   │   └── router.py         # ToolRouter
│   └── sandbox/              # 沙箱
│       └── sandbox.py        # Sandbox
├── gateway/                   # API 网关
│   └── api_gateway/
│       ├── main.py           # FastAPI 应用
│       └── routers/
│           └── chat.py       # Chat 路由
├── infra/                     # 基础设施
│   ├── config/
│   │   ├── settings.py       # 全局配置
│   │   └── flag_governance.py # Feature Flag 治理
│   ├── storage/
│   │   └── models.py         # ORM 模型
│   ├── cache/
│   │   └── redis_client.py   # Redis 客户端
│   ├── message_bus/
│   │   ├── cognitive_event_bus.py # 认知事件总线
│   │   └── events.py         # 事件定义
│   └── errors/
│       └── error_codes.py    # 错误码
├── model/                     # 模型层
│   ├── model_gateway/
│   │   └── gateway.py        # ModelGateway
│   ├── llm_adapter/
│   │   └── base.py           # LLM 适配器基类
│   ├── embedding/
│   │   └── base.py           # 嵌入模型基类
│   └── reranker/
│       └── base.py           # 重排序模型基类
├── memory/                    # 记忆系统
│   ├── episodic_memory/
│   │   └── episodic_memory.py # 情景记忆
│   ├── evolution/
│   │   ├── evolution.py      # 记忆进化
│   │   ├── governance.py     # 记忆治理
│   │   └── router.py         # 进化路由
│   └── fabric/
│       └── memory_graph.py   # 记忆图
├── safety/                    # 安全系统
│   ├── masking/
│   │   └── ner_masker.py     # NER 脱敏
│   ├── guardrails/
│   │   └── guardrails.py     # 安全护栏
│   ├── policy_engine/
│   │   └── engine.py         # 安全策略引擎
│   └── xai/
│       └── cognitive_trace.py # 认知追踪
├── tenant/                    # 多租户
│   ├── tenant_context.py     # 租户上下文
│   ├── quota_manager.py      # 配额管理
│   ├── billing_manager.py    # 计费管理
│   └── billing_runtime.py    # 计费运行时
├── control_plane/             # 控制平面
│   └── control_plane.py      # ControlPlane
├── evolution/                 # 演化系统
│   ├── learning/
│   │   └── learning.py       # 学习引擎
│   ├── meta_learning/
│   │   └── meta_learner.py   # 元学习
│   ├── self_play/
│   │   └── self_play.py      # 自博弈
│   ├── data_flywheel/
│   │   └── flywheel.py       # 数据飞轮
│   └── evaluation/
│       └── engine.py         # 评估引擎
├── connectors/                # 连接器
│   └── sdk/
│       └── protocol.py       # 连接器协议
├── sandbox_runtime/           # 沙箱运行时
│   └── executor.py           # 沙箱执行器
└── governance/                # 治理
    └── pii_detector.py       # PII 检测器
```

---

## 5. 前端应用

前端基于 React 18 + TypeScript + Vite 5 构建，使用 Zustand 管理状态，Tailwind CSS 构建 UI。

### 关键技术选型
- **状态管理**: Zustand（轻量、无样板代码）
- **路由**: React Router v6
- **UI 框架**: Tailwind CSS + Lucide Icons
- **图表**: Recharts
- **Markdown 渲染**: react-markdown + remark-gfm + rehype-raw
- **代码高亮**: react-syntax-highlighter + Shiki
- **虚拟滚动**: @tanstack/react-virtual

### 开发服务器
- 地址: `localhost:14108`
- 代理: API 请求代理至 `localhost:14100`

---

## 6. API 网关

### 模块路径
`gateway/api_gateway/main.py`, `gateway/api_gateway/routers/chat.py`

### 路由表
| 路由 | 方法 | 描述 |
|------|------|------|
| `/api/v1/chat` | POST | 对话接口（SSE 流式） |
| `/api/v1/documents` | POST | 文档上传 |
| `/api/v1/data` | POST | 数据查询 |
| `/api/v1/memory` | GET/POST | 记忆管理 |
| `/api/v1/tasks` | GET | 任务状态 |
| `/api/v1/skills` | GET | 技能列表 |
| `/api/v1/admin` | GET | 管理接口 |

### 中间件栈
1. **CORS** — 跨域支持
2. **TenantContext** — 多租户上下文注入
3. **RequestContext** — 请求级上下文（request_id, trace_id）

### Chat 路由核心流程
```
POST /api/v1/chat
→ 构建 KernelRequest
→ CognitiveKernel.process()
→ SSE 流式响应
```

---

## 7. 认知内核（Cognitive Kernel）

### 模块路径
`kernel/cognitive_kernel.py`

### 核心职责
认知内核是系统的中央调度器，负责：
1. 接收 API 网关转发的请求
2. V5 快速路径判断（L0 规则 / 语义缓存 / L1 路由）
3. 委托 CognitiveSupervisor 准备运行时
4. 通过 RuntimeGateway 调度执行
5. 返回 KernelResponse

### KernelRequest 数据结构
```python
@dataclass
class KernelRequest:
    query: str
    session_id: str
    user_id: str
    history: list[dict]
    metadata: dict
    trace_ctx: Any
    conversation_state: Any
    web_enabled: bool = False
```

### KernelResponse 数据结构
```python
@dataclass
class KernelResponse:
    content: str
    session_id: str
    route: str
    validation_score: float
    passed_validation: bool
    hallucination_risk: float
    intent_category: str
    intent_complexity: str
    metadata: dict
```

---

## 8. V5 分层路由

### 模块路径
`kernel/routing/v5_facade.py`

### V5RoutingFacade

V5 快速路径路由，在请求进入完整认知管线前尝试短路。

#### 数据结构

**V5FastPathResult**
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| hit | bool | — | 是否命中快速路径 |
| content | str | "" | 快速路径内容 |
| route | str | "" | 路由标签 |
| metadata | dict \| None | None | 元数据 |
| force_mode | str \| None | None | 强制模式 |

#### 方法

**`should_skip_v5(*, force_mode, has_attachments) → bool`**
- 当 force_mode 或有附件时跳过 V5 快速路径

**`try_fast_path(request, *, session_id, is_multi, context_hash_fn, t0) → V5FastPathResult | None`**
- 尝试 L0 规则路由 → 语义缓存 → L1 TinyRouter
- 命中时返回 V5FastPathResult，未命中返回 None

#### 快速路径优先级
1. **L0 规则路由** — 身份查询、斜杠命令、force_mode
2. **语义缓存** — 嵌入相似度 ≥ 0.92 时命中
3. **L1 TinyRouter** — 小型 LLM 分类 + 简单回答

---

## 9. L0 规则路由器

L0 规则路由器是零延迟的确定性路由层，通过正则匹配和关键词检测将请求分类：
- **identity** — 身份查询（"你是谁"、"你叫什么"等）
- **greeting** — 问候语
- **force_mode** — 斜杠命令（/rag, /data 等）
- **capability_help** — 能力查询

---

## 10. V4 编排器

V4 编排器是旧版编排管线，已被 CognitivePlanner V2 取代。保留用于向后兼容。

---

## 11. CognitiveExecutive V2 认知执行器

### 模块路径
`kernel/runtime/cognitive_executive.py`

### 类：CognitiveExecutive

认知执行中枢 — 所有请求的统一入口。请求经此完成一次认知决策，投影为 ExecutionPlan 后由运行时执行。

#### 惰性初始化组件
| 属性 | 类型 | 说明 |
|------|------|------|
| _rewrite_engine | RewriteEngine | 查询改写 |
| _understanding_engine | UnderstandingEngine | 深度理解 |
| _cognitive_planner | CognitivePlanner | 认知规划 |
| _cognitive_planner_v2 | CognitivePlannerV2 | V2 规划 |
| _strategy_builder | StrategyBuilder | 策略构建 |
| _capability_graph_builder | CapabilityGraphBuilder | 能力图构建 |
| _execution_runtime | ExecutionRuntime | 执行运行时 |
| _evidence_bus | EvidenceBus | 证据总线 |
| _fusion_engine | FusionEngineV2 | 融合引擎 |
| _critic_engine | CriticEngineV2 | 批评引擎 |
| _policy_engine | UnifiedPolicyEngine | 策略引擎 |
| _context_compressor | ContextCompressor | 上下文压缩 |
| _runtime_snapshots | RuntimeSnapshotStore | 运行时快照 |
| _trace | DeterministicTrace | 确定性追踪 |

#### 核心方法

**`execute(query, ctx, event_cb) → CognitiveExecutiveResult`**

完整认知流水线，包含以下阶段：

| 阶段 | 说明 | 是否调用 LLM |
|------|------|-------------|
| 0. IntentLock | 意图锁定与认知预算 | 否（规则） |
| 1. Rewrite | 查询改写 | 是（QUERY 角色） |
| 2. Understand | 深度理解 | 是（QUERY 角色） |
| 3. Policy | 策略检查 | 否（规则） |
| 3.5 Context Compress | 上下文压缩 | 是（COMPRESS 角色） |
| 4. Plan V2 | 认知规划 | 是（QUERY 角色） |
| 4.5 Constraint | 约束层检查 | 否（纯规则） |
| 5-6. Execute | DAG 执行 | 按能力 |
| 7. Evidence | 证据收集与排序 | 否 |
| 8. Fuse | 证据融合 | 条件性（QUERY 角色） |
| 9. Critic | 质量批评 | 条件性（CHEAP_CRITIC 角色） |
| 9.5 Capability Feedback | 能力反馈环 | 否 |
| 9.6 Failure Memory | 失败记忆记录 | 否 |
| 9.7 Cognitive Iteration | 认知迭代 | 条件性 |
| 10. Artifact | 制品合成 | 否 |
| 11. Archive | 证据归档 | 否 |

#### CognitiveExecutiveResult

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| answer | str | "" | 最终答案 |
| evidence_objects | list | [] | 证据对象列表 |
| artifact | Any | None | 制品 |
| plan | Any | None | 执行计划 |
| fusion_result | Any | None | 融合结果 |
| critic_result | Any | None | 批评结果 |
| rewrite_trace | str | "" | 改写追踪 |
| understanding | Any | None | 理解结果 |
| risk_level | str | "low" | 风险级别 |
| policy_denied | bool | False | 策略是否拒绝 |
| execution_reasoning | Any | None | 执行推理 |
| metadata | dict | {} | 元数据 |

#### 辅助方法

- **`_sync_goal_graph_from_runtime_task(ctx, plan)`** — 将执行子任务合并进 GoalGraph
- **`_apply_policy_mutation(ctx, kind, decision) → bool`** — 记录策略变更，返回是否应中止
- **`_phase_transition_blocked(ctx) → bool`** — 检查阶段转移是否被阻止
- **`_runtime_fabric_evolve(ctx, phase, evidence_ref, memory_ref)`** — 推进上下文织物
- **`_apply_phase_governance(ctx, phase, ...)`** — 应用阶段治理
- **`_apply_execution_guardrails(ctx, plan, execution_graph)`** — 执行前能力护栏
- **`compress_context(ctx, query)`** — 上下文压缩
- **`_simplify_plan(plan, decision)`** — 简化计划
- **`_direct_answer_fallback(query, ctx)`** — 直接 LLM 回答降级

#### 能力类型映射（_infer_capability_from_evidence）

| provenance.source | capability_type |
|-------------------|----------------|
| data | data.query |
| rag | rag.retrieve |
| web | web.search |
| tool | tool.datetime |
| skills | skills.execute |
| vision | vision.analyze |
| memory | memory.retrieve |

---

## 12. CognitivePlanner 与 UnifiedOrchestrator

### 模块路径
`kernel/runtime/orchestrator.py`

### UnifiedOrchestrator

一次性规划器 — 替代 PlanAgent + DST + ReferenceResolver + hard-guard。

#### Force Mode 映射

| force_mode | agent_type |
|------------|-----------|
| rag | rag |
| data_query | data |
| data_analysis | data |
| anomaly_tracking | skills |
| product | rule_engine |
| rule_engine | rule_engine |
| tool | tool |
| skills | skills |
| web | web |
| vision | vision |

#### 方法

**`plan(query, ctx) → TaskPlan`**
- force_mode: 跳过 LLM，直接映射
- 否则: 一次 LLM 调用生成完整 TaskPlan

**`_plan_via_llm(query, ctx) → TaskPlan`**
- 使用 QUERY 角色 LLM，temperature=0.0，max_tokens=800
- 解析 JSON 输出为 TaskPlan

**`_build_system_prompt(ctx) → str`**
- 包含可用 Agent 描述、数据源信息、编排规则

**`_build_user_prompt(query, ctx) → str`**
- 包含对话历史、记忆上下文、用户偏好、数据源、附件、技能

### CognitivePlanner

中央认知规划器 — 一次 LLM 调用生成完整 ExecutionPlan。

#### 方法

**`plan(query, ctx, understanding) → ExecutionPlan`**
- force_mode: 跳过 LLM
- 否则: 一次 LLM 调用（QUERY 角色，max_tokens=1200）

**`_enrich_plan_from_understanding(plan, understanding) → plan`**
- 从理解结果补充 understanding_summary 和 required_capabilities

#### Agent → Capability 映射

| agent_type | capability_type |
|-----------|----------------|
| data | data.query |
| rag | rag.retrieve |
| web | web.search |
| tool | tool.datetime |
| skills | skill.invoke |
| rule_engine | rule.lookup |
| vision | vision.analyze |

---

## 13. 约束层（Constraint Layer）

### 模块路径
`kernel/runtime/constraint_layer.py`

### PlannerConstraintLayer

确定性约束评估器 — 不调用 LLM，纯规则 + 查表。

#### ConstraintDecision

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| allowed | bool | True | 是否允许执行 |
| risk_level | str | "low" | 风险级别 |
| reason | str | "" | 拒绝原因 |
| modifications | list[str] | [] | 修改建议 |
| warnings | list[str] | [] | 警告 |
| fallback_strategy | str | "" | 降级策略 |

#### 五项约束检查

1. **预算检查** — token/延迟/成本上限
2. **策略/权限检查** — 能力前置条件
3. **风险阈值强制** — critical 风险强制串行
4. **能力可用性检查** — 注册表存在性 + 替代
5. **历史先验检查** — execution_memory + failure_memory

#### 预算常量

| 常量 | 值 |
|------|---|
| _DEFAULT_MAX_TOKENS | 4000 |
| _DEFAULT_MAX_LATENCY_MS | 30000 |
| _DEFAULT_MAX_PARALLEL_CAPABILITIES | 5 |

#### 风险等级 → 最大并行数

| risk_level | max_parallel |
|-----------|-------------|
| low | 5 |
| medium | 3 |
| high | 1 |
| critical | 1 |

#### 能力 Token 估算

| capability_type | estimated_tokens |
|----------------|-----------------|
| data.query | 600 |
| data.analysis | 900 |
| web.search | 500 |
| rag.retrieve | 400 |
| tool.datetime | 150 |
| tool.weather | 200 |
| tool.calculator | 150 |
| python.execute | 1200 |
| chart.generate | 800 |
| memory.retrieve | 250 |
| entity.resolution | 300 |
| vision.analyze | 700 |
| skills.execute | 600 |

#### 能力权限要求

| capability_type | required_permissions |
|----------------|---------------------|
| web.search | web_enabled |
| data.query | data_source_id |
| data.analysis | data_source_id |
| rag.retrieve | indexed_documents |
| vision.analyze | image_data |
| python.execute | sandbox_enabled |

#### 替代映射

| 原能力 | 替代能力 |
|--------|---------|
| web.search | rag.retrieve |
| rag.retrieve | web.search |
| data.analysis | data.query |
| python.execute | data.query |
| chart.generate | data.analysis |

---

## 14. 执行推理追踪（Execution Reasoning）

执行推理追踪记录从规划到执行的完整决策链，包括：
- 能力分配决策
- 约束层修改
- 跳过的能力
- 依赖关系

---

## 15. 智能体集群

### 模块路径
`agents/`

### AgentBase
所有智能体的基类，定义统一接口。

### AgentResult

| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | str | 任务 ID |
| agent_type | str | 智能体类型 |
| status | str | 状态（success/error） |
| content | str | 内容 |
| error | str | 错误信息 |
| confidence | float | 置信度 |
| metadata | dict | 元数据 |

### TaskMessage

| 字段 | 类型 | 说明 |
|------|------|------|
| task_id | str | 任务 ID |
| agent_type | str | 智能体类型 |
| query | str | 查询文本 |
| params | dict | 参数 |
| session_id | str | 会话 ID |
| user_id | str | 用户 ID |

### 智能体类型

| 智能体 | 文件 | 能力 |
|--------|------|------|
| DataAgent | data_agent.py | 结构化数据查询（Text2SQL） |
| RAGAgent | rag_agent.py | 文档检索 + 知识库 |
| WebAgent | web_agent.py | 联网搜索 |
| ToolAgent | tool_agent.py | 工具调用 |
| SkillsAgent | — | 技能执行 |
| VisionAgent | — | 图像分析 |
| CognitiveAgent | cognitive_agent.py | 认知推理 |

---

## 16. DataAgent V2 认知管线

### 模块路径
`agents/data_agent_v2/`

### 核心组件

| 模块 | 说明 |
|------|------|
| types.py | 类型定义 |
| supervisor.py | 监督器 |
| error_classifier.py | 错误分类 |
| skills_engine.py | 技能引擎 |
| knowledge_updater.py | 知识更新 |
| dag_builder.py | DAG 构建器 |

---

## 17. 模型网关

### 模块路径
`model/model_gateway/gateway.py`

### LLMRole 枚举

| 角色 | 模型 | 用途 |
|------|------|------|
| QUERY | qwen3.7-max | 主查询/编排 |
| COMPRESS | qwen3.6-plus | 上下文压缩 |
| PLANNING | qwen3.6-plus | 规划 |
| ROUTER | qwen3-1.7b | L1 分类 |
| FAST | qwen3-8b | 简单回答 |
| CHEAP_CRITIC | qwen3.6-plus | 轻量批评 |
| KNOWLEDGE | qwen3.6-plus | 知识问答 |
| IDENTITY | qwen3-0.6b | 身份响应 |
| VISION | qwen3.6-vl-plus | 图像理解 |

### LLMMessage

| 字段 | 类型 | 说明 |
|------|------|------|
| role | str | 消息角色（system/user/assistant） |
| content | str | 消息内容 |

### ModelGateway

**`complete(messages, role, temperature, max_tokens) → LLMResponse`**

统一 LLM 调用接口，按 role 路由到对应模型。

---

## 18. 记忆系统

### 模块路径
`memory/`

### 记忆类型
| 类型 | 半衰期 | 说明 |
|------|--------|------|
| fact | 720h (30天) | 事实记忆 |
| preference | 1440h (60天) | 用户偏好 |
| episodic | 168h (7天) | 情景记忆 |
| semantic | 2160h (90天) | 语义记忆 |
| procedural | 4320h (180天) | 过程记忆 |
| conversation | 24h (1天) | 对话上下文 |

### 记忆进化路由
`memory/evolution/router.py` — 根据记忆类型和时效性路由到不同进化策略。

---

## 19. 真值维护系统（TMS）

真值维护系统管理事实的版本控制和一致性：
- 事实从不删除，只被取代
- 维护完整的谱系链用于审计和回放
- 矛盾检测时施加惩罚

---

## 20. 记忆进化与治理

### 模块路径
`memory/evolution/`

### 组件
| 模块 | 说明 |
|------|------|
| evolution.py | 记忆进化引擎 |
| governance.py | 记忆治理（写入策略、污染检测） |
| router.py | 进化路由 |

---

## 21. 执行平面

### 模块路径
`execution/`

### DAG 引擎
`execution/dag_engine/`

| 组件 | 说明 |
|------|------|
| engine.py | DAG 执行引擎 |
| graph.py | DAGGraph, Task, TaskStatus |
| scheduler.py | DAG 调度器 |

### TaskStatus 枚举
| 值 | 说明 |
|----|------|
| PENDING | 待执行 |
| RUNNING | 执行中 |
| SUCCESS | 成功 |
| FAILED | 失败 |

### 工作流引擎
`execution/workflow_engine/workflow.py` — 声明式工作流定义与执行。

### 工具路由
`execution/tool_router/router.py` — 工具发现与路由。

### 沙箱
`execution/sandbox/sandbox.py` — 代码执行沙箱。

---

## 22. 数据认知层

### 模块路径
`kernel/data_cognition/`

### SemanticLayer

将业务术语映射到数据库构造。

#### DimensionMapping
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| column | str | "" | 数据库列名 |
| table | str | "" | 表名 |
| value_map | dict | {} | 业务值→数据库值映射 |
| description | str | "" | 描述 |

#### TimeMacroDef
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| pattern | str | "" | 匹配模式 |
| column | str | "" | 时间列 |
| table | str | "" | 表名 |
| operator | str | ">=" | 操作符 |
| days | int | 0 | 天数 |
| sql_template | str | "" | SQL 模板 |

#### 方法

**`resolve(query, dialect) → SemanticContext`**
- 解析维度映射、指标定义、时间宏

**`extract_time_intent(query) → dict | None`**
- 启发式时间意图提取
- 支持：绝对日期范围、月份范围、相对时间窗口、固定短语

### SQLPlanner

Text2SQL 规划器。

#### PlannedSQL
| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| sql | str | — | 生成的 SQL |
| join_path | list[str] | [] | JOIN 路径 |
| metadata | dict | {} | 元数据 |

#### 方法

**`plan(question, schema_hint, dialect) → PlannedSQL`**
- 使用 PLANNING 角色 LLM 生成 SQL

**`generate_candidates(question, schema_hint, dialect, n, semantic_fragments) → list[CandidateSQL]`**
- 生成多个候选 SQL（变温采样）

---

## 23. 能力智能层

### 模块路径
`kernel/capability_intelligence/`

### CapabilityProfiler

从注册表 + 种子数据 + 反馈构建并维护能力画像。

#### 种子数据（_SEED_DATA）

每种能力类型包含：
| 字段 | 说明 |
|------|------|
| description | 能力描述 |
| strengths | 擅长领域列表 |
| weaknesses | 局限列表 |
| ideal_queries | 理想查询示例 |
| anti_patterns | 反模式示例 |
| required_inputs | 必需输入 |
| output_types | 输出类型 |
| tags | 标签 |
| resource_type | 资源类型（cpu/io/gpu） |
| expected_latency_ms | 预期延迟 |
| reliability | 可靠性评分 |
| agent_type | 关联智能体类型 |

#### 14 种能力类型种子

| capability_type | reliability | latency_ms | resource |
|----------------|-------------|------------|----------|
| data.query | 0.92 | 3000 | cpu |
| data.analysis | 0.85 | 5000 | cpu |
| web.search | 0.80 | 2500 | io |
| rag.retrieve | 0.88 | 1500 | io |
| tool.datetime | 0.99 | 300 | cpu |
| tool.weather | 0.95 | 1500 | io |
| tool.calculator | 0.99 | 200 | cpu |
| python.execute | 0.85 | 8000 | cpu |
| chart.generate | 0.82 | 6000 | gpu |
| memory.retrieve | 0.90 | 500 | io |
| entity.resolution | 0.87 | 800 | cpu |
| vision.analyze | 0.80 | 5000 | gpu |
| skills.execute | 0.78 | 3000 | cpu |

#### 多目标评分公式

```
total = semantic_fitness × 0.30
      + historical_success × 0.25
      + contextual_compatibility × 0.20
      + budget_fit × 0.15
      + risk_fit × 0.10
```

#### 预算适配度评分

| budget_ratio | score |
|-------------|-------|
| ≥ 5 | 1.0 |
| ≥ 2 | 0.8 |
| ≥ 1 | 0.6 |
| ≥ 0.5 | 0.3 |
| < 0.5 | 0.1 |

#### 风险适配度评分

| risk_tolerance | threshold | 说明 |
|---------------|-----------|------|
| low | 0.60 | 低风险容忍 |
| medium | 0.75 | 中等 |
| high | 0.85 | 高风险容忍 |
| critical | 0.95 | 关键 |

### CapabilityClass 枚举（ontology.py）

| 值 | 说明 |
|----|------|
| DATA_QUERY | data.query |
| DATA_ANALYSIS | data.analysis |
| WEB_SEARCH | web.search |
| RAG_RETRIEVE | rag.retrieve |
| TOOL_DATETIME | tool.datetime |
| TOOL_WEATHER | tool.weather |
| TOOL_CALCULATOR | tool.calculator |
| PYTHON_EXECUTE | python.execute |
| CHART_GENERATE | chart.generate |
| MEMORY_RETRIEVE | memory.retrieve |
| ENTITY_RESOLUTION | entity.resolution |
| VISION_ANALYZE | vision.analyze |
| SKILLS_EXECUTE | skills.execute |

### ResourceCategory 枚举

| 值 | 说明 |
|----|------|
| CPU | CPU 密集 |
| IO | IO 密集 |
| GPU | GPU 密集 |

### QualityDimension 枚举

| 值 | 说明 |
|----|------|
| ACCURACY | 准确性 |
| COMPLETENESS | 完整性 |
| FRESHNESS | 新鲜度 |
| RELEVANCE | 相关性 |

### CapabilityReasoner

基于知识图谱 + 执行历史的推理引擎。

#### 方法

**`recommend_capability(gap_description, suggested_source, top_k) → list[tuple[CapabilityProfile, float]]`**

算法：
1. 从 profiler.match_scored() 获取 top_k*2 个带分匹配
2. 归一化匹配分数至 [0.3, 1.0]
3. 应用权重调整（退化→降低，改进→提升）
4. 知识图谱惩罚：依赖低可靠性能力时降级
5. 执行记忆惩罚：近期退化时降级
6. 按调整后分数排序

**`determine_execution_order(capabilities) → TopologicalOrder`**
- 利用知识图谱拓扑确定最优执行顺序

**`find_alternative(target, unavailable_reasons) → tuple[str|None, str]`**
- 查找替代能力

**`get_execution_strategy_hint(capabilities, query_domain) → str`**
- 推荐执行策略（direct/parallel/sequential/compare）

### CapabilityAdapter

将能力画像格式化为 LLM 提示。

#### 方法

**`format_for_cognitive_planner(profiles) → str`** — CognitivePlanner 系统提示
**`format_for_understanding_engine(profiles) → str`** — UnderstandingEngine 提示
**`format_for_self_model(profiles) → str`** — SelfModel 身份提示
**`find_best_capability(suggested_source, gap_description, profiles) → str|None`** — 最佳能力匹配
**`format_knowledge_graph_for_prompt(kg) → str`** — 知识图谱关系摘要

### CapabilityFeedbackLoop

记录执行结果并回灌到能力画像。

- 内部使用 deque(maxlen=200) 存储记录
- 每次记录立即更新 profiler 的可靠性与延迟估计
- 可靠性更新：增量均值
- 延迟更新：指数移动平均（新观测权重 0.2）

---

## 24. 证据生命周期管理

### 证据状态机

```
CREATED → VALIDATED → RANKED → MERGED → ARCHIVED
                ↓         ↓         ↓
           INVALIDATED  SUPERSEDED  SUPERSEDED
```

### EvidenceLifecycle（lifecycle.py）

| 方法 | 说明 |
|------|------|
| register(evidence_id, initial_state) | 注册新证据 |
| get_state(evidence_id) | 获取状态 |
| transition(evidence_id, target, force) | 状态转换 |
| validate(evidence_id, credibility_score) | 验证 |
| rank(evidence_id) | 标记已排序 |
| merge(evidence_id) | 标记已合并 |
| supersede(old_id, new_id, reason) | 取代 |
| archive(evidence_id) | 归档 |
| invalidate(evidence_id, reason) | 失效 |
| get_usable_evidence_ids() | 获取可用证据 |
| get_lifecycle_summary() | 生命周期摘要 |

### EvidenceRanker（ranking.py）

多维度证据排序。

#### 权重配置

| 维度 | 权重 |
|------|------|
| 可信度 | 0.35 |
| 相关性 | 0.35 |
| 新鲜度 | 0.15 |
| 权威性 | 0.15 |

#### RankedEvidence

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| evidence_id | str | "" | 证据 ID |
| content | str | "" | 内容 |
| source | str | "" | 来源 |
| credibility_score | float | 0.5 | 可信度 |
| relevance_score | float | 0.5 | 相关性 |
| freshness_score | float | 0.5 | 新鲜度 |
| authority_score | float | 0.5 | 权威性 |
| composite_score | float | 0.5 | 综合评分 |
| rank | int | 0 | 排名 |
| metadata | dict | {} | 元数据 |

#### 新鲜度公式

```
freshness = max(0.1, 1.0 / (1.0 + age_hours / 24.0))
```

24 小时半衰期。

#### 来源权威性评分

| source | authority_score |
|--------|----------------|
| data | 0.9 |
| rag | 0.7 |
| skills | 0.8 |
| web | 0.5 |
| tool | 0.7 |
| rule_engine | 0.8 |
| vision | 0.6 |

---

## 25. 策略引擎

### 模块路径
`kernel/runtime/policy.py`

### PolicyRule

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| name | str | — | 规则名称 |
| description | str | — | 描述 |
| priority | int | 0 | 优先级（越高越先评估） |
| condition | str | "" | 条件描述 |
| action | str | "allow" | 动作（allow/deny/warn/require_confirmation） |

### PolicyDecision

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| allowed | bool | True | 是否允许 |
| risk_level | str | "low" | 风险级别 |
| reason | str | "" | 原因 |
| requires_confirmation | bool | False | 是否需要确认 |
| denied_rules | list[str] | [] | 拒绝规则列表 |
| warnings | list[str] | [] | 警告列表 |

### UnifiedPolicyEngine

- 按优先级评估规则
- 首个 deny 停止评估
- 模块级单例：`policy_engine`

---

## 26. 推理引擎

### 模块路径
`kernel/reasoning/engine.py`

### ReasoningEngine

三种推理模式：

| 模式 | 说明 | LLM 调用次数 |
|------|------|-------------|
| DIRECT | 单次调用，快速 | 1 |
| COT | 链式推理，结构化思考 | 1 |
| TOT | 思维树：探索 N 分支，评判最佳 | N+1 |

### ReasoningResult

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| thinking | str | — | 推理过程 |
| answer | str | — | 最终答案 |
| strategy | str | "DIRECT" | 策略 |
| confidence | float | 1.0 | 置信度 |
| metadata | dict | {} | 元数据 |

### COT 输出格式

```
<thinking>...reasoning steps...</thinking>
<answer>...final answer...</answer>
```

### TOT 流程

1. 并行生成 N 个分支（temperature=0.7）
2. 收集所有分支方案
3. 评判最佳方案（temperature=0.1）

---

## 27. 世界模型

世界模型维护运行时的世界状态投影，包括：
- 目标图投影
- 上下文织物状态
- 运行时阶段追踪

---

## 28. 融合引擎

### FusionEngineV2（kernel/runtime/fusion.py）

LLM 驱动的语义证据融合。

#### 融合路径

| 条件 | 路径 | 说明 |
|------|------|------|
| 无证据 | empty | 返回空 |
| 全部失败 | error_aggregation | 聚合错误 |
| 有矛盾 + LLM 启用 + ≥2 证据 | llm_fusion_v2 | LLM 语义融合 |
| 其他 | heuristic_v2 | 启发式拼接 |

#### FusionResult

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| merged_context | str | — | 融合后内容 |
| confidence | float | 0.0 | 置信度 |
| contradictions | list[str] | [] | 矛盾列表 |
| method | str | "" | 融合方法 |
| evidence_ids | list[str] | [] | 证据 ID |

#### 矛盾检测

1. **数值矛盾** — 跨来源数值比值 > 2.0
2. **关键词矛盾** — 增加/下降、增长/减少等对立词对

### FusionEngine（kernel/fusion_engine/engine.py）

加权合并融合引擎。

#### 来源权重

| source | weight |
|--------|--------|
| llmwiki | 1.05 |
| document | 0.72 |
| sql | 1.0 |
| weather | 0.9 |
| time | 0.9 |
| search | 0.6 |
| web_search | 0.6 |
| attachment | 0.85 |
| memory | 0.55 |

#### 置信度公式

```
confidence = Σ(confidence_i × (weight_i + freshness_bonus_i + priority_bonus_i))
           / Σ(weight_i + freshness_bonus_i + priority_bonus_i)
```

#### FusionInput

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query | str | — | 查询 |
| results | list[ToolResult] | [] | 工具结果 |
| adaptive_profile | dict | {} | 自适应画像 |
| conversation_history | list[dict] | [] | 对话历史 |

#### FusionOutput

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| merged_context | str | — | 融合内容 |
| conflicts | list[str] | [] | 冲突 |
| confidence | float | 0.0 | 置信度 |
| alternate_contexts | list[str] | [] | 备选内容 |
| evidence_map | list[dict] | [] | 证据映射 |
| result_refs | list[dict] | [] | 结果引用 |

---

## 29. 审校引擎

### CriticEngineV2（kernel/runtime/critic.py）

LLM 驱动的结构化质量评估。

#### 评估路径

| 条件 | 路径 |
|------|------|
| 空回答 | 返回 passed=False |
| LLM 启用 + quality 画像 | llm_critic_v2 |
| 其他 | heuristic_v2 |

#### CriticResult

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| passed | bool | True | 是否通过 |
| factuality | float | 0.7 | 事实性 |
| completeness | float | 0.7 | 完整性 |
| evidence_coverage | float | 0.5 | 证据覆盖度 |
| hallucination_risk | float | 0.3 | 幻觉风险 |
| evidence_utilization | float | 0.5 | 证据利用率 |
| notes | str | "" | 备注 |
| method | str | "" | 评估方法 |

#### 启发式评估规则

| 条件 | factuality | completeness | hallucination_risk |
|------|-----------|-------------|-------------------|
| 拒答模式 | 0.9 | 0.2 | — |
| 默认 | 0.7 | — | — |
| answer_len < 20 | — | 0.1 | 0.1 |
| answer_len < 100 | — | 0.5 | — |
| answer_len ≥ 100 | — | 0.8 | 0.3 |
| evidence_count = 0 | — | — | — |
| evidence_count = 1 | evidence_coverage=0.6 | — | — |
| evidence_count ≥ 2 | evidence_coverage=0.8 | — | — |

### CriticEngine（kernel/critic_engine/engine.py）

增强批评引擎 — 多候选评分与可解释置信度分解。

#### CandidateScore

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| answer | str | — | 答案 |
| source | str | "" | 来源 |
| factual_consistency | float | 0.0 | 事实一致性 |
| relevance | float | 0.0 | 相关性 |
| completeness | float | 0.0 | 完整性 |
| coherence | float | 0.0 | 连贯性 |

#### 综合评分公式

```
composite = 0.35 × factual_consistency
          + 0.30 × relevance
          + 0.20 × completeness
          + 0.15 × coherence
```

#### CriticInput

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| query | str | — | 查询 |
| answer | str | — | 答案 |
| fusion_context | str | — | 融合上下文 |
| fusion_confidence | float | — | 融合置信度 |
| adaptive_profile | dict \| None | None | 自适应画像 |
| candidate_answers | list[dict] | [] | 候选答案 |

#### CriticOutput

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| need_fix | bool | — | 是否需要修复 |
| feedback | str | — | 反馈 |
| improved_answer | str | "" | 改进答案 |
| confidence_breakdown | dict | {} | 置信度分解 |
| confidence_explanation | str | "" | 置信度说明 |
| candidate_scores | list[CandidateScore] | [] | 候选评分 |
| selected_candidate_index | int | -1 | 选中候选索引 |

#### 置信度分解维度

| 维度 | 说明 | 计算方式 |
|------|------|---------|
| source_coverage | 来源覆盖 | min(1.0, sources/3.0) |
| answer_substance | 回答实质 | 基于长度分档 |
| non_refusal | 非拒答 | 1.0 - refusal_count × 0.25 |
| specificity | 具体性 | 数字+日期+实体+百分比加分 |

---

## 30. 认识论层

### 模块路径
`kernel/epistemology/`

### EvidenceLevel 枚举

| 值 | 级别 | 图标 | 说明 |
|----|------|------|------|
| FACT | 1 | 📊 | 事实 |
| DOCUMENT | 2 | 📄 | 文档 |
| SEARCH | 3 | 🔗 | 搜索 |
| MEMORY | 4 | 🧠 | 记忆 |
| INFERENCE | 5 | 💡 | 推理 |
| SPECULATION | 6 | ⚠️ | 推测 |

### SourceType 枚举

| 值 | 说明 |
|----|------|
| DATABASE | 数据库 |
| DOCUMENT | 文档 |
| WEB_SEARCH | 网页搜索 |
| USER_MEMORY | 用户记忆 |
| TOOL_OUTPUT | 工具输出 |
| MODEL_INFERENCE | 模型推理 |
| HYBRID | 混合 |

### AnnotatedContent

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| id | str | uuid4() | 内容 ID |
| text | str | "" | 文本 |
| annotation | EvidenceAnnotation \| None | None | 标注 |
| render_hint | dict \| None | None | 渲染提示 |

### OutputValidator

输出质量门禁：
- 检测未处理的 JSON 块
- 事实性断言缺少引用时警告
- 推测性内容自动添加不确定性标注

---

## 31. 元认知

### 模块路径
`kernel/meta_cognition/meta_cognition.py`

### MetaCognition

三层质量门控：

| 层级 | 条件 | 动作 |
|------|------|------|
| 第一层 | score ≥ 0.8 | 直接通过 |
| 第二层 | 0.6 ≤ score < 0.8 | 精炼一次 |
| 第三层 | score < 0.6 | 重试（最多 max_retries 次） |

#### ValidationResult

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| passed | bool | — | 是否通过 |
| score | float | — | 评分 |
| reason | str | — | 原因 |
| final_answer | Any | — | 最终答案 |
| hallucination_risk | float | 0.0 | 幻觉风险 |
| issues | list[str] | [] | 问题列表 |

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| high_threshold | float | 0.8 | 高阈值 |
| low_threshold | float | 0.6 | 低阈值 |
| max_retries | int | 2 | 最大重试次数 |

---

## 32. 系统身份

### 模块路径
`kernel/identity/system_identity.py`

### SYSTEM_IDENTITY

系统身份提示词，定义 OpenTrace 的核心身份：
- 基于 Cognitive Kernel 构建的智能认知系统
- 能力来源：推理引擎、工具系统、记忆系统、文档系统
- 禁止暴露底层模型信息
- 禁止自称 Qwen、ChatGPT、Claude 等

### 核心函数

**`build_system_identity(extra_instruction) → str`**
- 构建 SYSTEM_IDENTITY + 额外指令

**`merge_system_identity(messages) → list[LLMMessage]`**
- 合并多个 system 消息为单一 identity

**`is_identity_user_query(text) → bool`**
- 检测身份查询（"你是谁"等）

**`enforce_identity_output(content, user_text) → str`**
- 强制身份输出，替换禁止的自称

### 禁止自称正则

```python
_FORBIDDEN_SELF_ID = re.compile(
    r"(Qwen|通义千问|ChatGPT|GPT[- ]?\d|OpenAI|Anthropic|Claude|文心一言|讯飞星火|豆包|"
    r"阿里云的大语言模型|由阿里云开发|Google\s*Gemini|Gemini\s*Pro|DashScope)",
    re.IGNORECASE,
)
```

---

## 33. 认知协议

### 模块路径
`kernel/protocol/cognition_protocol.py`

### CognitionPhase 枚举

| 值 | 说明 |
|----|------|
| UNDERSTAND | 理解 |
| PLAN | 规划 |
| DECOMPOSE | 分解 |
| REFLECT | 反思 |
| CONSTRAINT | 约束 |

### CognitionEnvelope

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| phase | CognitionPhase | — | 认知阶段 |
| session_id | str | — | 会话 ID |
| request_id | str | — | 请求 ID |
| payload | dict | {} | 载荷 |
| version | str | "cognition_protocol_v1" | 协议版本 |

### PlanningArtifact

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| goal_graph | dict | {} | 目标图 |
| protected_intent | str | "" | 受保护意图 |
| task_type | str | "general_qa" | 任务类型 |
| constraints | dict | {} | 约束 |
| metadata | dict | {} | 元数据 |

---

## 34. 安全与防护

### 模块路径
`safety/`

### 组件

| 模块 | 说明 |
|------|------|
| masking/ner_masker.py | NER 命名实体识别脱敏 |
| guardrails/guardrails.py | 安全护栏 |
| policy_engine/engine.py | 安全策略引擎 |
| xai/cognitive_trace.py | 认知追踪（可解释性） |

---

## 35. 沙箱运行时

### 模块路径
`sandbox_runtime/executor.py`

代码执行沙箱，支持 Python 代码的安全执行。

---

## 36. Agent Runtime 多智能体流水线

### 模块路径
`agent_runtime/`

### 组件
| 模块 | 说明 |
|------|------|
| agent_runtime.py | 运行时入口 |
| agent_core/base_agent.py | 基础智能体抽象 |

---

## 37. 演化与学习系统

### 模块路径
`evolution/`

### 组件

| 模块 | 说明 |
|------|------|
| learning/learning.py | 学习引擎 |
| meta_learning/meta_learner.py | 元学习 |
| self_play/self_play.py | 自博弈 |
| data_flywheel/flywheel.py | 数据飞轮 |
| evaluation/engine.py | 评估引擎 |

---

## 38. 确定性重放与审计

运行时快照系统，在每个阶段边界记录提示词快照与运行时快照，供确定性回放与审计。

---

## 39. 插件系统

插件系统支持动态扩展系统能力。

---

## 40. 技能系统

技能系统提供领域专精任务的执行能力。

---

## 41. 规则引擎

规则引擎处理产品/规则查询。

---

## 42. 治理中心

### 模块路径
`kernel/governance/governance_center.py`

### GovernanceCenter

统一治理入口，包含以下子治理器：

| 子系统 | 说明 |
|--------|------|
| RuntimeGovernor | 运行时治理 |
| EvidenceGovernor | 证据治理 |
| RiskGovernor | 风险治理 |
| CapabilityGovernor | 能力治理 |
| MemoryGovernor | 记忆治理 |
| PolicyGovernor | 策略治理 |
| AuditGovernor | 审计治理 |

#### TurnGovernanceBundle

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| runtime | dict | {} | 运行时治理 |
| evidence | dict | {} | 证据治理 |
| risk | dict | {} | 风险治理 |
| semantic_observability | dict | {} | 语义可观测性 |

#### 方法

**`evaluate_task(task) → TurnGovernanceBundle`**
**`evaluate_planning_mutation(ctx) → dict`**
**`evaluate_memory_mutation(proposed_tokens, pollution_risk) → dict`**
**`evaluate_evidence_fusion_mutation(evidence_count, min_required, hallucination_risk) → dict`**
**`evaluate_replay_mutation(contract) → dict`**
**`evaluate_turn(...) → TurnGovernanceBundle`**

---

## 43. 基础设施层

### 模块路径
`infra/`

### 配置（settings.py）

全局配置通过 `settings` 对象访问，支持 Feature Flag 治理。

### Redis 客户端（redis_client.py）

多 DB 分区 Redis 客户端。

### 认知事件总线（cognitive_event_bus.py）

进程内事件发布/订阅。

### 错误码（error_codes.py）

统一错误码定义。

---

## 44. API SDK

外部 SDK 接口，提供标准化的 API 调用方式。

---

## 45. 连接器

### 模块路径
`connectors/sdk/protocol.py`

连接器协议定义，支持外部系统集成。

---

## 46. 上下文系统

### RuntimeContext

单次认知回合的统一请求上下文。

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| request_id | str | — | 请求 ID |
| session_id | str | — | 会话 ID |
| user_id | str | — | 用户 ID |
| query | str | — | 用户原始输入 |
| raw_user_query | str | "" | 原始用户查询 |
| protected_intent | str | "" | 受保护意图 |
| task_type | str | "general_qa" | 任务类型 |
| allowed_capabilities | list[str] | [] | 允许的能力 |
| disallowed_capabilities | list[str] | [] | 禁止的能力 |
| intent_confidence | float | 0.0 | 意图置信度 |
| cognitive_budget | dict | {} | 认知预算 |
| relevance_threshold | float | 0.35 | 相关性阈值 |
| conversation_history | list[dict] | [] | 对话历史 |
| conversation_state | Any | None | 对话状态 |
| memory_context | str | "" | 记忆上下文 |
| episodic_events | list[dict] | [] | 情景事件 |
| workspace_state | dict | {} | 工作空间状态 |
| user_preferences | list[str] | [] | 用户偏好 |
| user_style_hints | dict \| None | None | 用户风格提示 |
| preference_context_block | str | "" | 偏好上下文块 |
| data_source_context | dict | {} | 数据源上下文 |
| available_data_sources | list[dict] | [] | 可用数据源 |
| attachment_contexts | list[dict] | [] | 附件上下文 |
| force_mode | str \| None | None | 强制模式 |
| web_enabled | bool | False | 是否启用联网 |
| graph_controls | dict | {} | 图控制 |
| is_branch_request | bool | False | 是否分支请求 |
| branch_checkpoint | dict \| None | None | 分支检查点 |
| parent_message_id | str \| None | None | 父消息 ID |
| previous_plan | Any | None | 上一轮计划 |
| previous_results | Any | None | 上一轮结果 |
| clarify_context | str \| None | None | 澄清上下文 |
| clarify_question_id | str \| None | None | 澄清问题 ID |
| enabled_skills | list[str] | [] | 启用的技能 |
| disabled_skills | list[str] | [] | 禁用的技能 |
| risk_assessment | dict | {} | 风险评估 |
| tool_permission_token | str \| None | None | 工具权限令牌 |
| stream | bool | False | 是否流式 |
| trace_ctx | Any | None | 链路追踪 |
| adaptive_profile | dict | {} | 自适应画像 |
| metadata | dict \| None | None | 通用元数据 |

---

## 47. 对话状态管理

对话状态跟踪当前对话的主题、意图、阶段等信息。

---

## 48. 澄清门控

当查询存在歧义时，触发澄清流程，向用户确认意图。

---

## 49. 自适应配置与偏好层级

自适应配置系统根据用户画像和查询特征动态调整系统行为。

---

## 50. Web 搜索引擎

联网搜索智能体，获取实时信息。

---

## 51. 内置工具系统

| 工具 | capability_type | 说明 |
|------|----------------|------|
| 时间查询 | tool.datetime | 日期时间、时区转换 |
| 天气查询 | tool.weather | 实时天气、预报 |
| 计算器 | tool.calculator | 数值计算 |
| 代码执行 | python.execute | Python 沙箱执行 |
| 图表生成 | chart.generate | 数据可视化 |

---

## 52. PlanAgent 与 PlanMemory

规划智能体与规划记忆，维护历史规划结果供后续参考。

---

## 53. RefinePlanner 有界局部重规划

### 模块路径
`kernel/refine_planner.py`

### FailureType 枚举

| 值 | 说明 |
|----|------|
| SCHEMA_MISMATCH | Schema 不匹配 |
| TIMEOUT | 超时 |
| EMPTY_RESULT | 空结果 |
| PERMISSION_DENIED | 权限拒绝 |
| HALLUCINATION | 幻觉 |
| LOW_CRITIC | 低批评分 |
| UNKNOWN | 未知 |

### RepairStrategy 枚举

| 值 | 说明 |
|----|------|
| RETRY | 重试相同能力 |
| SIMPLIFY | 降低查询复杂度 |
| SUBSTITUTE | 替换为替代能力 |
| SPLIT | 分解为更小步骤 |
| PREPEND | 添加准备步骤 |
| SKIP | 跳过此节点 |
| ABORT | 中止该分支 |

### 失败类型 → 修复策略映射

| FailureType | 推荐策略（按优先级） |
|-------------|---------------------|
| SCHEMA_MISMATCH | PREPEND, SIMPLIFY, SUBSTITUTE |
| TIMEOUT | RETRY, SIMPLIFY, SUBSTITUTE |
| EMPTY_RESULT | SIMPLIFY, SUBSTITUTE, SKIP |
| PERMISSION_DENIED | SUBSTITUTE, SKIP, ABORT |
| HALLUCINATION | SUBSTITUTE, SPLIT, ABORT |
| LOW_CRITIC | SIMPLIFY, RETRY, SKIP |
| UNKNOWN | RETRY, SUBSTITUTE, ABORT |

### CorrectionIntent

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| is_correction | bool | False | 是否需要修正 |
| failure_type | FailureType | UNKNOWN | 失败类型 |
| failed_node_id | str | "" | 失败节点 ID |
| failure_reason | str | "" | 失败原因 |
| confidence | float | 0.0 | 置信度 |
| corrected_query | str | "" | 修正查询 |

### RefinedPlan

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| plan | Any | None | 修改后的计划 |
| reused_results | dict | {} | 复用的结果 |
| replaced_indices | list[int] | [] | 替换的索引 |
| new_nodes | list | [] | 新增节点 |
| removed_node_ids | list[str] | [] | 移除的节点 ID |
| repair_strategy | RepairStrategy | ABORT | 修复策略 |
| depth | int | 0 | 重规划深度 |

### 关键约束
- 最大重规划深度：2 层
- 仅重建失败节点的下游
- 不调用顶层模型 — 确定性修复策略选择

---

## 54. 上下文运行时（Context Runtime）

上下文运行时管理上下文压缩和组装。

### ContextCompressor
- max_tokens: 600
- 压缩记忆上下文（>800 字符时触发）
- 压缩偏好上下文（>500 字符时触发）
- quality_score > 0.5 时应用压缩

---

## 55. 证据生命周期详细管理

详见第 24 章。

---

## 56. Prompt 引擎

### 模块路径
`kernel/prompt_engine/engine.py`

### PromptEngine

基于模板的提示词构建器。

#### 内置模板

| 模板名 | 说明 |
|--------|------|
| system_default | 默认系统提示（含日期变量 $date） |
| rag_context | RAG 上下文提示 |
| summarize | 文本摘要 |
| tool_result | 工具结果注入 |

#### 方法

**`render(template_name, **kwargs) → str`** — 渲染模板
**`add_template(name, template) → None`** — 添加模板
**`list_templates() → list[str]`** — 列出模板

---

## 57. 意图引擎

意图引擎负责查询意图分类和认知预算分配。

---

## 58. 序列融合引擎

序列融合处理多轮对话中的信息累积和上下文维护。

---

## 59. Dispatcher 与 Runtime Supervisor

### 运行时注册表（registry.py）

| 运行时 | 说明 |
|--------|------|
| cognitive_executive | 认知执行器（默认） |
| data_intelligence | 数据智能运行时 |
| multi_goal | 多目标运行时 |

### CognitiveSupervisor（supervisor.py）

认知监督层，位于 CognitiveKernel 与 RuntimeGateway 之间。

#### SupervisorPreparedRun

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| runtime_task | RuntimeTask | — | 运行时任务 |
| ctx | Any | None | 运行时上下文 |
| route_hint | str | "cognitive_executive" | 路由提示 |
| multi_question_result | Any \| None | None | 多问结果 |
| governance_meta | dict | {} | 治理元数据 |
| semantic_observability | dict | {} | 语义可观测性 |
| goal_graph_dict | dict | {} | 目标图字典 |

#### prepare_run 流程

1. 控制平面门控检查
2. RuntimeTask 构建（slim/full）
3. 运行时策略评估
4. 运行时治理评估
5. RuntimeContext 构建
6. 世界状态注入
7. 目标图绑定
8. 策略投影注入
9. 上下文织物种子

---

## 60. Token 计数与历史检索

Token 计数用于控制上下文窗口大小，历史检索提供对话上下文。

---

## 61. DAG 计划与调度

### ExecutionRuntime（executor.py）

统一执行层，接收计划并通过 DAG 引擎执行。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| capability_registry | Any | None | 能力注册表 |
| timeout_sec | int | 30 | 超时时间 |
| max_parallel | int | 5 | 最大并行数 |

#### 执行流程

1. 从 TaskPlan 或 ExecutionGraph 构建 DAGGraph
2. 按依赖关系和并行度执行
3. 支持有界重规划（最多 2 层）
4. 失败节点记录到 failure_memory

---

## 62. 服务层与文件解析

服务层提供文件上传、解析和索引功能。

---

## 63. 嵌入模型与向量检索

### 模块路径
`model/embedding/base.py`

嵌入模型基类，支持 text-embedding-v3（1024 维）。

---

## 64. 重排序模型

### 模块路径
`model/reranker/base.py`

重排序模型基类，支持 BAAI/bge-reranker-v2-m3 和启发式重排序。

---

## 65. LLM 适配器

### 模块路径
`model/llm_adapter/base.py`

LLM 适配器基类，定义统一的 LLM 调用接口。

### LLMMessage

| 字段 | 类型 | 说明 |
|------|------|------|
| role | str | 消息角色 |
| content | str | 消息内容 |

---

## 66. ShadowRedis 双写缓存

ShadowRedis 提供双写缓存机制，确保缓存一致性。

---

## 67. 消息总线详细架构

### 模块路径
`infra/message_bus/`

### CognitiveEventBus

进程内认知事件发布/订阅总线。

### Events

事件定义，包含事件类型和载荷格式。

---

## 68. 可观测性体系

可观测性基于 OpenTelemetry + Prometheus：
- 请求级追踪
- 阶段级指标
- 语义可观测性（认知健康度、自适应风险）

---

## 69. 数据库访问与 ORM 模型

### 模块路径
`infra/storage/models.py`

使用 SQLAlchemy 2.0 (async) 定义 ORM 模型。

---

## 70. 零信任安全详细架构

零信任安全架构包含：
- JWT 认证
- 租户隔离
- PII 检测与脱敏
- 安全护栏
- 安全策略引擎

---

## 71. DataAgent V1 管线

### 模块路径
`agents/data_agent.py`

DataAgent V1 是旧版数据查询智能体，已被 V2 取代。

---

## 72. RAGAgent 详细架构

### 模块路径
`agents/rag_agent.py`

RAG 检索智能体，负责文档检索和知识库查询。

---

## 73. DataAgent V2 错误分类与修复

### 模块路径
`agents/data_agent_v2/error_classifier.py`

错误分类器将执行错误分类为可修复类型，触发相应的修复策略。

---

## 74. DataAgent V2 知识层与学习闭环

### 模块路径
`agents/data_agent_v2/knowledge_updater.py`

知识更新器从执行结果中提取知识并更新知识库。

---

## 75. DataAgent V2 高级分析

### 模块路径
`agents/data_agent_v2/skills_engine.py`, `agents/data_agent_v2/dag_builder.py`

高级分析技能引擎和 DAG 构建器。

---

## 76. 目标生命周期系统（Goal Lifecycle）

### 模块路径
`kernel/goal/`

### GoalLifecycleState 枚举

| 值 | 说明 |
|----|------|
| CREATED | 已创建 |
| PROJECTED | 已投影 |
| ACTIVE | 活跃 |
| EXECUTING | 执行中 |
| WAITING | 等待中 |
| BLOCKED | 已阻塞 |
| REPLANNING | 重规划中 |
| EVIDENCE_COLLECTED | 证据已收集 |
| FUSED | 已融合 |
| COMPLETED | 已完成 |
| FAILED | 已失败 |
| ARCHIVED | 已归档 |

### 有效状态转换

| 当前状态 | 可转换至 |
|---------|---------|
| CREATED | PROJECTED, FAILED, BLOCKED |
| PROJECTED | ACTIVE, EXECUTING, WAITING, BLOCKED, FAILED |
| ACTIVE | EXECUTING, WAITING, BLOCKED, REPLANNING, FAILED |
| EXECUTING | EVIDENCE_COLLECTED, WAITING, REPLANNING, BLOCKED, FAILED |
| WAITING | EXECUTING, ACTIVE, BLOCKED, FAILED |
| BLOCKED | PROJECTED, FAILED, ARCHIVED |
| REPLANNING | PROJECTED, EXECUTING, FAILED |
| EVIDENCE_COLLECTED | FUSED, FAILED |
| FUSED | COMPLETED, FAILED |
| COMPLETED | ARCHIVED |
| FAILED | ARCHIVED, PROJECTED |
| ARCHIVED | —（终态） |

### GoalSupervisor

目标监督器，负责目标拆分、合并、冲突检测和退休提示。

#### GoalSupervisorDecision

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| graph | GoalGraph | — | 目标图 |
| merged_goal_ids | list[str] | [] | 合并的目标 ID |
| split_from_root | bool | False | 是否从根拆分 |
| conflicts | list[dict] | [] | 冲突列表 |
| retired_goal_ids | list[str] | [] | 退休的目标 ID |
| domains | list[str] | [] | 领域列表 |

#### 业务概览拆分轴

| 轴 | 标签 | 领域 |
|----|------|------|
| revenue | 收入与增长 | revenue |
| cost | 成本与费用 | cost |
| risk | 风险与合规 | risk |
| growth | 增长与转化 | growth |

### Goal Lifecycle Binding

`bind_goal_graph_to_context(ctx, runtime_task)` — 将 GoalGraph 绑定到运行时上下文。

`finalize_turn_goal_lifecycle(graph, *, critic_passed, policy_denied, archive_terminal)` — 回合结束时关闭目标生命周期。

---

## 77. 治理中心详细架构

详见第 42 章。

---

## 78. 认知监督器（Cognitive Supervisor）

详见第 59 章。

---

## 79. 运行时网关（Runtime Gateway）

运行时网关负责查找运行时并调度执行。

---

## 80. 确定性认知控制（Cognitive Controls）

确定性认知控制包含：
- IntentLock — 意图锁定
- CognitiveBudget — 认知预算
- 相关性锚点检查

### CognitiveBudget

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| max_planning_depth | int | 1 | 最大规划深度 |
| max_capabilities | int | 1 | 最大能力数 |
| max_replans | int | 0 | 最大重规划次数 |
| max_memory_tokens | int | 0 | 最大记忆 token |
| max_context_expansion | int | 256 | 最大上下文扩展 |
| max_reasoning_steps | int | 2 | 最大推理步骤 |
| memory_injection | bool | False | 是否注入记忆 |
| workspace_context | bool | False | 是否使用工作空间上下文 |
| critic | bool | False | 是否启用批评 |

---

## 81. 能力链与能力运行时元数据

能力链定义能力间的依赖和组合关系。

---

## 82. 认知运行时状态（Cognitive Runtime State）

认知运行时状态跟踪当前请求的认知阶段和世界状态投影。

---

## 83. 多问题运行时 V2（Multi-Question Runtime V2）

### 模块路径
`kernel/cognition/multi_question.py`

### 多问检测

**`is_multi_question(query) → bool`**
- 多问号检测（≥2 个问号）
- 多问提示词检测（"第一个"、"另外"、"此外"等）
- 顺序词检测（"然后"、"接着"、"首先"等）

### 子问题领域分类

**`classify_sub_question_domain(text) → str`**

| 关键词 | 领域 |
|--------|------|
| 查询/统计/报表/销量/订单/数据库/sql/表/字段 | data_query |
| 文档/手册/知识库/总结/pdf/doc | document_retrieval |
| 最新/新闻/今天/实时/联网/搜索/weather | web_search |
| 时间/几点/天气/计算 | tool_execution |

### 分解方法

1. **语法分解** — 按问号、分号、逻辑连接词拆分
2. **LLM 分解** — 使用 PLANNING 角色 LLM 拆分

---

## 84. 上下文织物（Context Fabric）

### 模块路径
`kernel/context_fabric.py`

### ContextFabric

统一上下文组装门面。

#### FabricContext

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| summary_block | str | "" | 摘要块 |
| memory_block | str | "" | 记忆块 |
| attachment_block | str | "" | 附件块 |
| state_block | str | "" | 状态块 |
| recent_turns | list[dict] | [] | 最近轮次 |
| memory_injection_query | str | "" | 记忆注入查询 |
| total_tokens | int | 0 | 总 token 数 |
| compressed | bool | False | 是否已压缩 |
| metadata | dict | {} | 元数据 |

#### 方法

**`evolve_runtime(session_id, *, goal_id, runtime_phase, evidence_ref, memory_ref) → dict`**
**`get_session_graph(session_id) → dict`**
**`assemble(turn_context) → FabricContext`**

---

## 85. 记忆织物关系引擎（Memory Fabric）

### 模块路径
`kernel/runtime/memory_fabric.py`, `memory/fabric/memory_graph.py`

记忆织物维护记忆间的关系图谱，支持记忆的关联检索和演化。

---

## 86. 能力治理（Capability Governance）

能力治理确保能力执行符合策略和安全约束。

---

## 87. 结果引用系统（Result Reference）

结果引用系统维护执行结果与目标、证据间的绑定关系。

---

## 88. 企业多租户系统（Enterprise Tenant）

### 模块路径
`tenant/`

### 组件

| 模块 | 说明 |
|------|------|
| tenant_context.py | 租户上下文 |
| quota_manager.py | 配额管理 |
| billing_manager.py | 计费管理 |
| billing_runtime.py | 计费运行时 |

---

## 89. 企业控制平面（Enterprise Control Plane）

### 模块路径
`control_plane/control_plane.py`

企业控制平面提供集中化的策略管理和配置分发。

---

## 90. 合规运行时（Compliance Runtime）

合规运行时确保系统操作符合 SOC2 等合规框架。

---

## 91. 用量计量与成本归因（Usage Metering & Cost Attribution）

用量计量系统跟踪每次能力调用的资源消耗和成本。

---

## 92. 能力产品化与生命周期（CapabilityOS）

### 模块路径
`kernel/capability_runtime/capability_os.py`

### CapabilitySLA

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| success_rate | float | 1.0 | 成功率 |
| avg_latency_ms | float | 0.0 | 平均延迟 |
| cost_per_invocation | float | 0.0 | 每次调用成本 |
| confidence | float | 0.8 | 置信度 |
| availability | float | 1.0 | 可用性 |

**`degraded() → bool`** — success_rate < 0.85 或 availability < 0.9

### CapabilityProductState

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| capability_type | str | — | 能力类型 |
| lifecycle | str | "active" | 生命周期状态 |
| product_name | str | "" | 产品名称 |
| category | str | "general" | 分类 |
| sla | CapabilitySLA | — | SLA |

### CapabilityOS

能力操作系统 — 生命周期管理、SLA 指标、市场式产品。

#### 方法

**`set_lifecycle(capability_type, target) → bool`**
**`record_invocation(capability_type, *, success, latency_ms, cost) → None`**
**`get_product_state(capability_type) → CapabilityProductState | None`**
**`list_marketplace() → list[dict]`**

#### SLA 重算逻辑
- 维护最近 200 次调用记录
- 成功率 = 成功次数 / 总次数
- 平均延迟 = 总延迟 / 总次数
- 可用性 = 成功率
- 置信度 = min(0.99, 0.5 + success_rate × 0.5)
- 退化时自动将生命周期从 ACTIVE 降为 DEGRADED

---

## 93. 工作流引擎（Workflow Engine）

### 模块路径
`execution/workflow_engine/workflow.py`

声明式工作流定义与执行。

---

## 94. 认知迭代与反思重规划

### 模块路径
`kernel/runtime/cognitive_iteration.py`

### CognitiveIterationState

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| round | int | 0 | 当前迭代轮次 |
| max_rounds | int | 1 | 最大迭代轮次 |
| triggered | bool | False | 是否触发 |
| replan_reason | str | "" | 重规划原因 |
| history | list[dict] | [] | 迭代历史 |

### 触发条件

| 条件 | 原因 |
|------|------|
| critic.hallucination_risk ≥ 0.45 | critic_hallucination_risk |
| critic.factuality < 0.55 | critic_low_factuality |
| evidence_count ≤ min 且 fusion_confidence < 0.5 | insufficient_evidence |
| goals > 2 且 fusion_confidence < 0.6 | multi_goal_low_confidence |

### 最大迭代计算

```
max_iterations = max(1, min(kernel_cognitive_iteration_max, kernel_revise_max_iterations))
```

默认: max(1, min(2, 3)) = 2

---

## 95. 自优化运行时（Self-Optimizing Runtime）

### 模块路径
`kernel/runtime/self_optimizing_runtime.py`

### OptimizationHint

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| dimension | str | — | 优化维度 |
| action | str | — | 动作（tighten/relax/prefer/avoid） |
| delta | float | 0.0 | 变化量 |
| reason | str | "" | 原因 |
| capped | bool | False | 是否已封顶 |

### SelfOptimizationReport

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| hints | list[OptimizationHint] | [] | 优化提示 |
| applied | bool | False | 是否已应用 |
| session_id | str | "" | 会话 ID |

### 优化规则

| 条件 | 维度 | 动作 | delta |
|------|------|------|-------|
| drift > 0.55 或 risk > 0.65 | critic_threshold | tighten | +0.05 |
| replanned 且 round ≥ 2 | replan_budget | tighten | -1.0 (capped) |
| coverage < 0.4 | capability_preference | prefer | +0.1 |
| saturation > 0.7 | context_tokens | relax | -256 (capped) |

---

## 96. 运行时阶段与分派

### 模块路径
`kernel/runtime/runtime_turn_dispatcher.py`

运行时回合分派器，根据请求特征选择执行路径。

---

## 97. 能力注册表详细架构

能力注册表维护所有可用能力的元数据和执行代理映射。

---

## 98. 证据总线详细架构

### 模块路径
`kernel/runtime/evidence_bus.py`

### EvidenceBus

进程内证据发布/订阅总线，含生命周期管理。

#### 方法

| 方法 | 说明 |
|------|------|
| publish(evidence) → bool | 发布证据（幂等） |
| collect() → list[Evidence] | 非破坏性读取 |
| drain() → list[Evidence] | 读取并清空 |
| publish_results(results) → list[Evidence] | 将 AgentResult 转为 Evidence |
| rank_evidence(query) → list | 排序证据 |
| resolve(query) → list[str] | 解决冲突 |
| supersede(old_id, new_id, reason) | 取代证据 |
| archive_turn() | 归档本回合证据 |
| get_by_id(evidence_id) → Evidence \| None | 按 ID 获取 |
| get_usable() → list[Evidence] | 获取可用证据 |
| lifecycle_summary() → dict | 生命周期摘要 |
| reset() | 重置 |

---

## 99. 错误码与异常体系

### 模块路径
`infra/errors/error_codes.py`

统一错误码定义，包含错误类别、严重级别和描述。

---

## 100. 配置与特性开关完整表

### 关键配置项

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| kernel_runtime_replay_enabled | — | 运行时重放 |
| kernel_runtime_rewrite_enabled | — | 查询改写 |
| kernel_runtime_understanding_enabled | — | 深度理解 |
| kernel_context_compressor_enabled | — | 上下文压缩 |
| kernel_cognitive_planner_v2_enabled | True | V2 规划器 |
| kernel_runtime_capability_graph_enabled | — | 能力图 |
| kernel_runtime_artifact_composer_enabled | — | 制品合成 |
| kernel_runtime_workspace_enabled | — | 工作空间 |
| kernel_fusion_v2_enabled | False | V2 融合 |
| kernel_critic_v2_enabled | False | V2 批评 |
| kernel_v5_routing_enabled | — | V5 路由 |
| kernel_l0_rule_router_enabled | — | L0 规则路由 |
| kernel_l1_tiny_router_enabled | — | L1 路由 |
| kernel_semantic_cache_enabled | — | 语义缓存 |
| kernel_enriched_identity_enabled | — | 增强身份 |
| kernel_goal_supervisor_enabled | True | 目标监督 |
| kernel_refine_replan_enabled | True | 有界重规划 |
| kernel_refine_reexec_enabled | True | 重规划后重执行 |
| kernel_cognitive_iteration_enabled | True | 认知迭代 |
| kernel_self_optimizing_runtime_enabled | True | 自优化运行时 |
| kernel_self_optimizing_runtime_apply | False | 自优化应用 |
| kernel_governance_evidence_gate_enabled | True | 证据门控 |
| kernel_governance_risk_gate_enabled | True | 风险门控 |
| kernel_evidence_contract_strict | False | 证据契约严格模式 |
| kernel_capability_contract_strict | False | 能力契约严格模式 |
| kernel_policy_mutation_fail_closed | False | 策略变更失败关闭 |
| kernel_runtime_phase_transition_strict | False | 阶段转移严格 |
| kernel_agent_capability_executor_mode | — | 能力执行器模式 |
| kernel_sandbox_enabled | False | 沙箱 |
| kernel_world_state_persist_enabled | False | 世界状态持久化 |

---

## 101. 认知事件总线

### 模块路径
`infra/message_bus/cognitive_event_bus.py`

进程内认知事件发布/订阅总线，用于模块间异步通信。

---

## 102. Feature Flag Governance

### 模块路径
`infra/config/flag_governance.py`

Feature Flag 治理系统，管理特性开关的生命周期和生效范围。

---

## 103. 语义缓存

### 模块路径
`kernel/semantic_cache.py`

### SemanticCache

基于嵌入的语义答案缓存。

#### 配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| cache_dir | .cache/ | 缓存目录 |
| threshold | 0.92 | 相似度阈值 |
| max_entries | 10000 | 最大条目数 |
| ttl_seconds | 3600 | TTL（1小时） |

#### CacheEntry

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| answer | str \| None | None | 缓存答案 |
| content | str \| None | None | 缓存内容 |
| hit_count | int | 0 | 命中次数 |
| similarity | float | 0.0 | 相似度 |
| key | str | "" | 缓存键 |

#### 方法

**`lookup(query, ctx_hash) → CacheEntry | None`**
- 计算查询嵌入
- 按余弦相似度查找最佳匹配
- 相似度 ≥ threshold 时命中

**`store(query, content, ctx_hash) → None`**
- 计算查询嵌入
- 去重更新或新增
- LRU 淘汰

#### 余弦相似度公式

```
cosine_similarity(a, b) = dot(a, b) / (||a|| × ||b||)
```

---

## 104. NER PII Masker

### 模块路径
`safety/masking/ner_masker.py`

命名实体识别脱敏器，检测并遮蔽个人身份信息。

---

## 105. Safety Guardrails

### 模块路径
`safety/guardrails/guardrails.py`

安全护栏系统，在输入和输出层面实施安全检查。

---

## 106. Safety Policy Engine

### 模块路径
`safety/policy_engine/engine.py`

安全策略引擎，定义和执行安全规则。

---

## 107. Cognitive Trace

### 模块路径
`safety/xai/cognitive_trace.py`

认知追踪系统，提供可解释性支持。

---

## 108. Sandbox Providers

### 模块路径
`sandbox_runtime/executor.py`

沙箱执行器，提供安全的代码执行环境。

---

## 109. Connector Protocol

### 模块路径
`connectors/sdk/protocol.py`

连接器协议，定义外部系统集成的标准接口。

---

## 110. Data Flywheel

### 模块路径
`evolution/data_flywheel/flywheel.py`

数据飞轮系统，从执行结果中提取训练数据，持续改进模型。

---

## 111. Evaluation Engine

### 模块路径
`evolution/evaluation/engine.py`

评估引擎，对系统输出进行自动化评估。

---

## 112. Learning Engine

### 模块路径
`evolution/learning/learning.py`

学习引擎，从执行历史中学习优化策略。

---

## 113. Meta-Learner

### 模块路径
`evolution/meta_learning/meta_learner.py`

元学习器，学习如何学习，优化学习策略本身。

---

## 114. Self-Play

### 模块路径
`evolution/self_play/self_play.py`

自博弈系统，通过自我对弈发现和修复系统弱点。

---

## 115. Capability Profiler 5D Scoring

能力画像器的五维评分体系：

1. **语义适配度** (0.30) — 文本匹配质量
2. **历史成功率** (0.25) — 历史执行成功率
3. **上下文兼容性** (0.20) — 是否契合当前上下文
4. **预算适配度** (0.15) — 延迟/成本是否在预算内
5. **风险适配度** (0.10) — 可靠性是否满足风险容忍度

---

## 116. Capability Knowledge Graph

能力知识图谱，维护能力间的依赖、互补和替代关系。

---

## 117. Capability Reasoner

详见第 23 章。

---

## 118. Execution/Strategy/Failure Memory

### Execution Memory
记录每次能力执行的详细结果，支持退化检测。

### Strategy Memory
记录策略执行结果，推荐最优策略。

### Failure Memory
记录失败事件，支持快速失败检测和替代推荐。

---

## 119. Runtime Contract

### 模块路径
`kernel/protocol/runtime_contract.py`

### Goal

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| goal_id | str | — | 目标 ID |
| description | str | — | 描述 |
| priority | int | 0 | 优先级 |
| parent_id | str \| None | None | 父目标 ID |
| success_criteria | str | "" | 成功标准 |
| metadata | dict | {} | 元数据 |

### GoalGraph

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| root_goal_id | str | — | 根目标 ID |
| goals | list[Goal] | [] | 目标列表 |
| intent_category | str | "general" | 意图类别 |
| protected_intent | str | "" | 受保护意图 |

### Constraints

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| allowed_capabilities | list[str] | [] | 允许的能力 |
| disallowed_capabilities | list[str] | [] | 禁止的能力 |
| max_parallel | int | 5 | 最大并行数 |
| max_depth | int | 3 | 最大深度 |
| relevance_threshold | float | 0.35 | 相关性阈值 |
| metadata | dict | {} | 元数据 |

### Budget

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| max_tokens | int | 10000 | 最大 token |
| max_steps | int | 10 | 最大步骤 |
| max_llm_calls | int | 5 | 最大 LLM 调用 |
| max_time_seconds | float | 60.0 | 最大时间 |
| max_replans | int | 1 | 最大重规划 |

### EvidencePolicy

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| min_evidence_count | int | 0 | 最小证据数 |
| require_citations | bool | False | 是否需要引用 |
| rank_before_fusion | bool | True | 融合前排序 |
| resolve_contradictions | bool | True | 解决矛盾 |

### ExecutionPolicy

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| capability_executor_mode | bool | False | 能力执行器模式 |
| timeout_sec | int | 30 | 超时 |
| sandbox_required | bool | False | 需要沙箱 |
| fallback_to_direct_answer | bool | True | 降级到直接回答 |

### RuntimeTask

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| id | str | — | 任务 ID |
| goal | Goal | — | 目标 |
| goal_graph | GoalGraph \| None | None | 目标图 |
| constraints | Constraints | Constraints() | 约束 |
| capabilities | list[CapabilityRef] | [] | 能力引用 |
| budget | Budget | Budget() | 预算 |
| context | RuntimeContextRef | — | 上下文引用 |
| evidence_policy | EvidencePolicy | EvidencePolicy() | 证据策略 |
| execution_policy | ExecutionPolicy | ExecutionPolicy() | 执行策略 |
| query | str | "" | 查询 |

### RuntimeArtifact

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| artifact_id | str | — | 制品 ID |
| evidence | list | [] | 证据 |
| execution_trace | ExecutionTrace | — | 执行追踪 |
| confidence | float | 0.0 | 置信度 |
| provenance | Provenance | — | 来源 |
| state | ArtifactState | DRAFT | 状态 |
| content | str | "" | 内容 |
| goal_evidence_binding | GoalEvidenceBinding \| None | None | 目标证据绑定 |
| metadata | dict | {} | 元数据 |

---

## 120. Capability Execution Contract

### 模块路径
`kernel/capability_runtime/contract.py`

### CapabilityExecutionContract

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| capability_type | str | — | 能力类型 |
| max_latency_ms | float | 60000.0 | 最大延迟 |
| requires_sandbox | bool | False | 需要沙箱 |
| allowed_environments | list[str] | ["default"] | 允许的环境 |
| min_success_rate | float | 0.0 | 最低成功率 |
| risk_tier | str | "low" | 风险等级 |
| cost_units | float | 1.0 | 成本单位 |
| dependencies | list[str] | [] | 依赖 |
| owner_runtime | str | "cognitive_executive" | 所属运行时 |
| tier | str | "standard" | 层级 |

### 预定义契约

| capability_type | max_latency_ms | requires_sandbox |
|----------------|---------------|-----------------|
| data_query | 120000.0 | False |
| web_search | 45000.0 | False |

---

## 121. Capability Lifecycle

### 模块路径
`kernel/capability_runtime/lifecycle.py`

### CapabilityLifecycleState 枚举

| 值 | 说明 |
|----|------|
| DRAFT | 草稿 |
| ACTIVE | 活跃 |
| DEGRADED | 退化 |
| DEPRECATED | 已弃用 |
| RETIRED | 已退休 |

### 转换规则

单向递进：DRAFT → ACTIVE → DEGRADED → DEPRECATED → RETIRED

---

## 122. Adaptive Risk Engine

### 模块路径
`kernel/governance/adaptive_risk_engine.py`

### AdaptiveRiskScore

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| level | str | "low" | 风险级别 |
| score | float | 0.0 | 风险分数 |
| factors | list[str] | [] | 风险因子 |

### 评分公式

```
score = hallucination_risk × 0.5
      + (0.15 if replanned)
      + (0.2 if evidence_count == 0 and sub_goal_count > 0)
      + (0.1 if sub_goal_count > 4)
```

### 风险级别

| score | level |
|-------|-------|
| ≥ 0.6 | high |
| ≥ 0.35 | medium |
| < 0.35 | low |

---

## 123. Confidence Decay

### 模块路径
`kernel/runtime/memory/confidence_decay.py`

### ConfidenceDecayPolicy

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| memory_type | str | "fact" | 记忆类型 |
| half_life_hours | float | 720.0 | 半衰期（小时） |
| min_confidence | float | 0.1 | 最低置信度 |
| archive_threshold | float | 0.15 | 归档阈值 |
| contradiction_penalty | float | 0.3 | 矛盾惩罚乘数 |
| atrophy_rate | float | 0.001 | 萎缩率（每天） |
| boost_on_access | float | 0.05 | 访问提升 |

### 衰减公式

```
decay_factor = exp(-ln(2) × age_hours / half_life)
decayed_confidence = original_confidence × decay_factor
                   - atrophy_rate × unused_days
                   + boost_on_access × ln(access_count + 1)
```

### 默认半衰期

| 记忆类型 | 半衰期 |
|---------|--------|
| fact | 720h (30天) |
| preference | 1440h (60天) |
| episodic | 168h (7天) |
| semantic | 2160h (90天) |
| procedural | 4320h (180天) |
| conversation | 24h (1天) |

---

## 124. Fact Supersession

### 模块路径
`kernel/runtime/memory/fact_supersession.py`

### SupersessionRecord

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| superseded_id | str | "" | 被取代的 ID |
| superseding_id | str | "" | 取代的 ID |
| reason | str | "" | 原因 |
| source | str | "" | 来源 |
| timestamp | str | now() | 时间戳 |
| metadata | dict | {} | 元数据 |

### FactSupersessionEngine

管理事实的完整生命周期 — 创建、更新、取代。

#### 核心原则
- 事实从不删除，只被取代
- 维护完整谱系链用于审计和回放

#### 方法

**`register_fact(entity_key, memory_id)`** — 注册新事实
**`supersede(entity_key, old_memory_id, new_memory_id, reason, source) → SupersessionRecord`** — 取代旧事实
**`is_superseded(memory_id) → bool`** — 检查是否被取代
**`get_superseding(memory_id) → str | None`** — 获取取代者
**`get_lineage(memory_id) → list[str]`** — 获取谱系链
**`get_latest(entity_key) → str | None`** — 获取最新事实
**`get_history(entity_key) → list[SupersessionRecord]`** — 获取取代历史

---

*本文档涵盖 OpenTrace 项目的全部核心模块、数据结构、算法公式和集成点。所有内容均从源码直接分析，作为项目唯一权威技术参考。*
