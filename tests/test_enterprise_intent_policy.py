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
from kernel.agent_loop.intent_policy import (
    apply_enterprise_intent_policy,
    intent_answer_contract,
    is_enterprise_data_question,
    is_production_intelligence_question,
)
from kernel.agent_loop.runner import AgentLoop


def _spec(name: str, *, side_effect: SideEffect = SideEffect.READ) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        side_effect=side_effect,
    )


def _decision(*capabilities: str, sources: tuple[InformationSource, ...] = ()) -> PlanningDecision:
    return PlanningDecision(
        intent=IntentPlan(
            goal="回答业务问题",
            capabilities=capabilities,
            information_sources=sources,
        ),
        execution_plan=ExecutionPlan(
            goal="回答业务问题",
            steps=(
                ExecutionStep(
                    id="hallucinated-step",
                    objective="模型给出的越界步骤",
                    capability="unknown_tool",
                ),
            ),
        ),
    )


def test_business_measure_with_time_is_deterministic_data_intent() -> None:
    assert is_enterprise_data_question("本月各区域的订单金额同比是多少？")
    assert is_enterprise_data_question("帮我查数：最近 7 天复购用户数")
    assert not is_enterprise_data_question("复购率的公司口径是什么？")
    assert not is_enterprise_data_question("给我一些提升复购率的建议")
    assert not is_enterprise_data_question("分析一下产品战略")
    assert not is_enterprise_data_question("如何改善用户体验？")
    assert not is_enterprise_data_question("订单查询流程是什么？")
    assert not is_enterprise_data_question("问数平台是什么？")
    assert not is_enterprise_data_question("数据库怎么配置？")

    governed = apply_enterprise_intent_policy(
        _decision(),
        query="本月各区域的订单金额同比是多少？",
        context_manifest={},
        tool_specs=[_spec("data"), _spec("rag")],
    )

    assert governed.intent.task_type == "data_query"
    assert governed.intent.capabilities == ("data",)
    assert governed.intent.information_sources == (InformationSource.DATA,)
    assert governed.intent.freshness_requirement == FreshnessRequirement.HISTORICAL
    assert governed.intent.data_stage == DataIntentStage.RESEARCH_AND_DRAFT
    assert EvidenceRequirement.METRIC_DEFINITION in governed.intent.evidence_requirements
    assert EvidenceRequirement.TRUSTED_DATA_SOURCE in governed.intent.evidence_requirements
    assert EvidenceRequirement.BUSINESS_RULES in governed.intent.evidence_requirements
    assert EvidenceRequirement.VALIDATED_SQL in governed.intent.evidence_requirements
    assert EvidenceRequirement.EXECUTED_RESULT not in governed.intent.evidence_requirements
    assert [step.capability for step in governed.execution_plan.steps] == ["data"]


def test_business_incident_routes_to_data_then_production_evidence_graph() -> None:
    query = "用户 882719 充值成功但余额未增加，请定位原因"
    assert is_enterprise_data_question(query)
    assert is_production_intelligence_question(query)

    governed = apply_enterprise_intent_policy(
        _decision(),
        query=query,
        context_manifest={},
        tool_specs=[_spec("data"), _spec("production"), _spec("rag")],
    )

    assert governed.intent.capabilities == ("data", "production")
    assert governed.intent.information_sources == (
        InformationSource.DATA,
        InformationSource.PRODUCTION,
    )
    steps = {step.capability: step for step in governed.execution_plan.steps}
    assert steps["production"].depends_on == (steps["data"].id,)
    assert EvidenceRequirement.TRUSTED_DATA_SOURCE in governed.intent.evidence_requirements
    assert EvidenceRequirement.LIVE_OBSERVATION in governed.intent.evidence_requirements


def test_unclassified_question_defaults_to_governed_rag_instead_of_model_knowledge() -> None:
    governed = apply_enterprise_intent_policy(
        _decision(),
        query="今天有什么外部新闻？",
        context_manifest={},
        tool_specs=[_spec("data"), _spec("rag")],
    )

    assert governed.intent.capabilities == ("rag",)
    assert governed.intent.information_sources == (InformationSource.RAG,)
    assert governed.intent.evidence_requirements == (EvidenceRequirement.PUBLISHED_CITATIONS,)
    assert [step.capability for step in governed.execution_plan.steps] == ["rag"]


def test_disabled_tools_keep_default_rag_requirement_for_fail_closed_gate() -> None:
    governed = apply_enterprise_intent_policy(
        _decision(),
        query="介绍一下市场最新趋势",
        context_manifest={},
        tool_specs=[_spec("rag")],
        tools_enabled=False,
    )

    assert governed.intent.capabilities == ()
    assert governed.intent.information_sources == (InformationSource.RAG,)
    assert EvidenceRequirement.PUBLISHED_CITATIONS in governed.intent.evidence_requirements


def test_runtime_source_policy_allows_only_governed_sources_and_blocks_raw_attachments() -> None:
    manifest = AgentLoop._five_source_policy_manifest(
        selected_sources=(InformationSource.COMPANY_BRAIN, InformationSource.RAG)
    )

    assert manifest["allowed_sources"] == [source.value for source in InformationSource]
    assert manifest["selected_sources"] == ["company_brain", "rag"]
    assert manifest["model_knowledge_allowed"] is False
    assert manifest["web_allowed"] is False
    assert manifest["external_connectors_allowed"] is True
    assert manifest["external_connector_policy"] == "catalogued_via_governed_gateway_and_critic"
    assert manifest["raw_attachment_evidence_allowed"] is False
    assert AgentLoop._five_source_input_violation(attachment_ids=[], modality_counts={}) is None
    violation = AgentLoop._five_source_input_violation(
        attachment_ids=["attachment-1"], modality_counts={"image": 1}
    )
    assert violation == {
        "reason": "raw_attachment_not_governed",
        "attachment_count": 1,
        "media_count": 1,
    }


def test_four_sources_can_be_combined_without_turning_context_into_tools() -> None:
    governed = apply_enterprise_intent_policy(
        _decision(
            "rag",
            "data",
            sources=(InformationSource.PERSONAL_MEMORY,),
        ),
        query="结合我的偏好、公司规则和本月销售数据给建议",
        context_manifest={
            "memory_count": 2,
            "company_brain": {"answer_context_available": True},
        },
        tool_specs=[_spec("data"), _spec("rag")],
    )

    assert governed.intent.capabilities == ("rag", "data")
    assert governed.intent.information_sources == (
        InformationSource.PERSONAL_MEMORY,
        InformationSource.RAG,
        InformationSource.DATA,
        InformationSource.COMPANY_BRAIN,
    )
    assert EvidenceRequirement.PERSONAL_CONTEXT in governed.intent.evidence_requirements
    assert EvidenceRequirement.ENTERPRISE_CONTEXT in governed.intent.evidence_requirements
    assert EvidenceRequirement.PUBLISHED_CITATIONS in governed.intent.evidence_requirements


def test_tool_choice_none_keeps_information_need_but_removes_execution_capability() -> None:
    governed = apply_enterprise_intent_policy(
        _decision("data", sources=(InformationSource.DATA,)),
        query="本月订单金额是多少？",
        context_manifest={},
        tool_specs=[_spec("data")],
        tools_enabled=False,
    )

    assert governed.intent.capabilities == ()
    assert governed.intent.information_sources == (InformationSource.DATA,)
    assert governed.intent.data_stage == DataIntentStage.RESEARCH_AND_DRAFT
    assert all(step.capability is None for step in governed.execution_plan.steps)


def test_execute_stage_requires_result_evidence_and_write_risk() -> None:
    governed = apply_enterprise_intent_policy(
        _decision("execute_sql_draft", sources=(InformationSource.DATA,)),
        query="确认执行第一个候选",
        context_manifest={},
        tool_specs=[_spec("execute_sql_draft", side_effect=SideEffect.WRITE)],
    )

    assert governed.intent.data_stage == DataIntentStage.EXECUTE_AND_VERIFY
    assert governed.intent.risk == SideEffect.WRITE
    assert EvidenceRequirement.EXECUTED_RESULT in governed.intent.evidence_requirements


def test_planner_cannot_invent_execute_stage_without_pending_draft() -> None:
    governed = apply_enterprise_intent_policy(
        PlanningDecision(
            intent=IntentPlan(
                goal="查询本月订单金额",
                information_sources=(InformationSource.DATA,),
                data_stage=DataIntentStage.EXECUTE_AND_VERIFY,
                evidence_requirements=(EvidenceRequirement.EXECUTED_RESULT,),
            ),
            execution_plan=ExecutionPlan(goal="查询本月订单金额"),
        ),
        query="本月订单金额是多少？",
        context_manifest={},
        tool_specs=[_spec("data")],
    )

    assert governed.intent.capabilities == ("data",)
    assert governed.intent.data_stage == DataIntentStage.RESEARCH_AND_DRAFT
    assert EvidenceRequirement.EXECUTED_RESULT not in governed.intent.evidence_requirements
    assert "不能声称已有查询结果" in intent_answer_contract(governed.intent)


def test_denied_execute_tool_keeps_unmet_execution_stage_without_capability() -> None:
    governed = apply_enterprise_intent_policy(
        PlanningDecision(
            intent=IntentPlan(
                goal="执行已确认草案",
                capabilities=("execute_sql_draft",),
                information_sources=(InformationSource.DATA,),
                data_stage=DataIntentStage.EXECUTE_AND_VERIFY,
            ),
            execution_plan=ExecutionPlan(goal="执行已确认草案"),
        ),
        query="确认执行第一个候选",
        context_manifest={},
        tool_specs=[_spec("data")],
        data_stage_override=DataIntentStage.EXECUTE_AND_VERIFY,
    )

    assert governed.intent.capabilities == ()
    assert governed.intent.data_stage == DataIntentStage.EXECUTE_AND_VERIFY
    assert governed.intent.risk == SideEffect.READ
    assert EvidenceRequirement.EXECUTED_RESULT in governed.intent.evidence_requirements


def test_data_draft_policy_removes_premature_result_evidence_and_planner_refusal() -> None:
    governed = apply_enterprise_intent_policy(
        PlanningDecision(
            intent=IntentPlan(
                goal="查询本月订单金额",
                ambiguity="data_tool_unavailable",
                clarification_question="我无法访问数据，请提供结果。",
                evidence_requirements=(EvidenceRequirement.EXECUTED_RESULT,),
            ),
            execution_plan=ExecutionPlan(goal="查询本月订单金额"),
        ),
        query="本月订单金额是多少？",
        context_manifest={},
        tool_specs=[_spec("data")],
    )

    assert governed.intent.capabilities == ("data",)
    assert governed.intent.ambiguity is None
    assert governed.intent.clarification_question is None
    assert EvidenceRequirement.EXECUTED_RESULT not in governed.intent.evidence_requirements


def test_invalid_serialized_intent_values_are_ignored_safely() -> None:
    restored = IntentPlan.from_dict(
        {
            "goal": "兼容旧计划",
            "information_sources": ["data", "invalid", "data"],
            "freshness_requirement": "invalid",
            "evidence_requirements": ["validated_sql", "invalid"],
            "data_stage": "invalid",
        }
    )

    assert restored.information_sources == (InformationSource.DATA,)
    assert restored.freshness_requirement == FreshnessRequirement.UNSPECIFIED
    assert restored.evidence_requirements == (EvidenceRequirement.VALIDATED_SQL,)
    assert restored.data_stage == DataIntentStage.NONE


def test_required_rag_policy_preserves_structured_data_intent() -> None:
    decision = PlanningDecision(
        intent=IntentPlan(
            goal="核对指标并查数",
            capabilities=("data",),
            information_sources=(InformationSource.DATA,),
            freshness_requirement=FreshnessRequirement.CURRENT,
            evidence_requirements=(EvidenceRequirement.VALIDATED_SQL,),
            data_stage=DataIntentStage.RESEARCH_AND_DRAFT,
        ),
        execution_plan=ExecutionPlan(goal="核对指标并查数"),
    )

    grounded = AgentLoop._apply_required_rag_policy(decision)

    assert grounded.intent.capabilities == ("data", "rag")
    assert grounded.intent.information_sources == (
        InformationSource.DATA,
        InformationSource.RAG,
    )
    assert grounded.intent.freshness_requirement == FreshnessRequirement.CURRENT
    assert grounded.intent.data_stage == DataIntentStage.RESEARCH_AND_DRAFT
    assert EvidenceRequirement.PUBLISHED_CITATIONS in grounded.intent.evidence_requirements
