"""企业日常工作场景目录与准备度投影。

场景目录只描述如何使用现有 Responses、Goal、工具、Skill 和记忆能力，不执行模型或
副作用。它把“能做什么”转换为员工可直接发起、管理员可验证的业务过程合同。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ScenarioStatus = Literal["ready", "setup_required", "active"]


@dataclass(frozen=True, slots=True)
class EnterpriseScenarioDefinition:
    id: str
    category: str
    title: str
    description: str
    launch_mode: Literal["chat", "goal", "skills", "report"]
    launch_route: str
    starter_prompt: str
    prerequisites: tuple[str, ...]
    capabilities: tuple[str, ...]
    tools: tuple[str, ...]
    memory_scope: Literal["conversation", "user", "project"]
    risk: Literal["read", "mixed", "write"]
    approval_policy: Literal["none", "required_before_write", "inherited"]
    evidence_requirements: tuple[str, ...]
    deliverables: tuple[str, ...]
    adoption_signal: Literal["goal", "task", "alert", "skill"] | None = None
    active_route: str | None = None


_PREREQUISITES = {
    "project": {
        "code": "project_required",
        "title": "先建立业务 Project",
        "description": "Project 用于固定业务指令、数据权限和项目记忆边界。",
        "route": "/work?tab=projects",
    },
    "knowledge": {
        "code": "published_knowledge_required",
        "title": "先发布可信企业知识",
        "description": "场景需要可访问且已发布的知识来源，结论才能附带企业引用。",
        "route": "/documents",
    },
    "data": {
        "code": "active_data_source_required",
        "title": "先连接授权企业数据",
        "description": "场景需要当前员工有 query 权限的有效数据源。",
        "route": "/databases",
    },
    "skill": {
        "code": "governed_skill_required",
        "title": "先安装或发布一个 Skill",
        "description": "将稳定流程沉淀为可审计 Skill，并在具体会话中显式启用。",
        "route": "/skills",
    },
}


ENTERPRISE_SCENARIO_CATALOG: tuple[EnterpriseScenarioDefinition, ...] = (
    EnterpriseScenarioDefinition(
        id="trusted_knowledge_answer",
        category="知识协作",
        title="可信制度与流程问答",
        description="从已发布企业知识回答制度、流程和职责问题，并在结论后给出引用。",
        launch_mode="chat",
        launch_route="/chat",
        starter_prompt=(
            "请根据已发布的企业知识回答我的问题。先给直接结论，再列出适用范围、执行步骤、"
            "例外情况和来源引用；证据不足或资料冲突时不要猜测，请明确指出缺口。\n\n我的问题："
        ),
        prerequisites=("knowledge",),
        capabilities=("document_retrieval",),
        tools=(),
        memory_scope="conversation",
        risk="read",
        approval_policy="none",
        evidence_requirements=("已发布知识引用", "冲突与证据不足说明"),
        deliverables=("直接结论", "执行步骤", "来源引用"),
    ),
    EnterpriseScenarioDefinition(
        id="business_metric_review",
        category="数据决策",
        title="经营指标复盘",
        description="在授权数据源内完成只读分析、口径解释、异常定位和可视化建议。",
        launch_mode="report",
        launch_route="/reports?type=data_insight",
        starter_prompt=(
            "请对以下经营问题做一次可复核的数据分析：先确认指标口径和时间范围，再使用授权数据源"
            "查询；返回关键指标、同比/环比、异常切片、SQL 或查询依据、风险提示和下一步建议。"
            "不要执行任何数据写入。\n\n经营问题："
        ),
        prerequisites=("data",),
        capabilities=("data_query", "tool"),
        tools=("data_analysis", "chart_generator"),
        memory_scope="project",
        risk="read",
        approval_policy="none",
        evidence_requirements=("授权数据源", "只读 SQL 或查询依据", "指标口径"),
        deliverables=("指标表", "异常解释", "行动建议"),
    ),
    EnterpriseScenarioDefinition(
        id="decision_brief",
        category="管理协作",
        title="跨知识与数据决策简报",
        description="合并企业制度、项目背景和实时数据，形成可追溯的管理决策材料。",
        launch_mode="report",
        launch_route="/reports?type=management_brief",
        starter_prompt=(
            "请围绕以下决策问题生成一份管理简报。分别检索企业知识和授权业务数据，区分事实、"
            "推断与建议，列出关键指标、制度约束、可选方案、风险、待确认事项和来源；不要把未发布"
            "资料或个人记忆当作公司事实。\n\n决策问题："
        ),
        prerequisites=("project", "knowledge", "data"),
        capabilities=("document_retrieval", "data_query"),
        tools=("data_analysis", "chart_generator"),
        memory_scope="project",
        risk="read",
        approval_policy="none",
        evidence_requirements=("知识引用", "数据查询依据", "事实与推断分离"),
        deliverables=("决策摘要", "方案对比", "风险与待确认项"),
    ),
    EnterpriseScenarioDefinition(
        id="calendar_focus_plan",
        category="个人效能",
        title="日程与专注计划",
        description="读取个人日历安排工作重点；任何新增、修改或取消日程都先等待人工审批。",
        launch_mode="chat",
        launch_route="/chat",
        starter_prompt=(
            "请先读取我未来 7 天的个人日历，识别冲突、碎片时间和关键截止点，然后给出本周专注"
            "计划。先展示建议；只有我明确确认后，才创建或修改日程。"
        ),
        prerequisites=(),
        capabilities=("tool",),
        tools=("list_calendar_events", "create_calendar_event", "update_calendar_event"),
        memory_scope="user",
        risk="mixed",
        approval_policy="required_before_write",
        evidence_requirements=("个人日历事实", "明确时间范围"),
        deliverables=("冲突清单", "专注计划", "待审批日程变更"),
    ),
    EnterpriseScenarioDefinition(
        id="long_running_goal",
        category="持续工作",
        title="长期 Goal 推进",
        description="把跨小时或跨天的工作交给可恢复 Goal，并以成功标准和检查点持续推进。",
        launch_mode="goal",
        launch_route="/work?tab=goals",
        starter_prompt="",
        prerequisites=("project",),
        capabilities=("tool", "document_retrieval", "data_query"),
        tools=(),
        memory_scope="project",
        risk="mixed",
        approval_policy="inherited",
        evidence_requirements=("成功标准", "持久化检查点", "Response 事件"),
        deliverables=("阶段成果", "检查点", "最终验收"),
        adoption_signal="goal",
        active_route="/work?tab=goals",
    ),
    EnterpriseScenarioDefinition(
        id="recurring_management_brief",
        category="持续工作",
        title="周期经营简报",
        description="按固定时间运行完整 Agent Loop，生成经营简报并投递持久化通知。",
        launch_mode="report",
        launch_route="/reports?type=management_brief",
        starter_prompt=(
            "请为当前 Project 创建一个每周经营简报任务：每周一 09:00 读取授权数据，汇总上周"
            "核心指标、异常、风险和建议，并保留查询依据。先给出任务标题、完整提示词和时间规则，"
            "等待我审批后再创建。"
        ),
        prerequisites=("project", "data"),
        capabilities=("data_query", "tool"),
        tools=("create_scheduled_task",),
        memory_scope="project",
        risk="write",
        approval_policy="required_before_write",
        evidence_requirements=("授权数据源", "确定性时间规则", "运行事件"),
        deliverables=("周期简报", "持久化通知", "失败可重试记录"),
        adoption_signal="task",
        active_route="/reports",
    ),
    EnterpriseScenarioDefinition(
        id="metric_risk_monitor",
        category="风险治理",
        title="关键指标主动预警",
        description="由 Data Agent 只读取数，确定性阈值代码判断异常，并把证据送入行动中心。",
        launch_mode="chat",
        launch_route="/chat",
        starter_prompt=(
            "请为以下关键指标设计主动预警。先确认数据源、指标列、聚合方式、阈值、严重级别、"
            "检查频率和时区，展示完整规则；只有我确认后才创建并启用。\n\n监控目标："
        ),
        prerequisites=("project", "data"),
        capabilities=("data_query", "tool"),
        tools=("create_data_alert",),
        memory_scope="project",
        risk="write",
        approval_policy="required_before_write",
        evidence_requirements=("授权数据源", "确定性阈值", "触发证据"),
        deliverables=("预警规则", "异常事件", "行动中心待办"),
        adoption_signal="alert",
        active_route="/alerts",
    ),
    EnterpriseScenarioDefinition(
        id="governed_skill_workflow",
        category="能力复用",
        title="复用公司标准流程 Skill",
        description="安装受审查 Skill，或从企业资料蒸馏指令型 Skill，在会话中显式启用后复用。",
        launch_mode="skills",
        launch_route="/skills",
        starter_prompt="",
        prerequisites=("skill",),
        capabilities=("skill_execution",),
        tools=(),
        memory_scope="project",
        risk="mixed",
        approval_policy="inherited",
        evidence_requirements=("Skill 来源与版本", "企业资料哈希", "会话显式启用"),
        deliverables=("一致流程", "检查清单", "可审计来源"),
        adoption_signal="skill",
        active_route="/skills",
    ),
)


def build_enterprise_scenarios(
    *,
    project_count: int,
    published_knowledge_count: int,
    active_data_source_count: int,
    installed_skill_count: int,
    company_skill_count: int,
    active_goal_count: int,
    active_task_count: int,
    active_alert_count: int,
) -> list[dict[str, object]]:
    """按当前事实状态生成可行动的企业场景，不在前端猜测准备度。"""

    available = {
        "project": project_count > 0,
        "knowledge": published_knowledge_count > 0,
        "data": active_data_source_count > 0,
        "skill": installed_skill_count + company_skill_count > 0,
    }
    adopted = {
        "goal": active_goal_count > 0,
        "task": active_task_count > 0,
        "alert": active_alert_count > 0,
        "skill": installed_skill_count + company_skill_count > 0,
    }
    scenarios: list[dict[str, object]] = []
    available_indexes: list[int] = []
    for definition in ENTERPRISE_SCENARIO_CATALOG:
        missing = [key for key in definition.prerequisites if not available[key]]
        blockers = [dict(_PREREQUISITES[key]) for key in missing]
        is_active = bool(
            definition.adoption_signal and adopted.get(definition.adoption_signal, False)
        )
        status: ScenarioStatus = "setup_required" if missing else "active" if is_active else "ready"
        action_route = (
            str(blockers[0]["route"])
            if blockers
            else (
                definition.active_route
                if status == "active" and definition.active_route
                else definition.launch_route
            )
        )
        action_label = (
            "完成配置"
            if status == "setup_required"
            else "查看运行" if status == "active" else "开始工作"
        )
        scenarios.append(
            {
                "id": definition.id,
                "category": definition.category,
                "title": definition.title,
                "description": definition.description,
                "status": status,
                "recommended": False,
                "organization_recommended": False,
                "recommendation_reason": None,
                "launch_mode": definition.launch_mode,
                "action_route": action_route,
                "action_label": action_label,
                "starter_prompt": definition.starter_prompt,
                "capabilities": list(definition.capabilities),
                "tools": list(definition.tools),
                "memory_scope": definition.memory_scope,
                "risk": definition.risk,
                "approval_policy": definition.approval_policy,
                "approval_required": definition.approval_policy == "required_before_write",
                "evidence_requirements": list(definition.evidence_requirements),
                "deliverables": list(definition.deliverables),
                "blockers": blockers,
            }
        )
        if status != "setup_required":
            available_indexes.append(len(scenarios) - 1)

    for index in available_indexes[:3]:
        scenarios[index]["recommended"] = True
    return scenarios


def apply_organization_templates(
    scenarios: list[dict[str, object]],
    templates: list[dict[str, Any]],
) -> list[dict[str, object]]:
    """按已匹配模板重排场景；只改变发现投影，不改变准备度和执行语义。"""

    if not templates:
        return scenarios

    scenarios_by_id = {str(item["id"]): item for item in scenarios}
    ordered_ids: list[str] = []
    sources: dict[str, list[str]] = {}
    for template in templates:
        template_name = str(template.get("name") or "组织工作台")
        for raw_id in template.get("scenario_ids") or []:
            scenario_id = str(raw_id)
            if scenario_id not in scenarios_by_id:
                continue
            if scenario_id not in ordered_ids:
                ordered_ids.append(scenario_id)
            names = sources.setdefault(scenario_id, [])
            if template_name not in names:
                names.append(template_name)

    ordered_ids.extend(item_id for item_id in scenarios_by_id if item_id not in ordered_ids)
    ordered = [scenarios_by_id[item_id] for item_id in ordered_ids]
    recommended_count = 0
    for item in ordered:
        item["recommended"] = False
        source_names = sources.get(str(item["id"]), [])
        item["organization_recommended"] = bool(source_names)
        item["recommendation_reason"] = "、".join(source_names) if source_names else None
        if source_names and item["status"] != "setup_required" and recommended_count < 3:
            item["recommended"] = True
            recommended_count += 1

    if recommended_count < 3:
        for item in ordered:
            if item["status"] == "setup_required" or item["recommended"]:
                continue
            item["recommended"] = True
            recommended_count += 1
            if recommended_count == 3:
                break
    return ordered
