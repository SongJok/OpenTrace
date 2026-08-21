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
| Connector 控制面失联 | 分布式限流/熔断存储不可用 | 写操作失败关闭，不绕过 Runtime Control |
| Asset Sync 并发 | 同来源并发租约和旧游标 | 锁内重检游标，仅一个运行可提交 |
| 四眼重复批准 | 同账号提交两次批准 | 保持 `pending_secondary`，生产动作不执行 |

使用 `python scripts/chaos_responses.py <scenario>` 只查看计划。合同演练执行时必须指定全新的
证据文件：

```bash
python scripts/chaos_responses.py four-eye-replay \
  --execute --evidence-output artifacts/chaos/four-eye-replay.json
```

容器场景额外要求：

- 仅允许 `CHAOS_TARGET_ENV=staging` 且 `APP_ENV` 非 production；
- Compose project 名必须显式包含 `staging` 或 `chaos`，避免误操作同机其他项目；
- Token 只能通过 `CHAOS_API_TOKEN` 环境变量提供，命令行不得出现凭据；
- 选择注入前尚未结束的 `response_id`，`worker-kill` 必须已经是 `in_progress`；
- 必须增加 `--allow-destructive`，编排器会在 `finally` 恢复服务，并验证服务 running、Response
  终态和从 0 连续的持久事件序列；
- 证据文件独占创建且不保存 Response 正文、事件 payload、用户或租户标识，既有文件绝不覆盖。

示例：

```bash
CHAOS_TARGET_ENV=staging APP_ENV=staging CHAOS_API_TOKEN='***' \
python scripts/chaos_responses.py redis-outage \
  --execute --allow-destructive \
  --compose-project opentrace-staging-chaos \
  --compose-file deploy/staging/docker-compose.yml \
  --response-id resp_... \
  --evidence-output artifacts/chaos/redis-outage-20260820.json
```

演练通过只表示该次目标 Response、目标项目和证据文件满足验收，不得外推为季度可用性数据。
