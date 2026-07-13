# OpenTrace 项目文档重写计划

## 背景

当前 `docs/service/service_trae.md` Part I（Ch 1-3）已完成约 690 行，涵盖了项目概述、核心设计原则和系统架构。需要继续完成 Part II-VIII（Ch 4-55 + 附录），目标总计 8000-10000+ 行。

## 核心改进方向

1. 从扁平章节结构改为 8 个逻辑 Part + 55 个 Chapter 的层次结构
2. 新增完整 API 端点文档（25+ 路由器的请求/响应 schema）
3. 新增大量源码级代码片段和类签名
4. 新增详细数据流图
5. 新增完整配置参考（100+ Feature Flag）
6. 新增开发者指南、故障排查、部署指南

## 已完成

- **Part I: 介绍与概述（Ch 1-3）** ✅ — 690 行，包含项目概述、核心设计原则、系统架构

## 待实施任务

### Task 1: Part II: API 网关（Ch 4-11）~1500 行

**Ch 4: 网关架构** (~150 行)
- 源文件: `gateway/api_gateway/main.py`
- FastAPI 应用初始化、中间件栈（CORS → TenantContext → RequestContext）
- 全局异常处理（AppException → error envelope）
- 25+ 路由器注册方式、lifespan 管理

**Ch 5: 认证 API** (~180 行)
- 源文件: `gateway/api_gateway/routers/auth.py`
- Endpoints: POST /register, POST /login, POST /token, GET /me
- JWT Bearer Token 配置、OAuth2PasswordBearer
- 密码哈希（passlib[bcrypt]）、Token 刷新机制

**Ch 6: Chat API** (~300 行)
- 源文件: `gateway/api_gateway/routers/chat.py`（2628 行核心文件）
- SSE 流式响应：delta → final_answer → reasoning_step → execution_graph → error
- ChatRequest/ChatResponse schema、附件解析、分支管理
- 预检流程：认证 → 风险评估 → 附件解析 → 上下文加载
- 与 CognitiveKernel 的交互接口

**Ch 7: Conversations API** (~150 行)
- 源文件: `gateway/api_gateway/routers/conversations.py`
- CRUD 操作、归档/取消归档、分支管理
- 消息历史分页查询

**Ch 8: Data & Database API** (~200 行)
- 源文件: `gateway/api_gateway/routers/data.py`, `routers/databases.py`
- Text2SQL 端点、Schema 同步、连通性测试
- 表关系维护端点（`routers/table_relationships.py`）

**Ch 9: Documents API** (~120 行)
- 源文件: `gateway/api_gateway/routers/documents.py`
- 文档上传/下载/删除、向量检索、分块策略

**Ch 10: Knowledge API** (~120 行)
- 源文件: `gateway/api_gateway/routers/knowledge.py`
- 知识源管理、规则编译、知识演化

**Ch 11: 其他 API** (~280 行)
- Memories (`routers/memories.py`), Tasks (`routers/tasks.py`)
- Skills (`routers/skills.py`), Analytical Skills (`routers/analytical_skills.py`)
- Rules (`routers/rules.py`), Metrics (`routers/metrics.py`)
- Sandbox (`routers/sandbox.py`), Admin (`routers/admin.py`)
- Enterprise Admin (`routers/enterprise_admin.py`), Feedback (`routers/feedback.py`)
- Audit (`routers/audit.py`), Connectors (`routers/connectors.py`)
- Cognitive (`routers/cognitive.py`), Health (`routers/health.py`)
- Prometheus (`routers/prometheus.py`), Personalization (`routers/personalization.py`)
- Responses V2 (`routers/responses.py`), UI Settings (`routers/ui_settings.py`)

### Task 2: Part III: 认知内核（Ch 12-20）~1800 行

**Ch 12: 内核架构** (~200 行)
- 源文件: `kernel/cognitive_kernel.py`（875 行）
- CognitiveKernel.run() 完整流程
- 多 Prompt 链执行流：意图识别 → 规划 → 工具选择 → 并行执行 → 推理 → 反思 → 元认知 → 记忆存储
- 与 RuntimeGateway 的委托关系

**Ch 13: V5 分层路由** (~200 行)
- 源文件: `kernel/query_router_v2.py`, `kernel/tiny_router.py`, `kernel/semantic_cache.py`, `kernel/fast_tool_path.py`
- L0 规则路由：关键词/模式匹配
- 语义缓存：向量相似度匹配加速
- L1 TinyRouter：轻量级 LLM 分类 (qwen3-1.7b)
- 工具快速路径：weather/time/tool 绕过完整管线

**Ch 14: CognitiveExecutive** (~300 行)
- 源文件: `kernel/runtime/cognitive_executive.py`（1560 行）
- 12+ 阶段完整走查：IntentLock → Rewrite → Understand → Policy → Plan → Constraint → Execute → Evidence → Rank → Fuse → Critic → Iteration → Artifact → Archive
- 每阶段的输入/输出/LLM 角色
- RuntimeContext 在阶段间的传递

**Ch 15: 改写与理解引擎** (~200 行)
- 源文件: `kernel/runtime/rewrite_engine.py`, `kernel/runtime/understanding_engine.py`, `kernel/runtime/cognitive/cognitive_planner_v2.py`
- RewriteEngine：查询改写策略（HyDE、分解、消歧）
- UnderstandingEngine：深度语义理解、实体识别
- CognitivePlannerV2：策略构建 → 认知图 → 执行投影

**Ch 16: 约束层** (~180 行)
- 源文件: `kernel/runtime/constraint_layer.py`（361 行）
- 五项确定性检查：预算约束、策略合规、风险评估、能力可用性、历史先验
- PlannerConstraintLayer.evaluate() 完整流程
- 不调用 LLM，纯规则 + 查表

**Ch 17: 证据总线** (~200 行)
- 源文件: `kernel/runtime/evidence_bus.py`（318 行）, `kernel/runtime/evidence/`
- 生命周期状态机：CREATED → VALIDATED → RANKED → MERGED → ARCHIVED
- EvidenceBus.publish_results() 流程
- 多维度排序：相关性、新鲜度、权威性、一致性
- 冲突解决：版本向量、LWW（Last-Writer-Wins）

**Ch 18: 融合与审校引擎** (~200 行)
- 源文件: `kernel/runtime/fusion.py`（281 行）, `kernel/runtime/critic.py`（204 行）, `kernel/runtime/artifact_composer.py`
- FusionEngineV2：LLM 驱动语义融合，简单查询走启发式快速路径
- CriticEngineV2：结构化评估（factuality、completeness、evidence_coverage、hallucination_risk）
- ArtifactComposer：最终制品合成

**Ch 19: 工作空间与记忆织物** (~180 行)
- 源文件: `kernel/runtime/workspace.py`, `kernel/runtime/finalize_turn.py`, `kernel/runtime/memory/`
- Workspace：运行时工作区隔离
- 记忆织物：TMS（真值维护系统）、置信度衰减、事实取代
- 回合收尾：记忆写入、缓存更新、世界模型终结、计费

**Ch 20: 运行时回合分派器** (~140 行)
- 源文件: `kernel/runtime_gateway.py`（165 行）, `kernel/runtime/runtime_turn_dispatcher.py`, `kernel/runtime/registry.py`, `kernel/runtime/registry_governance.py`
- RuntimeGateway：瘦路由层，委托 CognitiveSupervisor
- RuntimeTurnDispatcher：按 runtime_type 分派（cognitive_executive | data_intelligence | multi_goal）
- 注册表治理：服务间访问控制

### Task 3: Part IV: 智能体系统（Ch 21-25）~1200 行

**Ch 21: Agent 架构** (~200 行)
- 源文件: `agents/base.py`, `agents/bootstrap.py`, `agents/registry.py`, `kernel/agent_runtime/`
- BaseAgent：抽象基类，execute(task) → AgentResult
- TaskMessage / AgentResult 结构
- bootstrap.py：内置 Agent 工厂注册
- Agent Topology Manifest（YAML）：tier0_kernel / tier1_executive / tier1_data / tier2_nodes
- AgentRuntimeExecutor：Tier-1 Capability 统一门面

**Ch 22: DataAgent V2** (~300 行)
- 源文件: `agents/data_agent_v2/`（25+ 子代理）
- 五层认知管线：知识层 → 推理层 → 规划层 → 验证层 → 学习层
- supervisor.py：任务分解与调度
- error_classifier.py：错误分类与恢复
- 核心子代理：knowledge_retriever, planner_agent, sql_compiler_agent, verification_agent, reflection_agent, insight_agent, statistical_agent

**Ch 23: RAGAgent** (~250 行)
- 源文件: `agents/rag_agent.py`（1156 行）
- 混合检索：向量检索 + 关键词检索 + RRF 融合
- 证据质量控制：相关性评分、Rerank（BAAI/bge-reranker-v2-m3）
- LLMWiki 查询、记忆检索集成

**Ch 24: WebAgent & WebIntelligence** (~200 行)
- 源文件: `agents/web_agent.py`, `agents/web_intelligence_agent.py`
- WebAgent：搜索 + 抓取 + 结构化格式化
- WebIntelligenceAgent：证据排名、信任评估、声明图生成
- 覆盖评估器

**Ch 25: 其他 Agent** (~250 行)
- ToolAgent (`agents/tool_agent.py`)：天气、时间、计算器
- VisionAgent (`agents/vision_agent.py`)：Qwen3-VL 图像理解
- SkillsAgent (`agents/skills_agent.py`)：技能执行
- CognitiveAgent (`agents/cognitive_agent.py`)：认知工作流基类
- RulesAgent (`agents/rule_engine_agent.py`)：规则触发与事件响应
- Worker (`agents/worker.py`)：Agent Worker

### Task 4: Part V: 认知子系统（Ch 26-35）~1800 行

**Ch 26: 目标系统** (~200 行)
- 源文件: `kernel/goal/goal_supervisor.py`, `goal_driven_planner.py`, `goal_lifecycle.py`, `goal_progress.py`, `goal_recovery.py`, `multi_goal_resources.py`, `multi_goal_scheduler.py`
- GoalGraph 结构：root_goal_id → goals[] → subgoals
- GoalSupervisor：任务查询识别、目标合并、冲突检测
- 目标驱动规划器：GoalGraph → ExecutionPlan 投影
- 生命周期：ACTIVE → IN_PROGRESS → COMPLETED → ARCHIVED

**Ch 27: 治理中心** (~200 行)
- 源文件: `kernel/governance/governance_center.py`, `risk_governor.py`, `evidence_governor.py`, `policy_governor.py`, `memory_governor.py`, `capability_governor.py`, `adaptive_risk_engine.py`
- GovernanceCenter：统一治理入口
- 五层治理器：风险、证据、策略、记忆、能力
- AdaptiveRiskEngine：自适应风险评估

**Ch 28: 认知监督器** (~180 行)
- 源文件: `kernel/cognitive_supervisor/supervisor.py`（331 行）, `prepare_dispatch.py`, `dispatch_enrichment.py`, `control_plane_gate.py`, `run_outcomes.py`
- CognitiveSupervisor.prepare_run：GoalGraph 构建、治理评估、策略记忆加载
- 控制平面门控：预检、配额
- RuntimeContext 构建（40+ 字段）
- 世界状态注入、上下文织物种子

**Ch 29: 上下文系统** (~180 行)
- 源文件: `kernel/context_fabric.py`, `kernel/runtime/context.py`
- RuntimeContext：40+ 结构化字段
- ContextFabric：统一上下文组装，替代分散的上下文处理
- 上下文装配器、图谱演化

**Ch 30: 对话状态与多轮** (~160 行)
- 源文件: `kernel/conversation_state.py`（346 行）, `kernel/turn_enrichment.py`（396 行）, `kernel/clarification_gate.py`, `kernel/multi_turn_resolution.py`, `kernel/history_retriever.py`
- ConversationState：结构化持久会话状态（主题、意图、约束）
- 回合增强：多轮对话、偏好注入、记忆处理、上下文织网装配
- 澄清门控：需要澄清时触发

**Ch 31: 能力智能** (~200 行)
- 源文件: `kernel/capability_intelligence/`
- 5D 能力画像：profiler.py
- 能力推理器：reasoner.py（知识图谱拓扑 + 画像匹配 + 执行历史）
- 能力知识图谱：knowledge_graph.py
- 执行记忆：execution_memory.py
- 策略记忆：strategy_memory.py
- 失败记忆：failure_memory.py
- 能力演化引擎：evolution.py

**Ch 32: 记忆系统** (~200 行)
- 源文件: `memory/` 全部模块
- 工作记忆：WorkingMemory（环形缓冲区，Redis 持久化，24h TTL）
- 情景记忆：EpisodicMemory（Redis 列表，会话事件）
- 语义记忆：SemanticMemory（pgvector，余弦相似度）
- 程序记忆：ProceduralMemory（Redis Hash，可重用过程模板）
- 时间记忆：TemporalMemoryIndex（指数衰减评分）
- 记忆路由：MemoryRouter（语义搜索 + 图搜索 + 事件检索 + 关键词检索）
- 记忆织物：MemoryGraphStore（节点/边操作，图快照）
- 记忆进化：MemoryEvolution（模式抽象、技能生成）

**Ch 33: 世界模型与认知** (~120 行)
- 源文件: `kernel/cognition/world_model.py`（267 行）, `predictive_world.py`, `runtime_grounding.py`
- WorldModel：语义接地与消歧，实体注册、时间短语处理
- PredictiveWorld：预测世界状态
- RuntimeGrounding：运行时接地

**Ch 34: 协议与契约系统** (~100 行)
- 源文件: `kernel/protocol/runtime_contract.py`, `cognition_protocol.py`, `agent_protocol.py`
- RuntimeContract：GoalGraph、Constraint、Capability 等类型定义
- CognitionProtocol：认知协议
- AgentProtocol：智能体协议

**Ch 35: 其他认知子系统** (~260 行)
- 元认知：`kernel/meta_cognition/meta_cognition.py`（181 行）— 三层质量控制（接受/精炼/重试）
- 意图引擎：`kernel/intent_engine/engine.py`（155 行）— 结构化意图解析
- 推理引擎：`kernel/reasoning/engine.py` — 高层逻辑推理
- 认识论：`kernel/epistemology/` — 知识验证
- 策略引擎：`kernel/policy/` — 策略执行
- Prompt 引擎：`kernel/prompt_engine/` — Prompt 管理
- 系统身份：`kernel/identity/system_identity.py` — 身份响应管理

### Task 5: Part VI: 安全与防护（Ch 36-38）~500 行

**Ch 36: 安全架构** (~180 行)
- 源文件: `infra/security/zero_trust.py`
- 零信任模型：最小权限、持续验证
- 查询风险评估
- 权限 Token 管理
- 工具异常检测

**Ch 37: PII 脱敏与护栏** (~180 行)
- 源文件: `safety/masking/ner_masker.py`（153 行）, `safety/guardrails/guardrails.py`（131 行）, `safety/policy_engine/engine.py`（107 行）
- NER Masker：命名实体识别与脱敏（人名、组织、日期）
- Guardrails：基于上下文的规则控制
- SafetyPolicyEngine：安全策略决策流程

**Ch 38: 沙箱运行时** (~140 行)
- 源文件: `plugins/code/interpreter.py`, `plugins/file/sandbox.py`
- 代码解释器 AST 守卫
- 文件沙箱：隔离文件系统
- gVisor/Firecracker MicroVM 支持

### Task 6: Part VII: 基础设施与运维（Ch 39-50）~1600 行

**Ch 39: 数据库与存储** (~180 行)
- 源文件: `infra/storage/database.py`, `infra/storage/models.py`
- PostgreSQL 16 + pgvector 配置
- SQLAlchemy 2.0 async 引擎与会话
- Alembic 数据库迁移

**Ch 40: Redis 与缓存** (~150 行)
- 源文件: `infra/cache/redis_client.py`, `infra/cache/redis_shadow_store.py`
- 6-DB 分区架构：session/cache/memory/queue/pubsub/ratelimit
- 语义缓存：`kernel/semantic_cache.py`
- ShadowRedis：影子缓存

**Ch 41: 消息总线与事件** (~120 行)
- 源文件: `infra/message_bus/agent_bus.py`, `infra/message_bus/`
- Agent Bus：Redis Stream/PubSub 分布式调度
- Celery + RabbitMQ 任务队列
- CognitiveEventBus：认知事件流

**Ch 42: 可观测性** (~150 行)
- 源文件: `infra/observability/tracer.py`, `infra/observability/logger.py`
- structlog：结构化日志
- OpenTelemetry：分布式追踪
- Prometheus：指标导出
- Cognitive Trace：认知追踪

**Ch 43: 企业多租户** (~160 行)
- 源文件: `tenant/tenant_manager.py`, `quota_manager.py`, `billing_manager.py`, `usage_metering.py`, `workspace_manager.py`
- 租户隔离：数据库级别 + RLS
- 配额管理：Token/请求/存储 配额
- 计费管理：用量计量、计费周期
- 工作空间管理

**Ch 44: 模型网关与 LLM 适配器** (~200 行)
- 源文件: `model/model_gateway/gateway.py`, `model/llm_adapter/`
- 9 角色路由：QUERY/COMPRESS/PLANNING/ROUTER/FAST/CHEAP_CRITIC/KNOWLEDGE/IDENTITY/VISION
- CircuitBreaker：三态熔断器（closed → open → half-open）
- 离线降级：`_offline_fallback_response()` 多角色覆盖
- OpenAICompatibleAdapter

**Ch 45: 数据认知层** (~120 行)
- 源文件: `kernel/data_cognition/semantic_layer.py`, `sql_planner.py`, `sql_builder.py`, `sql_validator.py`
- SemanticLayer：语义层抽象
- SQLPlanner：SQL 规划
- 多方言支持：PostgreSQL / MySQL / ClickHouse

**Ch 46: 插件系统** (~100 行)
- 源文件: `plugins/` 全部模块
- 插件基类：文档/Web/工具/知识/记忆/代码/图表/文件/数据插件
- 代码解释器、图表生成器、文件沙箱、数据分析

**Ch 47: 技能/规则/工具** (~120 行)
- 源文件: `skills/`, `kernel/tools/`
- Skills Marketplace：技能市场
- Skill Runtime：技能加载与执行
- Rule Engine：规则引擎
- Built-in Tools：内置工具集

**Ch 48: 连接器与 SDK** (~100 行)
- 源文件: `connectors/registry.py`, `connectors/sdk/protocol.py`
- OAuth 协议支持
- 内置连接器注册
- SDK 协议

**Ch 49: 演化与学习** (~100 行)
- 源文件: `kernel/runtime/self_optimizing_runtime.py`, `memory/evolution/evolution.py`
- Data Flywheel：数据飞轮
- Evaluation/Learning Engine
- Meta-Learner、Self-Play

**Ch 50: 确定性重放与审计** (~100 行)
- 源文件: `kernel/runtime/replay/runtime_snapshot.py`, `execution_replay.py`
- Prompt/运行时快照
- 执行重放
- 合规运行时

### Task 7: Part VIII: 运维与开发（Ch 51-55 + 附录）~1200 行

**Ch 51: 配置参考** (~300 行)
- 源文件: `infra/config/settings.py`（32825 行）
- 完整 settings.py 配置项参考
- 100+ Feature Flag 分类说明
- 环境变量映射表

**Ch 52: 部署指南** (~200 行)
- 源文件: `docker-compose.yml`, `Dockerfile`, `start.sh`, `.env.example`
- Docker Compose 4 服务部署
- 生产环境配置
- Nginx 反向代理
- 扩缩容策略

**Ch 53: 开发者指南** (~200 行)
- 环境搭建：Python 3.11+, Poetry, Docker
- 代码规范：black/ruff/mypy/pre-commit
- 架构约束：模块间禁止直接 import，仅通过 RuntimeContext 通信
- 新增端点/Agent/Flag 教程

**Ch 54: 测试策略** (~150 行)
- 测试层次：单元测试 / 集成测试 / 端到端测试
- 关键测试文件
- pytest + pytest-asyncio + pytest-cov
- 编写测试的规范

**Ch 55: 故障排查** (~150 行)
- 常见问题与解决方案
- 调试认知管线
- 性能调优建议
- 错误码参考

**附录** (~200 行)
- 附录 A: 完整 API 端点参考表（25+ 路由器，100+ 端点）
- 附录 B: 错误码参考
- 附录 C: 术语表
- 附录 D: ADR 索引

## 关键源文件（完整列表）

### API 网关
- `gateway/api_gateway/main.py` — FastAPI 应用入口
- `gateway/api_gateway/routers/chat.py` — 核心 Chat API（2628 行）
- `gateway/api_gateway/routers/auth.py` — 认证
- `gateway/api_gateway/routers/conversations.py` — 会话管理
- `gateway/api_gateway/routers/data.py` — 数据查询
- `gateway/api_gateway/routers/databases.py` — 数据库连接
- `gateway/api_gateway/routers/documents.py` — 文档管理
- `gateway/api_gateway/routers/knowledge.py` — 知识库
- `gateway/api_gateway/routers/memories.py` — 记忆管理
- `gateway/api_gateway/routers/tasks.py` — 任务管理
- `gateway/api_gateway/routers/skills.py` — 技能管理
- `gateway/api_gateway/routers/admin.py` — 管理员
- `gateway/api_gateway/routers/enterprise_admin.py` — 企业管理
- `gateway/api_gateway/routers/audit.py` — 审计
- `gateway/api_gateway/routers/cognitive.py` — 认知事件
- `gateway/api_gateway/routers/health.py` — 健康检查
- `gateway/api_gateway/routers/prometheus.py` — Prometheus
- `gateway/api_gateway/routers/sandbox.py` — 沙箱
- `gateway/api_gateway/routers/feedback.py` — 反馈
- `gateway/api_gateway/routers/connectors.py` — 连接器
- `gateway/api_gateway/routers/analytical_skills.py` — 分析技能
- `gateway/api_gateway/routers/metrics.py` — 指标
- `gateway/api_gateway/routers/rules.py` — 规则
- `gateway/api_gateway/routers/personalization.py` — 个性化
- `gateway/api_gateway/routers/responses.py` — V2 响应
- `gateway/api_gateway/routers/table_relationships.py` — 表关系
- `gateway/api_gateway/routers/ui_settings.py` — UI 设置

### 认知内核
- `kernel/cognitive_kernel.py` — 内核入口（875 行）
- `kernel/runtime_gateway.py` — 运行时网关（165 行）
- `kernel/runtime/cognitive_executive.py` — 认知执行器（1560 行）
- `kernel/runtime/context.py` — RuntimeContext（145 行）
- `kernel/runtime/evidence_bus.py` — 证据总线（318 行）
- `kernel/runtime/fusion.py` — 融合引擎（281 行）
- `kernel/runtime/critic.py` — 审校引擎（204 行）
- `kernel/runtime/constraint_layer.py` — 约束层（361 行）
- `kernel/runtime/rewrite_engine.py` — 改写引擎
- `kernel/runtime/understanding_engine.py` — 理解引擎
- `kernel/runtime/workspace.py` — 工作空间
- `kernel/runtime/artifact_composer.py` — 制品合成
- `kernel/runtime/cognitive_iteration.py` — 认知迭代
- `kernel/runtime/self_optimizing_runtime.py` — 自优化
- `kernel/runtime/finalize_turn.py` — 回合终结
- `kernel/runtime/runtime_turn_dispatcher.py` — 回合分派器
- `kernel/runtime/registry.py` — 注册表
- `kernel/runtime/registry_governance.py` — 注册表治理
- `kernel/query_router_v2.py` — L0 规则路由
- `kernel/tiny_router.py` — L1 TinyRouter
- `kernel/semantic_cache.py` — 语义缓存
- `kernel/fast_tool_path.py` — 工具快速路径
- `kernel/context_fabric.py` — 上下文织物
- `kernel/conversation_state.py` — 对话状态
- `kernel/turn_enrichment.py` — 回合增强
- `kernel/clarification_gate.py` — 澄清门控
- `kernel/multi_turn_resolution.py` — 多轮解析
- `kernel/history_retriever.py` — 历史检索
- `kernel/refine_planner.py` — 重规划
- `kernel/cognitive_controls.py` — 认知控制
- `kernel/plan_agent.py` — 规划智能体
- `kernel/plan_memory.py` — 规划记忆
- `kernel/dag_plan.py` — DAG 计划
- `kernel/dag_scheduler.py` — DAG 调度器
- `kernel/dispatcher.py` — 分派器
- `kernel/token_counter.py` — Token 计数器
- `kernel/result_reference.py` — 结果引用
- `kernel/adaptive_profiles.py` — 自适应画像
- `kernel/types.py` — 基础类型

### 目标/治理/监督
- `kernel/goal/goal_supervisor.py` — 目标监督器
- `kernel/goal/goal_driven_planner.py` — 目标驱动规划器
- `kernel/goal/goal_lifecycle.py` — 目标生命周期
- `kernel/goal/goal_progress.py` — 目标进度
- `kernel/goal/goal_recovery.py` — 目标恢复
- `kernel/goal/multi_goal_resources.py` — 多目标资源
- `kernel/goal/multi_goal_scheduler.py` — 多目标调度
- `kernel/governance/governance_center.py` — 治理中心
- `kernel/governance/risk_governor.py` — 风险治理
- `kernel/governance/evidence_governor.py` — 证据治理
- `kernel/governance/policy_governor.py` — 策略治理
- `kernel/governance/memory_governor.py` — 记忆治理
- `kernel/governance/capability_governor.py` — 能力治理
- `kernel/governance/adaptive_risk_engine.py` — 自适应风险
- `kernel/cognitive_supervisor/supervisor.py` — 认知监督器
- `kernel/cognitive_supervisor/prepare_dispatch.py` — 准备分派
- `kernel/cognitive_supervisor/dispatch_enrichment.py` — 分派增强
- `kernel/cognitive_supervisor/control_plane_gate.py` — 控制平面门控
- `kernel/cognitive_supervisor/run_outcomes.py` — 运行结果

### 能力/认知/协议
- `kernel/capability_intelligence/profiler.py` — 5D 画像
- `kernel/capability_intelligence/reasoner.py` — 推理器
- `kernel/capability_intelligence/knowledge_graph.py` — 知识图谱
- `kernel/capability_intelligence/execution_memory.py` — 执行记忆
- `kernel/capability_intelligence/strategy_memory.py` — 策略记忆
- `kernel/capability_intelligence/failure_memory.py` — 失败记忆
- `kernel/capability_intelligence/capability_score.py` — 评分
- `kernel/capability_intelligence/evolution.py` — 演化
- `kernel/capability_intelligence/adapter.py` — 适配器
- `kernel/cognition/world_model.py` — 世界模型
- `kernel/cognition/predictive_world.py` — 预测世界
- `kernel/cognition/runtime_grounding.py` — 运行时接地
- `kernel/protocol/runtime_contract.py` — 运行时契约
- `kernel/protocol/cognition_protocol.py` — 认知协议
- `kernel/protocol/agent_protocol.py` — 智能体协议
- `kernel/meta_cognition/meta_cognition.py` — 元认知
- `kernel/intent_engine/engine.py` — 意图引擎
- `kernel/reasoning/engine.py` — 推理引擎
- `kernel/identity/system_identity.py` — 系统身份
- `kernel/prompt_engine/` — Prompt 引擎
- `kernel/epistemology/` — 认识论
- `kernel/policy/` — 策略引擎
- `kernel/web_engine/` — Web 引擎
- `kernel/tools/` — 内核工具

### Agent 系统
- `agents/base.py` — Agent 基类
- `agents/bootstrap.py` — 引导注册
- `agents/registry.py` — Agent 注册表
- `agents/worker.py` — Agent Worker
- `agents/rag_agent.py` — RAG Agent（1156 行）
- `agents/data_agent.py` — DataAgent 包装
- `agents/data_agent_v2/` — DataAgent V2（25+ 子代理）
- `agents/web_agent.py` — Web Agent
- `agents/web_intelligence_agent.py` — Web Intelligence
- `agents/tool_agent.py` — Tool Agent
- `agents/vision_agent.py` — Vision Agent
- `agents/cognitive_agent.py` — Cognitive Agent
- `agents/skills_agent.py` — Skills Agent
- `agents/rule_engine_agent.py` — Rule Engine Agent
- `kernel/agent_runtime/agent_topology_manifest.yaml` — 拓扑清单
- `kernel/agent_runtime/executor.py` — AgentRuntimeExecutor
- `kernel/agent_runtime/contribution.py` — AgentContribution
- `kernel/agent_runtime/unified_evidence.py` — 统一证据
- `kernel/agent_runtime/cognitive_runtimes.py` — 认知运行时

### 记忆/模型/安全/基础设施
- `memory/working_memory/working_memory.py` — 工作记忆
- `memory/episodic_memory/episodic_memory.py` — 情景记忆
- `memory/semantic_memory/semantic_memory.py` — 语义记忆
- `memory/procedural_memory/procedural_memory.py` — 程序记忆
- `memory/temporal_memory/temporal_index.py` — 时间记忆
- `memory/memory_router/router.py` — 记忆路由
- `memory/fabric/memory_graph.py` — 记忆图
- `memory/evolution/evolution.py` — 记忆进化
- `model/model_gateway/gateway.py` — 模型网关
- `model/llm_adapter/openai_adapter.py` — LLM 适配器
- `model/embedding/` — 嵌入模型
- `model/reranker/` — 重排序
- `safety/masking/ner_masker.py` — NER 脱敏
- `safety/guardrails/guardrails.py` — 护栏
- `safety/policy_engine/engine.py` — 安全策略
- `infra/security/zero_trust.py` — 零信任
- `infra/config/settings.py` — 全局配置
- `infra/storage/database.py` — 数据库
- `infra/storage/models.py` — ORM 模型
- `infra/cache/redis_client.py` — Redis 客户端
- `infra/cache/redis_shadow_store.py` — ShadowRedis
- `infra/message_bus/agent_bus.py` — Agent 总线
- `infra/observability/tracer.py` — 追踪
- `infra/observability/logger.py` — 日志
- `infra/errors/` — 错误码
- `infra/guards/` — 内核守卫
- `plugins/` — 插件系统
- `skills/` — 技能系统
- `connectors/` — 连接器
- `tenant/` — 多租户
- `services/` — 服务层
- `control_plane/` — 控制平面
- `execution/` — 执行平面

### 运维/部署
- `docker-compose.yml` — Docker Compose
- `Dockerfile` — Docker 镜像
- `start.sh` — 启动脚本
- `.env.example` — 环境变量模板
- `pyproject.toml` — 项目配置
- `docs/adr/` — 架构决策记录

## 实施步骤

1. Part II: API 网关（Ch 4-11）— 从路由器源码提取端点信息
2. Part III: 认知内核（Ch 12-20）— 深入内核源码，提取关键类和方法
3. Part IV: 智能体系统（Ch 21-25）— 从 Agent 源码提取架构信息
4. Part V: 认知子系统（Ch 26-35）— 从子系统源码提取功能描述
5. Part VI: 安全与防护（Ch 36-38）— 从安全模块源码提取防护机制
6. Part VII: 基础设施（Ch 39-50）— 从基础设施源码提取配置和部署信息
7. Part VIII: 运维与开发（Ch 51-55 + 附录）— 编写运维指南和附录

## 验证方式

- 文档行数达到 8000-10000+
- 所有 55 个 Chapter 均有实质性内容
- API 端点文档覆盖所有 25+ 路由器
- 配置参考覆盖所有 100+ Feature Flag
- 代码片段可追溯到实际源文件