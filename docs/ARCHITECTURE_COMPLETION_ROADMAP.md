# Cognitive OS vNext — 分阶段全面完成规划

> 与 `ARCHITECTURE_REQUIREMENTS_MATRIX.md` 配套。每阶段结束跑 `scripts/run_vnext_final_tests.sh`。

## 阶段 0–1 — ✅ 已完成

- 瘦 Gateway + Dispatcher、`memory_injection`、V5 facade（run + stream）
- `test_kernel_import_boundaries.py`

## 阶段 2 — ✅ 基线已完成

- `kernel_goal_driven_dag_enabled`、`goal_driven_planner` / `try_build_goal_only_execution_graph`
- `cognitive_state/persistence.py` + fabric evolve flush
- `test_goal_driven_dag_contract.py`

## 阶段 3 — ✅ 基线已完成

- `memory_graph_redis.py` + hydrate/persist on bind & retrieve
- `test_memory_graph_redis_contract.py`

## 阶段 4 — ✅ 基线已完成

- `capability_runtime/dispatch_pipeline.py`（contract + outcomes → profiler）
- `test_capability_dispatch_pipeline.py`

## 阶段 5 — ✅ 基线已完成

- `governance/semantic_alerts.py` + `run_outcomes` export
- Staging phase strict via `app_env=staging`
- `test_semantic_metrics_alerts_contract.py`

## 阶段 6 — ✅ 文档与 CI（本轮）

| 项 | 状态 |
|----|------|
| V4 | `kernel/orchestrator_v4.py` 仅 re-export `legacy/v4`（勿扩展） |
| `dag_scheduler` | 仅 Kernel 插件并行 + 测试；主路径用 `execution/dag_engine` |
| README | vNext 主路径 + `run_vnext_final_tests.sh` |
| CI 套件 | 脚本纳入 phase 2–6 契约测试 |

### 仍可选的后续（非阻塞发布）

- 物理删除 `legacy/v4` 源码（v6）
- `kernel_capability_contract_strict` / Redis graph 生产默认开启
- import-linter 接入 CI

---

## 阶段 7 — ✅ 企业控制面与配置治理（本轮）

| 项 | 状态 |
|----|------|
| 配额 / 用量 Redis 可选镜像 | `enterprise_quota_redis_enabled` / `enterprise_usage_redis_enabled` |
| 异步预检 | `run_chat_preflight_async` → `evaluate_turn_async` |
| Turn 收尾 | `finalize_turn.post_turn_enterprise_accounting`（Gateway + stream） |
| 静默失败门禁 | `check_gateway_silent_failures.sh` + `check_kernel_silent_failures.sh` |
| Flag ↔ `.env.example` | `scripts/sync_env_example_to_docs.py` |
| Flag 文档生成 | `scripts/generate_feature_flag_docs.py` |
| 周检一键脚本 | `scripts/weekly_release_checklist.sh` |

### 仍可选的后续（非阻塞发布）

- 矩阵 ⚠️ 项：跨进程 World Model、多副本 cognitive state 强一致
- `docs/CONFIG_TRUTH.md` 段落级自动生成（当前以契约测试 + sync 脚本为主）
- DataAgent V2 产品级 clarification / verification UI 闭环

## 每周检查清单

一键执行：

```bash
bash scripts/weekly_release_checklist.sh
```

分项：

- [x] `bash scripts/run_vnext_final_tests.sh`
- [x] `bash scripts/run_enterprise_contract_tests.sh`
- [x] `pytest tests/test_architecture_requirements_alignment.py`
- [x] `bash scripts/check_import_boundaries.sh`（与 `test_kernel_import_boundaries` 对齐）
- [x] Gateway / kernel silent-failure guards
- [x] `PYTHONPATH=. python scripts/sync_env_example_to_docs.py`
- [x] 发布门禁文档：`docs/RELEASE_GATE.md`
- [ ] 矩阵 ⚠️ 项按环境逐步升为 ✅（外存 graph、跨进程 state）

## 架构债里程碑（负责人待填 @team）

| 债项 | 目标 | 验收 |
|------|------|------|
| 跨进程 World Model | Q3+ | 设计 doc + 契约 |
| 集群 cognitive state | staging persist → multi-replica | Redis 一致性测试 |
| 物理删除 `legacy/v4` | v6 | `run_vnext_final_tests` 绿 |
| import-linter 入 CI | ✅ 可选步骤 | `importlinter.ini` + `vnext-contract.yml`（continue-on-error） |