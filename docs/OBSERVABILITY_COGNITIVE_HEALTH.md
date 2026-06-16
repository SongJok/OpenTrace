# 认知健康指标（Semantic OS）

来源：`governance/semantic_metrics.py` + `semantic_metrics_pipeline` + `run_outcomes` 导出。

## CognitiveHealthSnapshot（8 维）

| 维度 | 含义（启发式） |
|------|----------------|
| reasoning_drift | 推理链相对历史漂移 |
| goal_stability | 目标图变更频率 |
| capability_entropy | 能力选择分散度 |
| memory_pollution_risk | 记忆注入噪声风险 |
| evidence_integrity | 证据置信与数量 |
| planner_volatility | 重规划次数 |
| runtime_recovery_score | 失败恢复成功率 |
| cognitive_saturation | 预算/上下文饱和 |

## 告警

`kernel_semantic_alerts_enabled=true` 时，`semantic_alerts` 写入回合 metadata。

## Prometheus / OTel

- `TRACE_ENABLED=true`，`OTEL_EXPORTER_OTLP_ENDPOINT` 指向 collector。
- 启动：`bash start.sh --with-observability` → Prometheus `14190`，Jaeger `14186`。

## 建议阈值（草案，按环境校准）

- `evidence_integrity` 持续低于 0.5 → 查 RAG/文档索引。
- `planner_volatility` 高 → 查 refine_replan 与 DAG 失败类型。
- `cognitive_saturation` 高 → 开启 context compressor 或提高 token 预算。

契约：`tests/test_semantic_metrics_alerts_contract.py`