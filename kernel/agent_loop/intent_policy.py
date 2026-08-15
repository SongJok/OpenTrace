"""Responses 五源意图的确定性校正与规划模型故障回退。"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from typing import Any, TypeVar

from kernel.agent_loop.contracts import (
    DataIntentStage,
    EvidenceRequirement,
    ExecutionPlan,
    ExecutionStep,
    FreshnessRequirement,
    InformationSource,
    IntentPlan,
    PlanningDecision,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.write_intent import is_contextual_follow_up

_DATA_MEASURE_RE = re.compile(
    r"销售|营收|收入|流水|金额|成本|利润|毛利|订单|客户数|用户数|会员数|人数|库存|"
    r"退款|支付|转化|留存|复购|活跃|流失|客单价|单量|销量|gmv|revenue|"
    r"conversion|retention|churn|order|customer|inventory",
    re.IGNORECASE,
)
_DATA_OPERATION_RE = re.compile(
    r"多少|几(?:个|人|笔|单)|查询|统计|计算|分析|对比|比较|趋势|同比|环比|排名|"
    r"top\s*\d*|明细|列出|分布|占比|平均|合计|总计|最高|最低|异常|实际数据|"
    r"how many|count|calculate|compare|trend|breakdown|list",
    re.IGNORECASE,
)
_DATA_TIME_RE = re.compile(
    r"今天|昨日|昨天|本周|上周|本月|上月|本季|上季|今年|去年|最近|过去|截至|"
    r"\d{4}\s*年|\d{1,2}\s*月|today|yesterday|this month|last month|year to date",
    re.IGNORECASE,
)
_DATA_EXPLICIT_RE = re.compile(
    r"问数|查数|经营数据|业务数据|实时数据|sql\s*(?:查询|草案|候选)|"
    r"query\s+(?:the\s+)?database",
    re.IGNORECASE,
)
_DEFINITION_ONLY_RE = re.compile(
    r"(?:口径|定义|含义|意思|计算方式|计算规则|业务规则|流程|制度|政策)"
    r".{0,8}(?:是什么|有哪些|说明|解释|怎么走|如何)?\s*[？?]?$|"
    r"(?:问数|查数|数据库|数据源|sql).{0,12}(?:是什么|怎么配置|如何配置)|"
    r"what (?:is|does).{0,30}(?:mean|definition)",
    re.IGNORECASE,
)
_PERSONAL_CONTEXT_RE = re.compile(
    r"我的|我叫|记得我|称呼我|我偏好|我喜欢|我通常|我习惯|关于我|"
    r"my preference|remember me|about me",
    re.IGNORECASE,
)
_HISTORICAL_RE = re.compile(
    r"昨日|昨天|上周|上月|上季|去年|历史|过去|同比|环比|\d{4}\s*年|\d{1,2}\s*月|"
    r"yesterday|last (?:week|month|quarter|year)|historical",
    re.IGNORECASE,
)
_MATERIAL_AMBIGUITY_RE = re.compile(
    r"sql[_ -]?candidate|candidate[_ -]?selection|multiple[_ -]?(?:candidate|target)|"
    r"source[_ -]?conflict|conflicting|permission|authorization|approval|destructive|"
    r"ambiguous[_ -]?(?:goal|action|output|target|recipient|time|range|metric|account|version)|"
    r"missing[_ -]?(?:goal|action|output|target|recipient|time|range|metric|account|identifier)|"
    r"候选|选择哪|请选择|多个(?:目标|对象|账户|数据源|指标)|冲突|不一致|权限|授权|审批|"
    r"写入|删除|破坏性|缺少(?:目标|操作|用途|期望输出|对象|收件人|时间|范围|指标|账户|标识)|"
    r"(?:哪个|哪一个|哪项|确认).{0,10}(?:目标|对象|收件人|时间|范围|指标|账户|数据源|版本)",
    re.IGNORECASE,
)
_RECOVERABLE_AMBIGUITY_RE = re.compile(
    r"capability[_ -]?unavailable|tool[_ -]?unavailable|source[_ -]?unavailable|"
    r"insufficient[_ -]?(?:context|information)|missing[_ -]?(?:context|source|document|antecedent)|"
    r"无法(?:访问|读取|获取)|不能(?:访问|读取|获取)|能力不支持|能力不可用|工具不可用|"
    r"缺少(?:上下文|资料|信息来源|文档)|未提供(?:资料|文档)|请提供(?:资料|文档|页面)",
    re.IGNORECASE,
)
_CLARIFICATION_STEP_RE = re.compile(
    r"clarif|ask (?:the )?user|澄清|询问用户|要求用户|请用户|补充(?:资料|信息|文档)",
    re.IGNORECASE,
)

_DATA_DRAFT_EVIDENCE = (
    EvidenceRequirement.METRIC_DEFINITION,
    EvidenceRequirement.TRUSTED_DATA_SOURCE,
    EvidenceRequirement.BUSINESS_RULES,
    EvidenceRequirement.VALIDATED_SQL,
)
T = TypeVar("T")


def is_enterprise_data_question(query: str) -> bool:
    """识别需要真实企业数据回答的问题，不把纯指标释义误路由为查询。"""

    text = str(query or "").strip()
    if not text:
        return False
    if _DEFINITION_ONLY_RE.search(text):
        return False
    if _DATA_EXPLICIT_RE.search(text):
        return True
    return bool(
        _DATA_MEASURE_RE.search(text)
        and (_DATA_OPERATION_RE.search(text) or _DATA_TIME_RE.search(text))
    )


def _append_unique(target: list[T], *items: T) -> None:
    for item in items:
        if item not in target:
            target.append(item)


def _available_grounding_sources(
    *,
    query: str,
    context_manifest: dict[str, Any],
    conversation_context_available: bool,
) -> list[str]:
    sources: list[str] = []
    enterprise = dict(context_manifest.get("enterprise_context") or {})
    company = dict(context_manifest.get("company_brain") or {})
    company_skills = dict(context_manifest.get("company_skills") or {})
    personal_business = dict(context_manifest.get("personal_business_context") or {})
    if enterprise.get("requires_grounding"):
        sources.append("enterprise_context")
    if company.get("answer_context_available"):
        sources.append(InformationSource.COMPANY_BRAIN.value)
    if company_skills.get("answer_context_available"):
        sources.append(InformationSource.COMPANY_SKILL.value)
    if int(context_manifest.get("memory_count") or 0) and (
        _PERSONAL_CONTEXT_RE.search(query or "") or is_contextual_follow_up(query)
    ):
        sources.append(InformationSource.PERSONAL_MEMORY.value)
    if personal_business.get("query_matched"):
        sources.append("personal_business_context")
    if int(context_manifest.get("attachment_count") or 0):
        sources.append("attachments")
    if conversation_context_available and is_contextual_follow_up(query):
        sources.append("conversation_parent_chain")
    return list(dict.fromkeys(sources))


def resolve_intent_clarification(
    decision: PlanningDecision,
    *,
    query: str,
    context_manifest: dict[str, Any],
    tool_specs: list[ToolSpec],
    tools_enabled: bool = True,
    conversation_context_available: bool = False,
) -> tuple[PlanningDecision, dict[str, Any]]:
    """优先用已注入信息和只读研究能力消解意图，只保留实质性用户选择。"""

    intent = decision.intent
    question = str(intent.clarification_question or "").strip()
    ambiguity = str(intent.ambiguity or "").strip()
    available_sources = _available_grounding_sources(
        query=query,
        context_manifest=context_manifest,
        conversation_context_available=conversation_context_available,
    )
    audit: dict[str, Any] = {
        "had_clarification": bool(question),
        "action": "none" if not question else "kept",
        "reason": "no_clarification" if not question else "material_user_choice",
        "available_context_sources": available_sources,
        "research_capabilities": [],
    }
    if not question:
        return decision, audit

    ambiguity_text = "\n".join((ambiguity, question))
    material = bool(_MATERIAL_AMBIGUITY_RE.search(ambiguity_text))
    if (
        intent.risk != SideEffect.READ
        or intent.data_stage
        in {DataIntentStage.SELECT_CANDIDATE, DataIntentStage.EXECUTE_AND_VERIFY}
        or material
    ):
        audit["material_ambiguity"] = True
        return decision, audit

    specs = {spec.name: spec for spec in tool_specs}
    research_capabilities = [
        name
        for name in intent.capabilities
        if specs.get(name) is not None and specs[name].side_effect == SideEffect.READ
    ]
    audit["research_capabilities"] = research_capabilities
    recoverable = bool(_RECOVERABLE_AMBIGUITY_RE.search(ambiguity_text))
    resolution_reason = ""
    normalized_intent = intent
    if available_sources:
        resolution_reason = "grounded_context_available"
    elif research_capabilities:
        resolution_reason = "read_research_available"
    elif conversation_context_available and is_contextual_follow_up(query) and not material:
        resolution_reason = "conversation_antecedent_available"
    elif recoverable and tools_enabled and "rag" in specs:
        resolution_reason = "rag_research_added"
        normalized_intent = replace(
            intent,
            capabilities=tuple(dict.fromkeys([*intent.capabilities, "rag"])),
            information_sources=tuple(
                dict.fromkeys([*intent.information_sources, InformationSource.RAG])
            ),
            freshness_requirement=(
                FreshnessRequirement.PUBLISHED
                if intent.freshness_requirement == FreshnessRequirement.UNSPECIFIED
                else intent.freshness_requirement
            ),
            evidence_requirements=tuple(
                dict.fromkeys(
                    [*intent.evidence_requirements, EvidenceRequirement.PUBLISHED_CITATIONS]
                )
            ),
        )
        audit["research_capabilities"] = [*research_capabilities, "rag"]
    else:
        audit["reason"] = "insufficient_non_material_grounding"
        return decision, audit

    resolved_intent = replace(
        normalized_intent,
        ambiguity=None,
        clarification_question=None,
    )
    audit.update(
        {
            "action": "resolved",
            "reason": resolution_reason,
            "material_ambiguity": False,
        }
    )
    retained_steps = tuple(
        step
        for step in decision.execution_plan.steps
        if step.capability is not None
        or not _CLARIFICATION_STEP_RE.search(
            "\n".join((step.id, step.objective, step.success_criteria))
        )
    )
    base_plan = replace(decision.execution_plan, steps=retained_steps)
    return (
        PlanningDecision(
            intent=resolved_intent,
            execution_plan=_reconcile_plan(base_plan, intent=resolved_intent),
        ),
        audit,
    )


def _default_step(capability: str) -> ExecutionStep:
    if capability == "rag":
        return ExecutionStep(
            id="rag-grounding",
            objective="检索当前用户有权访问的已发布企业知识与文档证据",
            capability="rag",
            success_criteria="返回带来源和作用域的可核验证据，证据不足时明确说明",
        )
    if capability == "data":
        return ExecutionStep(
            id="data-research-draft",
            objective="研究指标定义、可信数据源和业务规则并生成可验证 SQL 草案",
            capability="data",
            success_criteria="持久化治理运行和待确认候选，不把未执行草案当作数据答案",
        )
    if capability == "execute_sql_draft":
        return ExecutionStep(
            id="execute-governed-sql-draft",
            objective="审批后执行用户明确选择的 SQL 草案并验证结果",
            capability="execute_sql_draft",
            success_criteria="返回真实执行、结果校验和证据引用组成的数据答案",
        )
    return ExecutionStep(
        id=f"capability-{capability}",
        objective=f"调用 {capability} 获取完成目标所需的可核验证据",
        capability=capability,
        success_criteria="能力调用成功并返回可用于最终回答的结果",
    )


def _reconcile_plan(
    plan: ExecutionPlan,
    *,
    intent: IntentPlan,
) -> ExecutionPlan:
    capabilities = set(intent.capabilities)
    retained = [
        step for step in plan.steps if step.capability is None or step.capability in capabilities
    ]
    retained_ids = {step.id for step in retained}
    retained = [
        replace(
            step,
            depends_on=tuple(
                dependency for dependency in step.depends_on if dependency in retained_ids
            ),
        )
        for step in retained
    ]
    present = {step.capability for step in retained if step.capability}
    known_ids = {step.id for step in retained}
    for capability in intent.capabilities:
        if capability in present:
            continue
        step = _default_step(capability)
        base_id = step.id
        suffix = 2
        while step.id in known_ids:
            step = replace(step, id=f"{base_id}-{suffix}")
            suffix += 1
        retained.append(step)
        known_ids.add(step.id)
    if not retained:
        retained.append(
            ExecutionStep(
                id="answer-from-context",
                objective="综合当前请求与已注入的受治理上下文生成回答",
                success_criteria="只使用意图声明的信息来源并明确证据边界",
            )
        )
    success_criteria = list(plan.success_criteria)
    for requirement in intent.evidence_requirements:
        criterion = f"满足证据要求：{requirement.value}"
        if criterion not in success_criteria:
            success_criteria.append(criterion)
    return ExecutionPlan(
        goal=plan.goal or intent.goal,
        complexity=plan.complexity,
        steps=tuple(retained),
        success_criteria=tuple(success_criteria),
        replan_limit=plan.replan_limit,
    )


def apply_enterprise_intent_policy(
    decision: PlanningDecision,
    *,
    query: str,
    context_manifest: dict[str, Any],
    tool_specs: list[ToolSpec],
    rag_required: bool = False,
    tools_enabled: bool = True,
    data_stage_override: DataIntentStage | None = None,
) -> PlanningDecision:
    """把模型语义意图约束为五源、证据和问数阶段的可审计决策。"""

    intent = decision.intent
    specs = {spec.name: spec for spec in tool_specs}
    capabilities = [name for name in intent.capabilities if name in specs]
    sources = list(intent.information_sources)
    evidence = list(intent.evidence_requirements)

    if "rag" in capabilities:
        _append_unique(sources, InformationSource.RAG)
    if "data" in capabilities or "execute_sql_draft" in capabilities:
        _append_unique(sources, InformationSource.DATA)

    company = dict(context_manifest.get("company_brain") or {})
    enterprise = dict(context_manifest.get("enterprise_context") or {})
    if company.get("answer_context_available") or enterprise.get("requires_grounding"):
        _append_unique(sources, InformationSource.COMPANY_BRAIN)
    company_skills = dict(context_manifest.get("company_skills") or {})
    if company_skills.get("answer_context_available"):
        _append_unique(sources, InformationSource.COMPANY_SKILL)
    if int(context_manifest.get("memory_count") or 0) and _PERSONAL_CONTEXT_RE.search(query or ""):
        _append_unique(sources, InformationSource.PERSONAL_MEMORY)

    if rag_required:
        _append_unique(sources, InformationSource.RAG)
        if tools_enabled and "rag" in specs:
            _append_unique(capabilities, "rag")

    data_requested = is_enterprise_data_question(query)
    if data_requested:
        _append_unique(sources, InformationSource.DATA)
        if (
            tools_enabled
            and data_stage_override
            not in {DataIntentStage.SELECT_CANDIDATE, DataIntentStage.EXECUTE_AND_VERIFY}
            and "data" in specs
            and "execute_sql_draft" not in capabilities
        ):
            _append_unique(capabilities, "data")

    if not tools_enabled:
        capabilities = []
    if InformationSource.RAG in sources and tools_enabled and "rag" in specs:
        _append_unique(capabilities, "rag")
    if (
        InformationSource.DATA in sources
        and tools_enabled
        and data_stage_override
        not in {DataIntentStage.SELECT_CANDIDATE, DataIntentStage.EXECUTE_AND_VERIFY}
    ):
        if "execute_sql_draft" in specs and "execute_sql_draft" in capabilities:
            pass
        elif "data" in specs:
            _append_unique(capabilities, "data")

    allowed_evidence: set[EvidenceRequirement] = set()
    if InformationSource.PERSONAL_MEMORY in sources:
        allowed_evidence.add(EvidenceRequirement.PERSONAL_CONTEXT)
    if InformationSource.COMPANY_BRAIN in sources:
        allowed_evidence.add(EvidenceRequirement.ENTERPRISE_CONTEXT)
    if InformationSource.COMPANY_SKILL in sources:
        allowed_evidence.add(EvidenceRequirement.COMPANY_SKILL_CONTEXT)
    if InformationSource.RAG in sources:
        allowed_evidence.add(EvidenceRequirement.PUBLISHED_CITATIONS)
    if InformationSource.DATA in sources:
        allowed_evidence.update(_DATA_DRAFT_EVIDENCE)
        if data_stage_override == DataIntentStage.EXECUTE_AND_VERIFY:
            allowed_evidence.add(EvidenceRequirement.EXECUTED_RESULT)
    evidence = [item for item in evidence if item in allowed_evidence]

    if InformationSource.PERSONAL_MEMORY in sources:
        _append_unique(evidence, EvidenceRequirement.PERSONAL_CONTEXT)
    if InformationSource.COMPANY_BRAIN in sources:
        _append_unique(evidence, EvidenceRequirement.ENTERPRISE_CONTEXT)
    if InformationSource.COMPANY_SKILL in sources:
        _append_unique(evidence, EvidenceRequirement.COMPANY_SKILL_CONTEXT)
    if InformationSource.RAG in sources:
        _append_unique(evidence, EvidenceRequirement.PUBLISHED_CITATIONS)
    if InformationSource.DATA in sources:
        _append_unique(evidence, *_DATA_DRAFT_EVIDENCE)

    if data_stage_override is not None:
        data_stage = data_stage_override
    elif "execute_sql_draft" in capabilities:
        data_stage = DataIntentStage.EXECUTE_AND_VERIFY
    elif "data" in capabilities or data_requested:
        data_stage = DataIntentStage.RESEARCH_AND_DRAFT
    else:
        data_stage = DataIntentStage.NONE
    if data_stage == DataIntentStage.EXECUTE_AND_VERIFY:
        _append_unique(evidence, EvidenceRequirement.EXECUTED_RESULT)

    freshness = intent.freshness_requirement
    if InformationSource.DATA in sources:
        freshness = (
            FreshnessRequirement.HISTORICAL
            if _HISTORICAL_RE.search(query or "")
            else FreshnessRequirement.CURRENT
        )
    elif InformationSource.RAG in sources and freshness == FreshnessRequirement.UNSPECIFIED:
        freshness = FreshnessRequirement.PUBLISHED
    elif sources and freshness == FreshnessRequirement.UNSPECIFIED:
        freshness = FreshnessRequirement.STABLE

    selected_specs = [specs[name] for name in capabilities if name in specs]
    risk = max(
        (spec.side_effect for spec in selected_specs),
        default=SideEffect.READ,
        key=lambda value: {
            SideEffect.READ: 0,
            SideEffect.WRITE: 1,
            SideEffect.DESTRUCTIVE: 2,
        }[value],
    )
    task_type = intent.task_type
    if data_stage == DataIntentStage.RESEARCH_AND_DRAFT and task_type == "chat":
        task_type = "data_query"
    normalized_intent = replace(
        intent,
        task_type=task_type,
        capabilities=tuple(capabilities),
        risk=risk,
        information_sources=tuple(sources),
        freshness_requirement=freshness,
        evidence_requirements=tuple(evidence),
        data_stage=data_stage,
        ambiguity=(
            None
            if data_stage == DataIntentStage.RESEARCH_AND_DRAFT and "data" in capabilities
            else intent.ambiguity
        ),
        clarification_question=(
            None
            if data_stage == DataIntentStage.RESEARCH_AND_DRAFT and "data" in capabilities
            else intent.clarification_question
        ),
    )
    return PlanningDecision(
        intent=normalized_intent,
        execution_plan=_reconcile_plan(decision.execution_plan, intent=normalized_intent),
    )


def intent_answer_contract(intent: IntentPlan) -> str:
    """把结构化意图转换为最终回答模型可执行的证据约束。"""

    return (
        "当前 Response 的受治理信息意图如下。只把实际命中或工具成功返回的来源用于事实陈述；"
        "来源未命中、工具失败或证据不足时必须明确说明，不得补造。DataAgent 的 research_and_draft "
        "阶段只能展示研究结论与待确认 SQL 草案，不能声称已有查询结果；execute_and_verify 阶段"
        "只能采用实际执行和结果验证返回的数据。父链或已命中上下文能够高置信补全的省略信息，"
        "应按证据最强的解释完成回答；非关键格式和详略偏好采用稳妥默认值，必要时简短说明假设，"
        "不要在最终回答中重新提出已被意图策略消解的问题。\n"
        + json.dumps(intent.to_dict(), ensure_ascii=False)
    )
