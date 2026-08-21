# OpenTrace 生产 SLO

本 SLO 适用于 `/api/v2/responses` 持久化执行主路径及其受治理 Production Intelligence
执行面。开发数据库样本、旧 Cognitive Runtime 指标和人工 smoke test 不可作为生产 SLO
证据；配置校验发现业务风险不属于平台可用性失败。

## 服务级目标

| 指标 | 目标 | 统计口径 |
|---|---:|---|
| API 可用性 | 月度 ≥ 99.9% | 非预期 5xx；鉴权/限流/参数错误不计入失败 |
| Response 非取消成功率 | 月度 ≥ 99.0% | `completed / (completed + failed + incomplete)` |
| 首持久化事件 P95 | ≤ 2 秒 | 创建事务提交至 `response.in_progress` |
| 端到端完成 P95 | ≤ 120 秒 | 创建至终态；按能力类型拆分看板 |
| 模型调用 P95 | ≤ 30 秒 | Model Gateway span/metric |
| 队列等待 P95 | ≤ 5 秒 | 创建至数据库 lease claim |
| 工具只读成功率 | ≥ 99.0% | durable tool ledger 的终态 |
| 写工具未知结果 | < 0.1% | reconciliation / write tool executions |
| SSE 续传正确率 | 100% | sequence_number 无跳号、无重复业务事件 |
| 跨租户数据泄露 | 0 | PostgreSQL RLS 与 API 负向测试 |
| Connector 只读成功率 | 月度 ≥ 99.0% | 已准入调用中 `completed / all`；Policy、限流拒绝单独统计 |
| Connector 写入未知结果 | < 0.1% | 生产写操作中进入 reconciliation 的比例 |
| Connector 控制面可用性 | 月度 ≥ 99.9% | Runtime Control 非 `unavailable` 的决策比例；写操作始终失败关闭 |
| 生产证据门禁正确率 | 100% | `blocked/incomplete` Critic 不得满足 Response 证据要求 |
| 资产同步成功率 | 月度 ≥ 99.0% | 已领取同步运行的 `completed / (completed + failed)` |
| 资产同步 P95 | ≤ 300 秒 | 持久租约领取至原子提交终态；按权威/增量拆分 |
| 资产来源游标错序 | 0 | 非幂等重放必须严格延续上次成功游标 |
| 破坏性操作单账号执行 | 0 | `required_approvals = 2` 且批准事实来自两个不同 user_id |
| 破坏性操作二次审批积压 | < 20 | `pending_secondary` 持久审批数；按 Worker 周期采样 |
| 破坏性操作最老审批等待 | ≤ 30 分钟 | 审批创建至最终批准/拒绝；超时必须复核请求是否仍有效 |

## 错误预算

- 月度 Response 失败预算为 1%。消耗 50% 时冻结非可靠性功能发布；消耗 100% 时仅允许
  故障修复、安全修复与回滚。
- 采用 5 分钟快速窗口与 1 小时慢速窗口组合告警；低流量租户使用绝对失败数保护。
- 成本、Token、能力成功率必须按 tenant/workspace 在持久事实或日志中聚合，但 Prometheus
  标签不得包含 tenant、workspace、user、response、connector_id 或 conversation 等高基数字段。
- Connector 的 Policy 拒绝、限流、并发保护和熔断拒绝不是供应商调用失败，必须与适配器错误
  分开计算；`runtime_control_unavailable` 对写操作按可用性事故处理。
- 四眼审批等待属于治理 SLI，不计入平台可用性失败；但等待期间禁止降级为单人审批、复制请求
  绕过队列或直接调用下游。生产动作一旦进入 reconciliation，按 page 处理并冻结同目标后续写入。

## 发布证据

每次 Beta/GA 发布必须归档：Golden Dataset 报告、按
[Responses 容量手册](runbooks/responses_capacity.md) 生成且绑定候选提交的端到端容量结果、恢复
演练结果、迁移验证、SBOM、安全扫描、SLO 看板截图和已知风险。规则文件位于
`deploy/observability/prometheus-rules.yml`。
