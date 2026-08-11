# OpenTrace 能力成熟度

> **产品整体状态：受控企业 Beta。** Beta 表示支持范围内的主路径可进入受治理企业试点，不代表 GA。在线架构以 `docs/architecture/runtime_manifest.yaml` 为准，放量条件以 `docs/BETA_READINESS.md` 为准。

| 产品能力 | 当前状态 | Beta 后至 GA 的主要工作 |
|---|---|---|
| Responses 持久化运行时 | **Beta** | 企业准入、恢复、审批、结算和发布门禁已闭环；GA 仍需生产 SLO、容量和备份恢复长期基线 |
| 提问页与 Responses 持久化运行时 | **Beta** | 继续提升真实提问完成率、恢复语义和成本基线 |
| Agent Loop 与持久化审批 | **Beta** | 扩大 Golden Dataset、Trace Grading 和副作用 reconciliation 演练规模 |
| DataAgent / Text2SQL | **Beta** | 扩大脱敏评测集、复杂方言覆盖和生产查询延迟基线 |
| RAG 与知识发布 | **Beta** | 建立更长周期的引用准确率、生产规模召回和治理质量数据 |
| Memory / Task | **Beta** | 完善长期一致性、权限边界和生产运维基线 |
| Agent Bus 与专家 Agent | **Beta internal** | 完成独立 Worker Pool、背压、DLQ 运维和容量压测 |
| 旧 Cognitive Runtime | **compatibility / experimental** | 不进入当前产品主路径；仅维护兼容合约 |

## 成熟度定义

- **Alpha**：核心能力可运行且有合约保护，但仍缺试点交付、安全和持续质量闭环。
- **Beta（当前）**：可用于受控企业试点，具备恢复、租户隔离、评测和运维合同；实际放量必须提供真实主链结果。
- **GA**：完成生产 SLO、备份恢复、安全评审、容量与升级策略，并持续通过发布门禁。
