# SLO 告警处置

1. 确认告警窗口、版本、租户范围和是否存在供应商事故。
2. 查看 API 5xx、Response queue/outbox、DB pool、Redis、lease recovery、模型与工具分段 Trace。
3. 队列积压时先启用背压并扩容 Worker；不要绕过 PostgreSQL claim 或直接删除 Stream 消息。
4. Redis 故障时保留数据库轮询恢复路径；DB 故障时停止写流量并执行托管数据库切换流程。
5. 副作用工具出现 unknown result 时不得自动重试，必须进入 reconciliation。
6. 记录开始/发现/缓解/恢复时间、影响 Response 数、根因和防复发事项。
7. Connector 控制面不可用时，只读调用可按连接器策略显式降级；写操作必须保持失败关闭，禁止
   临时绕过 Runtime Control、Policy、审批或幂等键。
8. Connector 熔断时先确认下游供应商、凭据、配额和最近变更；不要通过提高失败阈值掩盖故障。
9. 资产同步失败时检查来源游标、租约所有者和来源所有权。只允许使用相同幂等键重试相同载荷；
   不得手工跳过游标或直接删除失败运行事实。
10. Critic 阻断或不完整率上升时检查证据时间戳、环境、独立来源和资产映射；不得关闭答案门禁。
11. `execute_production_action` 进入 reconciliation 时立即冻结同一目标资产的后续写操作，根据
    Tool Ledger 的下游幂等键到真实系统核对；确认最终状态后走人工 reconciliation 流程，不得
    重新提交、修改账本终态或让模型推测结果。
12. 四眼审批积压时检查待复核队列、审批人角色和原请求有效期。第二审批人必须使用不同账号，
    重新核对已脱敏参数、环境和影响范围；超过 30 分钟的请求应优先拒绝并由发起人重新评估，
    禁止临时降低 `required_approvals`。
13. 配置验证或 dry-run 告警时分别核对确定性 schema/rule 结果和绑定 candidate hash、asset、
    environment 的验证证据。HTTP 200、transport `completed` 或未绑定证据都不代表 dry-run 通过。
14. 资产游标异常时保留失败运行和当前成功游标，核对来源租约及增量范围；不得手工前移游标、
    将旧游标伪装为全量同步，或在未确认来源完整性时执行权威清理。
