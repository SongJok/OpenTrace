# Runbook — 证据门禁失败（`kernel_evidence_contract_strict`）

## 症状

- 回合在 Executive / Fusion 阶段提前结束或返回「证据不足」类提示。
- `run_outcomes` 中 `governance` 标记 evidence 未通过。
- 测试：`test_stage4_grounding_and_annotations_contract` 等失败。

## 相关配置

| 变量 | 默认 | 说明 |
|------|------|------|
| `KERNEL_EVIDENCE_CONTRACT_STRICT` | true | 严格契约 |
| `RAG_MIN_EVIDENCE_SCORE` | 0.65 | 单条证据最低分 |
| `RAG_MIN_EVIDENCE_COUNT` | 2 | 最少证据条数 |
| `KERNEL_GOVERNANCE_EVIDENCE_GATE_ENABLED` | true | EvidenceGovernor 回合检查 |

权威说明见 `docs/CONFIG_TRUTH.md`。

## 排查顺序

1. 确认路径：RAG / Web / Data 是否实际产出 `Evidence` 并进入 `evidence_bus`。
2. 查日志关键词：`evidence_gate`、`min_evidence`、`EvidenceGovernor`。
3. 对 RAG：检查 `RAG_RERANK_ENABLED`、索引是否为空、HyDE/rewrite 是否过度改写查询。
4. 对 Data：检查 `data_source_id`、SQL 是否空结果（非门禁本身，但会导致无证据）。
5. 开发环境临时放宽（**勿用于生产**）：降低 `RAG_MIN_EVIDENCE_SCORE` 或关闭 `KERNEL_EVIDENCE_CONTRACT_STRICT`（需记录变更原因）。

## 用户可见策略

- 优先返回可操作的澄清或「未找到足够依据」而非无依据长文。
- 与 `kernel_governance_risk_gate_enabled` 叠加时，先证据后风险。

## 相关文档

- `docs/adr/002-governance-layers.md`
- `docs/runbooks/turn-trace.md`