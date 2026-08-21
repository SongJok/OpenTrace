# Enterprise Production Intelligence Platform

## 1. 目标与非目标

OpenTrace 从“企业数据与知识问答”演进为 **Enterprise Production Intelligence
Platform**。平台面向企业员工统一承接 Web Workspace、WorkBuddy/运营客服工作台、企业
微信与飞书 Bot 的请求，在同一个受治理 Control Plane 中完成理解、规划、授权、执行、
证据融合、审查和回答。

本次改造的目标是：

1. 用 Production Asset Graph 明确业务、服务、代码、部署、配置、数据、监控、知识和负责
   人之间的关系，消除诊断过程中的猜测。
2. 用统一 Connector Gateway 接入 MCP、REST、SDK 与内部 RPC，同时保留专业高速通道。
3. 用 Production、Data、Config、Knowledge 四类受控能力覆盖线上故障、业务问数、配置
   检查和知识检索。
4. 所有高影响结论都经过 Evidence、Fusion 与 Critic，并输出结论、证据、置信度、影响和
   建议。
5. 默认只读；写入进入 Responses 持久化审批点与工具幂等账本，删除、回滚和生产变更必须
   由两个不同账号完成四眼审批。

以下内容不是目标：

- 不以 MCP Server 代替平台 Control Plane。
- 不迁移到另一套 Agent 框架；继续使用当前可恢复 Responses Worker 与 AgentLoop。
- 不恢复 `/api/v1/chat` 或 `/api/v1/tasks` 旧执行入口。
- 不允许模型获得任意 SQL、任意 HTTP 或任意 Shell 执行能力。
- 不把企业大脑、公司 Skill 和个人记忆重新包装为在线 Agent；它们继续由
  `ContextAssembler` 注入。

## 2. 目标主链路

```text
Web / WorkBuddy / 企业 IM Bot
              │
              ▼
       Enterprise AI Gateway
              │
       Identity + Tenant Scope
              │
       POST /api/v2/responses
              │
  PostgreSQL Response/Item/Event/Outbox
              │
              ▼
         Responses Worker
              │
  Understanding → IntentPlan → ExecutionPlan
              │
       IAM / Policy / Capability Discovery
              │
     ┌────────┼─────────┬──────────┐
     ▼        ▼         ▼          ▼
 Production  Data      Config    Knowledge
   Agent     Agent      Agent      Agent
     └────────┼─────────┴──────────┘
              ▼
    Governed Connector Gateway
       MCP / Native / REST / RPC
              │
 Git · Observability · DB · Config · CI/CD · Business
              │
              ▼
  Evidence Ledger → Fusion → Deterministic Critic
              │
 Conclusion / Evidence / Confidence / Impact / Recommendation
              │
              ▼
 Persistent Event Projection + resumable SSE
```

API 进程只验证请求、租户范围、资源范围和幂等键并提交持久状态。模型调用、连接器调用、
外部数据读取和副作用执行只允许出现在 Worker。客户端断开不取消 Response，Redis 丢消息
时由数据库租约恢复。

## 3. 领域边界

### 3.1 AI Gateway 与 Control Plane

Control Plane 对一次执行回答五个问题：

- 谁在问：用户、角色、租户、工作区、会话和来源渠道。
- 问什么：目标、意图、实体、环境、时间范围、影响面和所需证据。
- 能查什么：资源 ACL、数据分类、环境边界、操作权限和配额。
- 调什么：受信能力目录中的最小能力集合，以及确定性的执行依赖。
- 凭什么：证据来源、版本、时效、权限标签、冲突和置信度。

`control_plane/` 继续承担租户、配额、合规和能力生命周期的统一入口；Responses 主路径在
Worker 中调用它，不能在 API 中预先执行外部能力。

### 3.2 Production Asset Graph

当前生产基线使用 PostgreSQL 邻接表，并通过受控接口保留替换图存储的边界。核心资产类型为：

- `business_domain`
- `service`
- `repository`
- `deployment`
- `config`
- `database`
- `table`
- `dashboard`
- `alert`
- `owner`
- `runbook`
- `business_api`

关系使用受控词表，例如 `contains`、`owned_by`、`depends_on`、`repository_for`、
`deployed_as`、`configured_by`、`reads_from`、`writes_to`、`monitored_by`、
`documented_by`。所有资产和关系都包含 `tenant_id + workspace_id`，服务层禁止跨范围连边。

图谱不是回答事实本身，而是连接器选择、查询收敛和证据关联的上下文。外部同步来源、人工
维护来源和推断关系必须分别标注；推断关系不得伪装为权威配置。

外部资产源使用持久同步运行记录管理稳定来源键、增量游标、请求幂等、租约恢复和来源
所有权。权威全量同步只退役同一来源拥有且本次未出现的资产，并删除同源过期关系；不会
静默覆盖人工或其他来源维护的节点。所有权转移必须显式开启并进入审计。

### 3.3 Connector Gateway

Connector Gateway 是统一治理边界，不等于“全部 MCP 化”。每个能力声明：

- 连接器类型与传输：`mcp`、`native`、`rest` 或 `rpc`。
- 操作名、输入 JSON Schema、风险等级、超时、最大结果大小和所需权限。
- 支持的环境、数据分类、速率限制和审计策略。
- 输出的证据类型、资源引用、观测时间和脱敏策略。

平台不持久化明文凭据，只保存外部 Secret Manager 的引用。模型只能看到经过 Policy 过滤
的操作目录，不能选择任意 URL、任意工具名或任意 MCP Server。

运行时通过 Redis 原子脚本统一执行滑窗限流、分布式并发租约、连续失败熔断和半开恢复。
控制存储故障时只读能力可显式降级，任何写能力失败关闭；写操作还必须声明下游幂等支持。

建议的接入顺序：

1. Knowledge、Data、Git 和基础 Observability 只读操作。
2. Trace/Log/Metric/Deployment/Config 关联查询。
3. Config Dry Run、CI/CD 检查等低风险写操作。
4. 回滚、配置发布和生产变更；始终需要持久化审批与审计。

### 3.4 四类受控能力

| 能力 | 责任 | 典型证据 | 明确边界 |
| --- | --- | --- | --- |
| Production | 故障、Bug、异常、发布关联与影响分析 | metric、trace、log、deployment、code | 不直接执行修复 |
| Data | 指标、业务查询、漏斗和影响数量 | metric contract、validated SQL、snapshot | 不暴露任意 SQL |
| Config | Schema、规则、历史、容量、冲突和 Dry Run | policy result、snapshot、simulation | 确定性校验优先于 LLM |
| Knowledge | PRD、SOP、Runbook、历史事故 | 已发布文档与引用 | 不生成无来源事实 |

复杂问题由 Manager 生成有依赖关系的 ExecutionPlan；能力之间不自由聊天。结果统一进入
Evidence/Fusion/Critic，避免多 Agent 自由讨论造成不可恢复、不可审计的状态。

### 3.5 Evidence 与 Critic

统一证据至少包含：

```json
{
  "evidence_type": "trace",
  "source_kind": "observability",
  "source_ref": "trace://8af...",
  "asset_id": "payment-service",
  "environment": "prod",
  "observed_at": "2026-08-20T18:35:00Z",
  "title": "ledger RPC timeout",
  "summary": "account-service 调用 ledger-service 超时",
  "authority": "production_observation",
  "permission_class": "internal",
  "confidence": 0.95,
  "content_hash": "sha256:..."
}
```

Critic 首先执行确定性检查，再决定是否需要模型辅助：

- 所需证据种类是否齐全。
- 环境、时间窗口、服务版本和部署版本是否一致。
- 是否存在相互冲突的证据。
- 结论是因果关系、相关关系还是仅时间邻近。
- 数据是否过期，引用是否可定位，用户是否有权查看。
- 影响估算是否有受治理数据查询支持。

高影响回答固定包含 `Conclusion / Evidence / Confidence / Impact / Recommendation`。证据
不足时必须降级为“无法确认”并列出缺口，不能用语言流畅度掩盖缺证。

### 3.6 IAM、Policy 与审批

建议角色矩阵：

| 角色 | Code | Log/Trace | DB | Config | 生产修改 |
| --- | --- | --- | --- | --- | --- |
| customer_service | 无 | 脱敏摘要 | 用户级受限 | 无 | 无 |
| operations | 无 | 摘要 | 业务范围 | 只读/提交检查 | 审批 |
| product | 部分 | 摘要 | 聚合 | 只读 | 无 |
| developer | 有 | 有 | 受限 | 有 | 审批 |
| sre | 有 | 有 | 受限 | 有 | 审批 |
| admin | 有 | 有 | 有 | 有 | 破坏性操作四眼审批 |

通用执行等级：

- `read`：策略允许时自动执行。
- `write_low`：单人持久化确认。
- `write_high`：审批后执行，结果必须验证。
- `destructive`：双确认/双人审批、幂等键、执行后验证与完整审计。

默认拒绝未知角色、未知连接器操作、跨租户资产、跨环境查询和缺少分类标签的数据。

## 4. 持久化模型

新增事实表分为四组：

1. 资产：`production_assets`、`production_asset_relations`。
2. 连接器：`enterprise_connectors`，仅保存非敏感配置和凭据引用。
3. 证据：`production_evidence`，关联 Response、资产与连接器，保存哈希和受控摘要。
4. 配置智能：`production_config_policies`、`production_config_snapshots`、`production_config_validation_runs`。

所有表建立租户/工作区组合索引。正式结构变更通过 Alembic；开发兼容 DDL 不抢先创建新
表。高容量原始日志、Trace 和指标不复制进 PostgreSQL，只保存不可变引用、必要摘要和哈希。

## 5. 典型执行图

### 5.1 线上 Bug

```text
实体/时间/环境识别
  → Asset Graph 定位业务与服务
  → Data Agent 查询业务事实
  → Trace 查询
  → Log/Error 查询
  → Deployment 与 Config Diff
  → Repository Diff/Blame
  → 历史 Incident/Runbook
  → Evidence Fusion
  → Critic
  → 根因、影响与建议
```

### 5.2 活动配置检查

```text
解析配置
  → JSON/YAML Schema
  → 引用完整性
  → 业务 Policy as Code
  → 时间/资源冲突
  → 历史成功配置分位数
  → 容量估算
  → 受控 Dry Run
  → 风险解释
  → 审批（仅当要求发布）
```

## 6. 分期交付与验收

### Phase 1：生产智能查询基础

- 资产图 CRUD、邻域查询、批量导入与租户隔离。
- Connector 契约、目录、Policy 过滤、Secret 引用和审计。
- Data/RAG 保持在线能力，新增只读生产资产查询工具。
- Web Workspace 提供资产与连接器管理入口。
- 验收：员工能从业务或服务定位关联代码、数据、监控和负责人；所有访问可审计。

### Phase 2：智能诊断

- Production 能力、部署/配置/Trace/Log/Metric/Git 证据标准化。
- Evidence 持久化、Fusion、确定性 Critic 和标准答案协议。
- 验收：线上异常问题能够给出跨至少两个独立来源的证据闭环，缺证时明确拒答。

### Phase 3：Config Intelligence 与受控运维

- Config Policy、历史快照、分位数、容量模型、冲突检查和 Dry Run。
- 发布检查、修复建议、审批后执行、执行后验证和 reconciliation。
- 验收：任何生产写操作均无法绕过审批、幂等账本、审计和结果验证。

## 7. 质量门槛

- 后端单测、Responses/Worker 合约、租户隔离、迁移单头、导入边界全部通过。
- 前端 TypeScript 构建与 Vitest 通过。
- Connector 单次输出有大小限制、超时、脱敏和审计；副作用操作不自动重试。
- 关键查询都有 Prometheus 指标与 OpenTelemetry span，不记录凭据或原始敏感数据。
- 示例配置、Feature Flag、部署文档、威胁模型、贡献指南和变更日志同步更新。
- 评测集覆盖线上 Bug、业务查询、配置检查、发布问题、系统异常、客服、运营和产品八类
  场景，并测量证据完整率、错误归因率和安全拒绝率。

## 8. 实现状态与部署边界

当前代码库已实现平台核心：四类 Manifest 受控能力、资产图、持久化增量/权威同步、Connector
目录/Gateway/MCP/Native SDK、Capability Policy、配置策略与验证运行、Evidence/Fusion/Critic、
分布式限流/租约/熔断、下游幂等透传、破坏性操作双人四眼审批与副作用账本、SSE 进度事件和
管理工作台。

GitHub/GitLab、Grafana/Sentry/Datadog、Kubernetes、CI/CD、CMDB、配置中心和内部业务 API 的
真实凭据、网络与资源 ACL 属于部署方边界，不能在开源仓库中伪造。它们通过
`docs/CONNECTOR_DEVELOPMENT.md` 的统一契约接入，必须在 staging 完成最小权限、证据可定位性和
真实主链评测后再放量。四眼审批由 Responses 持久化协议强制执行；OPA/CUE/Temporal 等
组织级扩展保持可插拔，不成为默认开源运行时的强依赖。
