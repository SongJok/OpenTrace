# OpenTrace 能力成熟度

> **产品整体状态：Alpha。** OpenTrace 对外只使用 Alpha / Beta / GA，不再以单个模块“生产级”替代产品交付成熟度。在线架构以 `docs/architecture/runtime_manifest.yaml` 为准。

| 产品能力 | 当前状态 | 进入 Beta 前的主要缺口 |
|---|---|---|
| Responses 持久化运行时 | **Alpha** | 真实故障注入、SLO、容量和备份恢复门禁 |
| Agent Loop 与持久化审批 | **Alpha** | Golden Dataset、Trace Grading、副作用 reconciliation 演练 |
| DataAgent / Text2SQL | **Alpha** | 脱敏评测集、方言黑盒覆盖、跨租户负向测试 |
| RAG 与知识发布 | **Alpha** | 发布治理评测、引用准确率基线、生产规模召回测试 |
| Memory / Goal / Task / Alert | **Alpha** | 一致性、恢复、租户隔离和运维告警覆盖 |
| Agent Bus 与专家 Agent | **Alpha** | 独立 Worker Pool、背压、DLQ 运维和容量基线 |
| 旧 Cognitive Runtime | **compatibility / experimental** | 不进入当前产品主路径；仅维护兼容合约 |
| MCP / A2A | **未对外支持** | 完成真实协议、授权、审批、隔离与互操作测试 |

## 成熟度定义

- **Alpha（当前）**：核心能力可运行且有合约保护，但仍缺生产交付、安全和持续质量闭环。
- **Beta**：可用于受控企业试点，具备恢复、租户隔离、评测和运维基线。
- **GA**：完成生产 SLO、备份恢复、安全评审、容量与升级策略，并持续通过发布门禁。
