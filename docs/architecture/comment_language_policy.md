# 代码注释语言规范

## 约定

- **新增与修改的模块级 docstring、类/函数说明**：优先使用**简体中文**。
- **标识符**（类名、函数名、配置键、协议字段）保持英文，与 API/契约一致。
- **行内 `#` 注释**：在 vNext 认知栈（`kernel/cognitive_supervisor`、`kernel/goal`、`kernel/runtime/capability_governance`、`governance/`、`memory/fabric/`、`services/data_intelligence_runtime`、`legacy/v4`）已逐步中文化；全仓库其余目录按模块迭代。

## 已完成中文化的区域（本轮）

| 区域 | 说明 |
|------|------|
| `kernel/runtime_gateway.py` | 模块说明 |
| `kernel/cognitive_supervisor/*` | 监督层 |
| `kernel/goal/*` | 目标状态机、调度、绑定、回放 |
| `kernel/runtime/capability_governance.py` | 能力治理 |
| `kernel/context_fabric*.py` | 上下文织网 |
| `kernel/cognition/planner_facade.py` | 三层规划门面 |
| `governance/*.py` | 顶层治理包 |
| `kernel/governance/*.py` | 内核治理镜像 |
| `kernel/protocol/runtime_contract.py` 等 | 契约与协议 |
| `memory/fabric/*` | 记忆关系 |
| `services/data_intelligence_runtime` | 数据智能运行时 |
| `legacy/v4` | V4 遗留 |

## 未覆盖（需分阶段）

- `kernel/orchestrator_v4` 薄壳、`agents/*` 大文件、`execution/*`、`gateway/*`、历史测试中的英文说明
- 第三方风格注释、OpenAPI 描述、README 英文段落（文档可中英并存）

## 本轮补充

- `kernel/runtime/cognitive_executive.py`：模块说明、阶段 1–11.5、行内注释、结果类 docstring 已中文化
- `kernel/runtime/multi_question_runtime.py`、`kernel/cognition/multi_execution_planner.py` 模块说明已中文化
- `agents/worker.py`、`agents/registry.py`、`agents/base.py` 及 vision/rule/skills/data_agent_v2 模块说明
- `agents/data_agent_v2/types.py`、各 V2 Agent 模块头；`kernel/data_cognition/*` 模块 docstring
- `execution/dag_engine/*`、`execution/tool_router`、`execution/workflow_engine`
- `gateway/.../chat.py`、`gateway/.../rules.py`
- `tests/test_*vnext*`、`test_cognitive_supervisor_contract` 等 vNext 契约测试模块说明

## 批量检查（可选）

```bash
rg '^"""[A-Za-z]' kernel governance memory/fabric services/data_intelligence_runtime legacy
```

将输出仍含英文开头的模块 docstring，便于排期下一批翻译。