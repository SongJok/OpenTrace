from kernel.agent_loop.contracts import (
    DataIntentStage,
    EvidenceRequirement,
    ExecutionPlan,
    ExecutionStep,
    InformationSource,
    IntentPlan,
    PlanningDecision,
    SideEffect,
    ToolSpec,
)
from kernel.agent_loop.intent_policy import (
    apply_enterprise_intent_policy,
    intent_answer_contract,
    resolve_intent_clarification,
)
from kernel.agent_loop.runner import AgentLoop


def _spec(name: str, side_effect: SideEffect = SideEffect.READ) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        parameters={"type": "object", "properties": {}},
        side_effect=side_effect,
    )


def _unclear(
    *,
    ambiguity: str = "capability_unavailable",
    question: str = "请提供相关资料。",
    capabilities: tuple[str, ...] = (),
    risk: SideEffect = SideEffect.READ,
    data_stage: DataIntentStage = DataIntentStage.NONE,
) -> PlanningDecision:
    return PlanningDecision(
        intent=IntentPlan(
            goal="回答当前问题",
            capabilities=capabilities,
            ambiguity=ambiguity,
            risk=risk,
            clarification_question=question,
            data_stage=data_stage,
        ),
        execution_plan=ExecutionPlan(
            goal="回答当前问题",
            steps=(ExecutionStep(id="clarify", objective="询问用户补充资料"),),
        ),
    )


def test_grounded_five_source_context_resolves_non_material_clarification() -> None:
    decision, audit = resolve_intent_clarification(
        _unclear(ambiguity="answer_format_preference", question="需要表格还是文字？"),
        query="结合我的偏好总结公司的订单字段规则",
        context_manifest={
            "enterprise_context": {"entity_count": 1, "requires_grounding": True},
            "company_brain": {"answer_context_available": True},
            "company_skills": {"answer_context_available": True},
            "memory_count": 2,
            "attachment_count": 1,
            "personal_business_context": {"query_matched": True},
        },
        tool_specs=[_spec("rag"), _spec("data")],
    )

    assert decision.intent.clarification_question is None
    assert decision.intent.ambiguity is None
    assert [step.id for step in decision.execution_plan.steps] == ["answer-from-context"]
    assert audit["action"] == "resolved"
    assert audit["reason"] == "grounded_context_available"
    assert {
        "enterprise_context",
        "company_brain",
        "company_skill",
        "personal_memory",
        "personal_business_context",
        "attachments",
    }.issubset(audit["available_context_sources"])


def test_missing_document_is_converted_to_read_only_rag_research() -> None:
    decision, audit = resolve_intent_clarification(
        _unclear(
            ambiguity="source_unavailable",
            question="请提供公司的报销制度文档。",
        ),
        query="公司的差旅报销有什么要求？",
        context_manifest={},
        tool_specs=[_spec("rag"), _spec("data")],
    )

    assert decision.intent.clarification_question is None
    assert decision.intent.capabilities == ("rag",)
    assert decision.intent.information_sources == (InformationSource.RAG,)
    assert EvidenceRequirement.PUBLISHED_CITATIONS in decision.intent.evidence_requirements
    assert any(step.capability == "rag" for step in decision.execution_plan.steps)
    assert all(step.id != "clarify" for step in decision.execution_plan.steps)
    assert audit["reason"] == "rag_research_added"


def test_selected_read_capability_runs_before_asking_user_for_source() -> None:
    decision, audit = resolve_intent_clarification(
        _unclear(capabilities=("rag",), question="你能提供相关文档吗？"),
        query="请总结产品退款政策",
        context_manifest={},
        tool_specs=[_spec("rag")],
    )

    assert decision.intent.clarification_question is None
    assert decision.intent.capabilities == ("rag",)
    assert audit["reason"] == "read_research_available"


def test_short_follow_up_inherits_parent_chain_instead_of_reasking_topic() -> None:
    decision, audit = resolve_intent_clarification(
        _unclear(
            ambiguity="missing_antecedent",
            question="你指的是哪个流程？",
        ),
        query="那具体怎么操作？",
        context_manifest={},
        tool_specs=[],
        conversation_context_available=True,
    )

    assert decision.intent.clarification_question is None
    assert audit["reason"] == "grounded_context_available"
    assert "conversation_parent_chain" in audit["available_context_sources"]


def test_material_target_or_source_conflict_still_requires_user_choice() -> None:
    for ambiguity, question in (
        ("missing_target", "请明确要修改哪个账户。"),
        ("source_conflict", "公司 Skill 与制度文档冲突，请确认采用哪个版本。"),
        ("ambiguous_metric", "你希望分析哪个经营指标？"),
    ):
        decision, audit = resolve_intent_clarification(
            _unclear(ambiguity=ambiguity, question=question),
            query="继续处理",
            context_manifest={"company_skills": {"answer_context_available": True}},
            tool_specs=[_spec("rag")],
            conversation_context_available=True,
        )

        assert decision.intent.clarification_question == question
        assert audit["action"] == "kept"
        assert audit["material_ambiguity"] is True


def test_sql_candidate_selection_and_write_operation_are_never_auto_resolved() -> None:
    candidate, candidate_audit = resolve_intent_clarification(
        _unclear(
            ambiguity="sql_candidate_selection_required",
            question="请选择要执行的 SQL 候选。",
            data_stage=DataIntentStage.SELECT_CANDIDATE,
        ),
        query="执行",
        context_manifest={"company_skills": {"answer_context_available": True}},
        tool_specs=[_spec("execute_sql_draft", SideEffect.WRITE)],
    )
    write, write_audit = resolve_intent_clarification(
        _unclear(
            ambiguity="missing_recipient",
            question="请确认消息接收人。",
            capabilities=("send_message",),
            risk=SideEffect.WRITE,
        ),
        query="发送通知",
        context_manifest={"memory_count": 3},
        tool_specs=[_spec("send_message", SideEffect.WRITE)],
    )

    assert candidate.intent.clarification_question is not None
    assert candidate_audit["action"] == "kept"
    assert write.intent.clarification_question is not None
    assert write_audit["action"] == "kept"


def test_vague_request_without_grounding_or_tools_keeps_one_question() -> None:
    decision, audit = resolve_intent_clarification(
        _unclear(ambiguity="missing_goal", question="你希望我完成什么结果？"),
        query="帮我处理一下",
        context_manifest={},
        tool_specs=[],
    )

    assert decision.intent.clarification_question == "你希望我完成什么结果？"
    assert audit["action"] == "kept"


def test_attachment_without_a_goal_and_disabled_tools_do_not_bypass_clarification() -> None:
    attachment, attachment_audit = resolve_intent_clarification(
        _unclear(ambiguity="missing_goal", question="你希望我如何处理这个附件？"),
        query="",
        context_manifest={"attachment_count": 1},
        tool_specs=[_spec("rag")],
    )
    disabled, disabled_audit = resolve_intent_clarification(
        _unclear(ambiguity="source_unavailable", question="请提供制度文档。"),
        query="公司的报销规则是什么？",
        context_manifest={},
        tool_specs=[_spec("rag")],
        tools_enabled=False,
    )

    assert attachment.intent.clarification_question is not None
    assert attachment_audit["material_ambiguity"] is True
    assert disabled.intent.clarification_question is not None
    assert disabled.intent.capabilities == ()
    assert disabled_audit["reason"] == "insufficient_non_material_grounding"


def test_planner_grounding_summary_declares_all_already_available_context() -> None:
    prompt = AgentLoop._planning_grounding_context(
        {
            "enterprise_context": {"requires_grounding": True},
            "company_brain": {"answer_context_available": True},
            "company_skills": {"answer_context_available": True, "skill_count": 2},
            "memory_count": 3,
            "personal_business_context": {"query_matched": True},
            "attachment_count": 1,
        },
        query="那具体怎么操作？",
        conversation_context_available=True,
    )

    assert "企业认知实体" in prompt
    assert "企业大脑" in prompt
    assert "2 个公司上传 Skill" in prompt
    assert "3 条" in prompt
    assert "周期任务" in prompt
    assert "1 个附件" in prompt
    assert "父链最近对话" in prompt


def test_enterprise_entity_context_is_recorded_as_company_brain_evidence() -> None:
    governed = apply_enterprise_intent_policy(
        PlanningDecision(
            intent=IntentPlan(goal="解释公司术语"),
            execution_plan=ExecutionPlan(goal="解释公司术语"),
        ),
        query="飞轮项目是什么意思？",
        context_manifest={"enterprise_context": {"entity_count": 1, "requires_grounding": True}},
        tool_specs=[_spec("rag")],
    )

    assert governed.intent.information_sources == (InformationSource.COMPANY_BRAIN,)
    assert governed.intent.evidence_requirements == (EvidenceRequirement.ENTERPRISE_CONTEXT,)
    assert "不要在最终回答中重新提出" in intent_answer_contract(governed.intent)
