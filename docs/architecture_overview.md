# OpenTrace 架构总览

> **产品成熟度：Alpha。** 本文与 `docs/architecture/runtime_manifest.yaml` 共同构成在线架构单一真相；清单由 `python scripts/check_architecture_manifest.py` 自动校验。

## 唯一在线对话主路径

```text
POST /api/v2/responses
  → API 校验身份、租户/工作区/项目范围和幂等键
  → PostgreSQL 同一事务写入 Response / Item / Event / Outbox
  → Agent Worker 投递 Redis Streams，并通过数据库租约领取 Response
  → IntentPlan → ContextAssembler → Manager model/tool loop
  → typed tools / expert agents / RAG / DataAgent
  → 写或破坏性操作进入持久化审批暂停点
  → PostgreSQL 持久化输出、事件、模型计量和工具账本
  → SSE 按 sequence_number 投影和断点续传
  → 会话摘要、记忆学习、Goal、Task 与 Alert 后处理
```

PostgreSQL 是在线执行事实来源；Redis 只承担投递、唤醒和可重建投影。API 进程只提交命令，不执行模型和工具。客户端断开 SSE 不取消持久化 Response。

## 关键边界

| 边界 | 权威实现 | 约束 |
|---|---|---|
| API 命令面 | `gateway/api_gateway/routers/responses.py` | 只校验和持久化，不导入 Worker、AgentLoop 或 provider client |
| 事实存储 | `infra/storage/models.py`、`infra/responses/repository.py` | Response/Item/Event/Outbox/Approval/Tool ledger 为在线事实 |
| 执行面 | `agents/worker.py`、`infra/responses/worker.py` | 通过数据库租约恢复，不依赖 Redis 消息完整性 |
| Manager Loop | `kernel/agent_loop/` | 模型统一经过 Model Gateway；副作用必须审批和幂等 |
| 模型入口 | `model/model_gateway/gateway.py` | 业务模块不得直接创建 provider client |
| 流式读取 | `/api/v2/responses/{id}/events` | 从持久化事件投影，可断点续传 |

## 兼容与实验子系统

`kernel/cognitive_supervisor/`、`kernel/runtime_gateway.py` 以及相关 Cognitive Runtime 文档只保留为 **compatibility/experimental**。它们不是产品能力清单中的在线 Responses 入口；只有任务明确涉及兼容子系统时才修改。

`/api/v1/chat` 与 `/api/v1/tasks` 是迁移墓碑，固定返回 `410 Gone`。

## 成熟度口径

OpenTrace 对外只使用 **Alpha / Beta / GA**：

- **Alpha（当前）**：核心持久化执行链可用，但备份恢复、容量基线、完整安全隔离和持续评测尚未全部完成。
- **Beta**：关键场景具备真实 PostgreSQL 故障恢复、跨租户负向测试、Golden Dataset 和试点运维基线。
- **GA**：完成生产 SLO、备份恢复演练、安全评审、容量与升级策略，并通过发布门禁。

模块不得单独宣称“生产级”来绕过产品整体成熟度。

## 企业知识库主链

知识编排继续作为内部控制面，员工产品面为企业知识库。`KnowledgeSpace` 提供公司、部门、岗位、项目和个人治理边界；连接器增量同步来源内容与 ACL，编译结果经过密级、有效期、Lint 和 Review Task 后才能成为 Active Published Version。RAG 在召回前统一执行空间与来源权限过滤。详细设计见 `docs/architecture/enterprise_knowledge_base.md`。
