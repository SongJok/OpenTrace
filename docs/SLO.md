# OpenTrace 生产 SLO

本 SLO 只适用于 `/api/v2/responses` 持久化执行主路径。开发数据库样本、旧 Cognitive
Runtime 指标和人工 smoke test 不可作为生产 SLO 证据。

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

## 错误预算

- 月度 Response 失败预算为 1%。消耗 50% 时冻结非可靠性功能发布；消耗 100% 时仅允许
  故障修复、安全修复与回滚。
- 采用 5 分钟快速窗口与 1 小时慢速窗口组合告警；低流量租户使用绝对失败数保护。
- 成本、Token、能力成功率必须按 tenant/workspace 聚合，但 Prometheus 标签不得包含 user、
  response 或 conversation 等高基数字段。

## 发布证据

每次 Beta/GA 发布必须归档：Golden Dataset 报告、容量结果、恢复演练结果、迁移验证、SBOM、
安全扫描、SLO 看板截图和已知风险。规则文件位于 `deploy/observability/prometheus-rules.yml`。
