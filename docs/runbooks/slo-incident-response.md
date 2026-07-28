# SLO 告警处置

1. 确认告警窗口、版本、租户范围和是否存在供应商事故。
2. 查看 API 5xx、Response queue/outbox、DB pool、Redis、lease recovery、模型与工具分段 Trace。
3. 队列积压时先启用背压并扩容 Worker；不要绕过 PostgreSQL claim 或直接删除 Stream 消息。
4. Redis 故障时保留数据库轮询恢复路径；DB 故障时停止写流量并执行托管数据库切换流程。
5. 副作用工具出现 unknown result 时不得自动重试，必须进入 reconciliation。
6. 记录开始/发现/缓解/恢复时间、影响 Response 数、根因和防复发事项。
