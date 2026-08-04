# OpenTrace 项目摘要

OpenTrace 当前定位为 **AI 原生企业组织操作系统**。产品整体仍为 Alpha，`/api/v2/responses` 主链与“数据洞察、月报、经营简报”第一灯塔进入受控企业 Beta。近期工程优先级是用真实业务闭环提升可交付性，而不是继续扩张认知模块数量。

## 当前产品闭环

1. 企业数据库问题 → 授权数据源 → 只读 Text2SQL → 校验与证据化答案。
2. 企业文档 → 编译/审核/发布 → RAG 检索 → 带引用回答。
3. 分析结论 → 持久化审批 → 定时任务或主动预警 → 审计与通知。
4. 报告定义 → 周期 Response → DataAgent/RAG/图表 → 工具账本证据投影 → 人工复核与通知。

## 工程单一真相

- 在线入口：`POST /api/v2/responses`。
- 执行进程：Agent Worker；API 不运行模型或工具。
- 事实来源：PostgreSQL Response / Item / Event / Outbox / Approval / Tool ledger。
- 投递层：Redis Streams，可丢失且可由数据库 claim 恢复。
- Manager：`kernel/agent_loop/runner.py`，模型调用统一经过 Model Gateway。
- 兼容子系统：旧 Cognitive Runtime，仅用于明确的兼容任务。

完整架构见 `docs/architecture_overview.md`，机器可读清单见 `docs/architecture/runtime_manifest.yaml`。

## P0 工程基线

- Python 3.11 为发布基准，Python 3.12 为兼容矩阵。
- Python 与前端依赖必须从锁文件安装。
- PR 快速门禁覆盖格式、lint、类型、架构、配置、迁移单头、关键 Responses 合约和前端 TypeScript/Vitest。
- 完整门禁使用真实 PostgreSQL 验证迁移 upgrade、downgrade、重复执行和生产基线升级。
- 安全门禁覆盖依赖漏洞、密钥泄露、容器镜像和 SBOM。
- 已提交 Alembic 历史保持不可变；2026 年 7 月 24 日之后的新 revision 使用无日期单调序列。

## 明确不在 P0 扩张的范围

暂停新增 Cognitive Engine、Agent 类型、世界模型和独立功能开关。新需求必须直接服务 Responses、DataAgent、RAG、审批、主动预警，或提升上述主路径的质量、安全和可交付性。
