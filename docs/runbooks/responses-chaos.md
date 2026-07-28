# Responses 故障注入矩阵

仅在隔离 staging 运行。每个场景都必须记录 Response ID、事件序列、工具 ledger、lease owner、
Outbox 状态、恢复耗时与重复副作用数。

| 场景 | 注入 | 验收 |
|---|---|---|
| Redis 丢失 | stop/restart Redis | DB polling 接管；Outbox 不丢；Redis 恢复后继续发布 |
| Worker kill | SIGKILL 执行 Worker | lease 到期后接管；事件序列连续；副作用不重复 |
| 重复投递 | 同一 outbox payload 投递两次 | 只产生一次业务结果 |
| DB 切换 | 托管数据库 failover | 客户端连接恢复；未提交事务安全重试 |
| 模型超时 | provider 延迟超过预算 | 有限重试、熔断、明确终态 |
| 工具 unknown | 外部系统提交后断连 | 标记 reconciliation，不自动重试 |

使用 `python scripts/chaos_responses.py <scenario>` 查看计划；执行破坏性容器场景还必须增加
`--execute --allow-destructive`。
