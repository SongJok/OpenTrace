"""
plugins/tool — 与「工具型能力」相关的注册入口说明。

实际注册发生在 FastAPI lifespan 中导入的模块：
  - `tools.builtin_tools.builtins` — 计算器、搜索、python_repl 等
  - `tools.builtin_tools.analytics_tools` — code_interpreter / chart_generator / data_analysis / file_sandbox

结构化元数据（JSON Schema 风格）见 `plugins.structured_tool`。
内核通过 `ToolRouter` + `kernel/orchestrator.py` 的 EXECUTE 步骤按名或意图调用。
"""

from plugins.structured_tool import (
    CHART_GENERATOR_SPEC,
    CODE_INTERPRETER_SPEC,
    DATA_ANALYSIS_SPEC,
    FILE_SANDBOX_SPEC,
)

__all__ = [
    "CODE_INTERPRETER_SPEC",
    "CHART_GENERATOR_SPEC",
    "DATA_ANALYSIS_SPEC",
    "FILE_SANDBOX_SPEC",
]
