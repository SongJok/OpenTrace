# ChatGPT 化零停机切换

## Expand

1. 部署 `20260723_unified_agent_runtime`，此迁移只增加表、列和索引。
2. 先部署兼容读取的新 API，再滚动部署 Agent Worker；API 实例不得运行模型任务。
3. 确认 `response_outbox`、Responses Stream consumer group 和 Worker heartbeat 正常。

## Backfill 与校验

```bash
python scripts/backfill_responses_v2.py --dry-run
python scripts/backfill_responses_v2.py --batch-size 500
```

按租户核对会话数、Response 数、输入/输出 Item 数、事件序号连续性、父子分支和 active response。脚本使用确定性 ID，可中断重跑。

## Switch

1. 前端与所有正式客户端只调用 `/api/v2`。
2. `/api/v1/chat` 和 `/api/v1/tasks` 保持 `410 Gone`；迁移窗口内 v1 conversations 只作为滚动部署兼容入口。
3. 按租户灰度启用新前端和 Worker，监控 queue lag、租约回收、工具失败、审批等待和 Provider 降级。

## Rollback 与 Contract

Contract 前保留旧表只读和 7 天数据库恢复点；回滚只切换客户端版本，不回写旧表。连续 7 天校验无漂移后，删除 v1 conversations 兼容路由及旧 Message/TraceLog 表。原始思维链、秘密和未脱敏工具参数不得进入日志或迁移审计文件。
