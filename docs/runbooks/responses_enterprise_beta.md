# Responses 企业 Beta 发布手册

## 范围

Beta 覆盖 `/api/v2/responses` 的持久化创建、Worker 租约执行、RAG 与 DataAgent、
企业大脑上下文注入、SSE 续传、企业准入和实际 token/成本结算。旧 `/api/v1/chat`、
`/api/v1/tasks` 和 Cognitive Runtime 不在 Beta 主路径。

## 门禁

本地合同门禁用于开发反馈，不构成放量批准：

```bash
bash scripts/run_responses_beta_gate.sh --contract
```

发布门禁必须提供由真实 Responses E2E 运行产生的逐 case JSON；缺目录或缺 case 会失败：

```bash
ENTERPRISE_EVAL_RESULTS_DIR=/secure/eval-results \
  bash scripts/run_responses_beta_gate.sh --release
```

发布负责人还需保存 PostgreSQL/Redis 故障恢复、Worker 中止接管、SSE 断连续传、审批恢复、迁移 upgrade/downgrade 和备份恢复演练记录。评测输出和演练记录按租户审计策略留存。

## 放量与回滚

1. 先选择单一内部租户，限制每日 turn 与成本配额。
2. 观察完成率、P95 时延、租约恢复、RAG 引用质量、DataAgent 校验结果和成本偏差。
3. 任何租户隔离、重复副作用或事实丢失问题立即停止放量。
4. 回滚应用镜像时保留已提交 migration；按 [Responses 切换手册](chatgpt_cutover.md) 恢复 Worker，不删除 Response 或 Outbox。
