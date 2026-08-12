from kernel.agent_loop.contracts import (
    DataIntentStage,
    EvidenceRequirement,
    ExecutionProfile,
    FreshnessRequirement,
    InformationSource,
    IntentPlan,
    SideEffect,
)


def test_intent_plan_is_provider_neutral_and_serializable():
    plan = IntentPlan(
        goal="分析数据",
        task_type="chat",
        capabilities=("query_database",),
        risk=SideEffect.READ,
        execution_profile=ExecutionProfile.DEEP,
        information_sources=(InformationSource.COMPANY_BRAIN, InformationSource.DATA),
        freshness_requirement=FreshnessRequirement.CURRENT,
        evidence_requirements=(
            EvidenceRequirement.METRIC_DEFINITION,
            EvidenceRequirement.VALIDATED_SQL,
        ),
        data_stage=DataIntentStage.RESEARCH_AND_DRAFT,
    )
    assert plan.to_dict() == {
        "goal": "分析数据",
        "task_type": "chat",
        "capabilities": ["query_database"],
        "ambiguity": None,
        "risk": "read",
        "execution_profile": "deep",
        "execution_mode": "interactive",
        "expected_outputs": ["answer"],
        "clarification_question": None,
        "information_sources": ["company_brain", "data"],
        "freshness_requirement": "current",
        "evidence_requirements": ["metric_definition", "validated_sql"],
        "data_stage": "research_and_draft",
    }
    assert IntentPlan.from_dict(plan.to_dict()) == plan
