# PostgreSQL PITR、备份恢复与灾备演练

## 生产要求

- PostgreSQL 启用持续归档/PITR，目标 RPO ≤ 5 分钟、RTO ≤ 60 分钟；备份跨可用区并使用 KMS
  加密，生产账号与备份恢复账号分离。
- Redis 不是事实来源，不从 Redis 恢复业务状态；恢复后由 PostgreSQL Outbox、Response lease 和
  scheduler 重建投递。
- 每月至少恢复一次到隔离数据库，每季度执行一次完整区域级演练。

## 演练步骤

1. 记录故障点、目标恢复时间、当前 Alembic revision 和镜像 digest。
2. 执行 `DATABASE_URL=... BACKUP_DIR=... bash scripts/backup_postgres.sh`。
3. 创建隔离空库，设置 `RESTORE_DATABASE_URL`，执行
   `bash scripts/verify_disaster_recovery.sh backups/opentrace-*.dump`。
4. 验证单 migration head、Response/Item/Event 外键、Outbox backlog、租户 RLS、附件对象可读性。
5. 使用隔离 API/Worker 重放只读请求；写工具保持审批关闭，避免外部副作用。
6. 记录实际 RPO/RTO、丢失窗口、孤儿记录、人工步骤和改进项。

严禁未演练的备份被标记为“可恢复”。逻辑备份用于便携验证，生产优先使用托管数据库快照与 WAL。
