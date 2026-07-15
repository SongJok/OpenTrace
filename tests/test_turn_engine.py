from kernel.agent_loop.contracts import ExecutionProfile, IntentPlan, SideEffect


def test_intent_plan_is_provider_neutral_and_serializable():
    plan = IntentPlan(
        goal="分析数据",
        task_type="chat",
        capabilities=("query_database",),
        risk=SideEffect.READ,
        execution_profile=ExecutionProfile.DEEP,
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
    }
