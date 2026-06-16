# ADR-001: vNext 为唯一默认执行路径

## 状态

已接受（2026-06）

## 背景

系统曾以 V4 Plan+Dispatcher 为主；现以 Cognitive Runtime V2 + CognitiveSupervisor 为主路径。

## 决策

1. 默认 `kernel_orchestrator_v4_enabled=false`。
2. 入口：`CognitiveKernel` → `CognitiveSupervisor.prepare_run` → `RuntimeGateway`（仅 dispatch）→ `RuntimeTurnDispatcher` → registry handlers。
3. V4 代码仅通过 `legacy/v4` 与 `kernel/orchestrator_v4.py` re-export 访问；禁止扩展 re-export 文件。
4. `RuntimeGateway` 不得调用 `evaluate_turn`、不得构建最终 artifact（由 `run_outcomes` 负责）。

## 禁止 bypass

- 在 `kernel/runtime_gateway.py`、`kernel/cognitive_supervisor/*`、`kernel/runtime/runtime_turn_dispatcher.py` 中导入 `orchestrator_v4`。
- 在 agents 中导入 `cognitive_kernel`。

## 验证

`tests/test_kernel_import_boundaries.py`、`bash scripts/run_vnext_final_tests.sh`