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

发布门禁必须提供由真实 Responses E2E 运行产生的逐 case JSON，以及绑定当前候选提交的
端到端容量报告；缺目录、缺 case、缺少主链溯源字段或容量证据过期都会失败。每个
`<case_id>.json` 必须使用以下封套，`output` 才是被断言的结构化结果：

```json
{
  "schema_version": 1,
  "case_id": "production-bug-evidence-chain",
  "source": "responses_v2",
  "response_id": "resp_...",
  "captured_at": "2026-08-20T12:00:00+08:00",
  "output": {}
}
```

合同模式只检查 JSONL 结构、唯一 ID、断言类型和阈值范围，不执行 case、不会生成通过率，
也不能用作放量证据：

```bash
python scripts/run_enterprise_evals.py --validate-contracts
```

真实结果评测命令：

```bash
ENTERPRISE_CAPACITY_REPORT=/secure/capacity-<revision>.json \
ENTERPRISE_EVAL_RESULTS_DIR=/secure/eval-results \
  bash scripts/run_responses_beta_gate.sh --release
```

容量采集和固定发布底线见 [Responses 容量与发布证据手册](responses_capacity.md)。正式容量
运行必须使用 HTTPS staging、多场景 JSONL 工作负载和当前提交摘要；单次 POST 的 2xx 不代表
完成，不能作为容量证据。

发布负责人还需保存 PostgreSQL/Redis 故障恢复、Worker 中止接管、SSE 断连续传、审批恢复、迁移 upgrade/downgrade 和备份恢复演练记录。评测输出和演练记录按租户审计策略留存。

## 放量与回滚

1. 先选择单一内部租户，限制每日 turn 与成本配额。
2. 观察完成率、P95 时延、租约恢复、RAG 引用质量、DataAgent 校验结果和成本偏差。
3. 任何租户隔离、重复副作用或事实丢失问题立即停止放量。
4. 回滚应用镜像时保留已提交 migration；按 [Responses 切换手册](chatgpt_cutover.md) 恢复 Worker，不删除 Response 或 Outbox。
