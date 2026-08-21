# ADR-004：以自有 Control Plane 承载生产智能平台

- 状态：Accepted
- 日期：2026-08-20

## 背景

OpenTrace 已有 Responses API、数据库租约 Worker、AgentLoop、DataAgent、RAG、企业上下文、
个人记忆和持久化审批。新的生产智能需求需要接入 Git、可观测性、配置、CI/CD、业务 API
等外部系统，并对线上故障、业务变化和活动配置形成可核验结论。

如果把某个 MCP Server、外部模型产品或另一套 Agent Runtime 放在平台中心，会分裂租户、
权限、审批、幂等、证据和恢复语义，并使现有 Responses 主路径失去事实来源地位。

## 决策

1. 保留当前自研可恢复 AgentLoop 和 Responses Worker 作为唯一在线执行面。
2. 新建 Governed Connector Gateway，将 MCP、Native SDK、REST 和内部 RPC 统一纳入能力
   契约、Policy、超时、脱敏、审计和证据标准。
3. 使用 PostgreSQL 实现 Production Asset Graph 第一版；关系规模和查询形态证明需要后再
   评估图数据库。
4. 在线能力收敛为 Production、Data、Config、Knowledge 四类，由 Manager 按 Execution
   Plan 调度，不允许自由 Multi-Agent 讨论。
5. 高影响回答必须经过 Evidence/Fusion/Critic；生产写操作必须经过持久化审批、工具账本和
   执行后验证。

## 后果

正向结果：

- 复用现有可靠性与治理基础，不引入第二套会话事实来源。
- MCP 与专业 API 可以按场景组合，性能和互操作性不互相排斥。
- 资产、连接器、证据和审批都可以在租户/工作区范围内审计和恢复。
- 四类能力边界清晰，便于评测、灰度和故障隔离。

代价：

- 需要维护 Connector SDK、资产同步和 Policy 词表。
- 对外部系统的生产级适配需要逐个实现与认证，不能依赖任意 MCP 即插即用。
- 确定性证据检查会增加少量延迟，但这是企业可信度必须承担的成本。

## 被否决的方案

- 将纯 MCP Client 作为平台 Runtime：缺少统一恢复、审批和事实存储。
- 迁移到 LangGraph 或 Temporal 承载每次对话：与现有可恢复 Worker 重叠；Temporal 仅保留为
  未来长流程可选实现。
- 一开始引入大量专用 Agent：能力重叠、调度不稳定且难以做最小权限。
- 将原始日志、Trace 和指标全量复制入 PostgreSQL：成本高、时效差并扩大敏感数据面。
