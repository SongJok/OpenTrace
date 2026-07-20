# ChatGPT 化五项能力主链合流

本文只描述当前在线主路径：`/api/v2/responses → Agent Worker → kernel/agent_loop`。
旧 `CognitiveKernel/CognitiveSupervisor` 的同名模块不属于本能力的在线入口。

## 1. Agentic Planning

规划模型在一次严格工具调用中同时输出 `IntentPlan` 与 `ExecutionPlan`。后者包含复杂度、
2–8 个面向用户的执行步骤、依赖、成功标准和重规划上限。计划以 `agent_plan` ResponseItem
持久化；步骤开始、延后、完成、失败和重规划以 `opentrace.plan.*` 事件写入 PostgreSQL，
Intent、步骤状态和重规划计数同时回写计划 Item；续跑会直接恢复规划决策，不会再次调用
规划模型生成另一套能力选择。因此 SSE 断线、Worker 重启和审批暂停不会丢失计划事实或
恢复进度。

依赖未满足的工具调用会被延后。只读工具失败后，Manager 在原工具结果上下文上重新评估
剩余路径；副作用工具仍遵守审批、幂等账本和“不自动重试”约束。

## 2. 动态记忆与关系图

`UserMemory` 仍是记忆节点，`user_memory_relations` 是关系边的事实来源。主动学习、用户确认
和手工新增记忆后，会在同一 user/tenant/workspace/scope 内建立 `same_topic`、`supports`
或 `supersedes` 边。编辑记忆会重建相关边，删除由外键级联清理。

在线读取先做文本相关性排序，再从命中节点做一跳关系扩展；图权重、置信度、显著性、访问
强化和时间衰减共同参与排序。关系图不能扩大用户、租户、工作区、Project 或 conversation
边界。记忆页通过 `/api/v2/memories/graph` 展示持久节点与边。

## 3. 原生多模态融合

Responses 输入和会话附件统一归一化为文本、图片、音频、视频 part。图片路由到 Vision 模型；
音频或视频路由到 `DEFAULT_LLM_OMNI_MODEL`。图片、音频、视频与当前文本在同一 user message
中进入模型，不再通过旧 Vision Agent 二次转述。纯媒体输入也可创建 Response。

文档、表格和幻灯片仍优先抽取受限文本，避免把任意二进制伪装成模型指令。音视频使用受限
Base64 Data URL，大小由 `MULTIMODAL_INLINE_MAX_MB` 控制。

## 4. 工具自发现

能力发现从统一 `CapabilityRegistry` 与调用方显式 tools 构建可信目录，按名称、描述和参数语义
排序。小目录完整交给规划器；目录超过预算时只暴露相关能力，并始终保留调用方显式工具。
Assistant Profile 的 allow/deny policy 在发现前执行，模型不能通过“发现”扩大权限。

发现结果写入 `opentrace.capabilities.discovered` 和最终 Response metadata，便于审计为什么某项
能力进入本轮规划。

## 5. Long-context Handling

ContextAssembler 使用 token-aware 分层打包：平台/租户安全边界、最新持久摘要、最近消息、
工具调用对、当前输入与媒体分别计量。当前输入和最新摘要优先保留；工具 schema 与输出预留
也计入同一窗口。图片/音频/视频按媒体 token 预算估算，不再把 Base64 长度误算为文本 token。

超过阈值的活跃分支会生成带版本、来源 Response、checksum 和 source token 数的持久摘要。
新版本摘要会把上一版摘要与新增回合合并，而不是只压缩增量消息，避免多次滚动压缩后遗失
早期目标和决定。
每轮 `context_manifest` 记录估算输入、裁剪条数、摘要命中、媒体数量、记忆关系数与工具 schema
预算，便于容量规划和回归。

## 不变量

- API 进程只校验并提交持久命令，模型、规划、记忆学习和工具执行只在 Worker。
- PostgreSQL 是 Response、事件、工具账本和记忆图事实来源。
- 不输出或持久化隐藏思维链；计划与 reasoning summary 只包含面向用户、可核验的执行摘要。
- write/destructive 工具必须进入持久审批暂停点，未知副作用结果不得自动重试。

## 项目评价与边界

OpenTrace 的核心优势不是单个 Prompt，而是 Responses、Outbox、数据库租约、持久事件、审批和
工具账本组成的可恢复执行面；这使它已经具备较强的企业 AgentOS 工程基础。本轮五项能力已经
合流到这条主路径，不再是旁路模块或旧 Kernel 中的概念性实现。

当前 Agentic Planning、能力发现和长上下文已达到“可观测、可恢复、可配置”的工程状态；记忆图
和原生多模态达到可用主链状态。它们仍不应被描述为与 ChatGPT 产品完全等价：记忆关系目前是
确定性一跳图，尚未使用独立关系抽取/图嵌入；音视频聚焦异步理解，未实现实时双工语音；长上下文
依赖模型实际窗口和估算器精度。发布前还需要真实 Provider 冒烟、长会话压力测试、跨租户隔离
回归，以及基于成功率/延迟/成本的离线评测集。
