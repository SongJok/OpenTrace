# Legacy Cognitive Runtime compatibility boundary

旧 `CognitiveKernel → CognitiveSupervisor → RuntimeGateway` 只允许通过
`architecture/legacy_runtime_allowlist.txt` 中冻结的适配器继续存在。新业务不得新增依赖；在线会话必须
进入 `/api/v2/responses` 与 `kernel/agent_loop/runner.py`。兼容层计划在连续两个正式版本无调用、回放
与回滚演练通过后删除。
