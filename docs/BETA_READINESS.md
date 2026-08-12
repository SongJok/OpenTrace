# OpenTrace 受控企业 Beta 就绪说明

## 结论与范围

OpenTrace 产品主路径自 2026-08-08 起进入 **受控企业 Beta**。Beta 范围是以 `/chat` 为入口的
`/api/v2/responses` 持久化执行、企业大脑上下文、企业知识与 RAG、DataAgent、数据库、
个人记忆、任务、Skills、设置，以及管理员治理页面。它表示代码和运维合同可以支持受控租户
试点，不等同于无条件生产承诺或 GA。

旧 Cognitive Runtime 继续保持 compatibility/experimental，不进入产品支持面。GA 仍要求长期
SLO、容量压测、备份恢复演练、安全评审、跨版本升级与至少一个季度的试点运行数据。

## Beta 不变量

1. 在线命令只进入 `/api/v2/responses`；API 不执行模型和工具。
2. PostgreSQL 是 Response、事件、审批和工具账本的事实来源，Redis 仅负责投递与唤醒。
3. 所有资源访问同时限定 user、tenant、workspace，并继续执行数据源授权。
4. 在线问答仅允许 RAG 与 DataAgent；企业大脑只作为授权上下文注入，不暴露为工具。
5. 数据库 Schema 元数据与业务 SQL 结果使用不同预算：同步端分批读取最多 100,000 张表和
   1,000,000 个列记录，页面按 100 张分页并支持搜索与按库筛选，不再被 DataAgent 的 500 行
   上限静默截断。
6. 达到任何安全预算必须显式返回截断状态和运维提示，不能把下限统计呈现为完整结果。

## 发布门禁

本地合同门禁验证代码、架构、迁移单头、全量后端、企业边界、前端全量测试和生产构建：

```bash
bash scripts/run_product_beta_gate.sh --contract
```

受控租户放量必须提供真实 Responses 主链 Golden Results；fixture 只验证评测器合同：

```bash
ENTERPRISE_EVAL_RESULTS_DIR=/secure/real-results \
  bash scripts/run_product_beta_gate.sh --release
```

发布负责人还应归档 PostgreSQL/Redis 故障恢复、Worker 接管、SSE 续传、审批恢复、迁移、备份
恢复与 Schema 大目录容量验证证据。任何租户越权、事实丢失或重复副作用问题都必须停止放量。
