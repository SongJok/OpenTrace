# 数据保留、删除传播与 Legal Hold

- 默认保留期由 `ENTERPRISE_DEFAULT_RETENTION_DAYS` 控制；审计日志不得与普通 Trace 使用同一短期策略。
- 管理员通过 `/api/v1/admin/legal-holds` 建立保全；活动 Legal Hold 优先于保留清理和租户删除。
- `/api/v1/admin/data-deletions` 只创建带冷静期的持久化任务。执行器先删除对象存储，再按 ORM
  外键反向拓扑清除所有带 `tenant_id` 的业务表；治理任务、Legal Hold 和审计日志留作证据。
- 删除任务必须支持 pending/blocked/running/completed/failed，任何对象存储失败都应在数据库删除前
  中止，避免留下不可对账的二进制孤儿。
