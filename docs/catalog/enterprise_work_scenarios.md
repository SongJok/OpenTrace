# 企业日常工作场景目录

## 目标

企业工作台不能只展示模块入口，还要回答三个员工问题：

1. 我现在能让 AI 完成什么工作？
2. 开始前还缺哪些企业上下文、知识、数据、Skill 或权限？
3. 这项工作的记忆、证据、审批和最终交付如何验收？

OpenTrace 用 `services/enterprise_scenarios.py` 维护确定性的场景目录，并由
`services/enterprise_workbench.py` 根据 PostgreSQL 事实状态生成当前用户、租户和工作区的
场景投影。目录不执行模型或工具，不形成第二套 Runtime；可用场景最终仍进入 Responses、
Goal、Skill 和 typed tools 主链路。

同一总览中的 Project 工作组合由 `services/workbench_portfolio.py` 生成。它负责把场景启动后
形成的 Responses、Goal、审批、自动化和预警重新收敛到 Project，并给出可追溯下一步；它不
修改本目录的前置条件、工具、审批或证据合同。

## 对标结论与设计取舍

- WorkBuddy 的有效产品模式是用日常语言发起完整工作、由专家和工具产出可验收交付物，并用
  MCP 与自定义 Skill 扩展能力。OpenTrace 对应补齐“场景—交付物—能力链”的可发现入口。
- Codex 的有效扩展模式是用 Skill 固化可复用工作流，用 MCP/Connector 连接外部系统，并把
  持久指令、工具执行、审批和自动化分层。OpenTrace 对应保持 Project 指令、Skill、typed
  tool、Goal/定时任务各自的最小职责。
- 企业场景不能是绕过治理的快捷按钮。前端只预填可审查提示词；写操作继续由 Worker 创建
  `ResponseApproval`，批准后通过工具账本和幂等键执行。

## 场景合同

每个场景必须声明：

| 字段 | 合同 |
| --- | --- |
| `prerequisites` | `project / knowledge / data / skill`，由服务端事实状态判定 |
| `capabilities` | Agent Topology Manifest 中的规范能力类型 |
| `tools` | Tool Registry 中存在的 typed tool 名称 |
| `memory_scope` | `conversation / user / project`，禁止场景自行扩大范围 |
| `risk` | `read / mixed / write` |
| `approval_policy` | `none / required_before_write / inherited` |
| `evidence_requirements` | 对知识引用、数据依据、检查点或触发证据的最低要求 |
| `deliverables` | 员工可以验收的最终产物，而非内部执行步骤 |

投影状态：

- `setup_required`：前置条件缺失，`action_route` 指向第一个可处理缺口。
- `ready`：可以从工作台直接进入对话或 Goal/Skills 页面。
- `active`：Goal、定时任务、主动预警或 Skill 已存在，入口切换到运行管理页面。

组织工作台模板在状态判定之后应用。模板按员工的有效部门、岗位、用户组关系匹配，并可继承
上级部门；多个模板按管理员优先级合并有序 `scenario_ids`。模板只重排目录并记录
`organization_recommended` 与 `recommendation_reason`，不能修改前置条件、启动路由、工具、
记忆范围、证据要求或审批策略。没有匹配模板时继续使用目录默认推荐。

## 当前场景矩阵

| 场景 | 主能力/工具 | 记忆 | 审批 | 核心交付 |
| --- | --- | --- | --- | --- |
| 可信制度与流程问答 | `document_retrieval` | conversation | 只读免审批 | 结论、步骤、知识引用 |
| 经营指标复盘 | `data_query`、`data_analysis`、`chart_generator` | project | 只读免审批 | 指标表、异常、建议 |
| 跨知识与数据决策简报 | `document_retrieval + data_query` | project | 只读免审批 | 决策摘要、方案、风险 |
| 日程与专注计划 | `list/create/update_calendar_event` | user | 写入前审批 | 冲突、专注计划、待审批变更 |
| 长期 Goal 推进 | Goal → Responses | project | 副作用继承审批 | 阶段成果、检查点、验收 |
| 周期经营简报 | `create_scheduled_task` | project | 写入前审批 | 周期简报、通知、失败记录 |
| 关键指标主动预警 | `create_data_alert` | project | 写入前审批 | 预警规则、证据、行动项 |
| 复用公司标准流程 Skill | `skill_execution` | project | 副作用继承审批 | 一致流程、清单、来源 |

## 业务过程

```text
工作台读取作用域内事实状态
  → 服务端判定场景前置条件和采用状态
  → 员工选择场景
  → 缺能力：进入 Project / Documents / Databases / Skills 配置
  → 已就绪：预填任务并进入 Responses，或进入 Goal / Skills
  → Manager 选择最小能力集合
  → 只读工具自动执行；写/破坏性工具创建持久化审批
  → 输出携带证据、工具结果和状态事件
  → 完成后按 user/project/conversation 规则学习记忆
  → 工作台投影最近工作、审批、预警和采用状态
```

## 验收

场景不是静态营销文案，必须同时通过以下验证：

```bash
python -m pytest -q tests/test_enterprise_work_scenarios_contract.py
python -m pytest -q tests/test_enterprise_workbench_templates.py
python -m pytest -q tests/test_workbench_portfolio.py
python scripts/run_enterprise_evals.py --minimum-pass-rate 1.0
cd frontend && npm test -- src/pages/__tests__/WorkPage.contract.test.tsx
npm test -- src/components/__tests__/WorkbenchPortfolio.test.tsx
bash scripts/run_enterprise_contract_tests.sh
```

`evals/datasets/workbench.jsonl` 定义知识引用、只读问数、日历审批、定时任务幂等、预警
证据和 Skill 治理六类可替换生产结果的 Golden Dataset 合同。
