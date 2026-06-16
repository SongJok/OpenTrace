# ADR-002: 双层 Governance

## 状态

已接受

## 背景

存在顶层 `governance/` 包与 `kernel/governance/GovernanceCenter`。

## 决策

- **顶层 `governance/`**：可复用 governor 实现、`semantic_metrics`、`adaptive_risk_engine`、`execution_guardrails`。
- **`kernel/governance/`**：vNext 回合内通过 `GovernanceCenter.evaluate_turn()` 编排 evidence/risk/audit/cognitive health。
- **`CognitiveSupervisor`**：在 `prepare_run` / `dispatch_enrichment` 预检；**`run_outcomes`** 导出 semantic health / alerts。

## 排障顺序

1. 查回合 metadata 中 `governance` / `adaptive_risk_*` / `semantic_observability`。
2. 若证据不足：查 `kernel_evidence_contract_strict` 与 `EvidenceGovernor`。
3. 若被 capability 拒绝：查 `CapabilityGovernor` 与 `kernel_registry_dispatch_strict`。
4. 顶层与 kernel 包**不是**两套独立策略，而是同一实现的不同导入面。

## 验证

`tests/test_semantic_metrics_alerts_contract.py`、`test_cognitive_supervisor_contract.py`