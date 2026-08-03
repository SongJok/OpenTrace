from services.retrieval_matching import (
    expand_retrieval_terms,
    semantic_relevance,
    semantic_relevance_score,
)


def test_enterprise_colloquial_synonyms_rank_relevant_policy_above_noise() -> None:
    query = "借公司章要走什么手续？"
    relevant = semantic_relevance_score(
        query,
        "申请人通过钉钉 OA 发起印章借用审批，填写借出原因与归还日期。",
        title="印章使用借用审批流程",
    )
    irrelevant = semantic_relevance_score(
        query,
        "公司主营电竞媒体和语音社交产品。",
        title="公司基本信息",
    )

    assert relevant >= 0.55
    assert irrelevant < 0.24


def test_work_hours_and_personal_identity_paraphrases_share_business_concepts() -> None:
    work_hours = semantic_relevance(
        "上下班几点？",
        "工作时间为支持岗 9:00-18:00，运营岗 10:00-19:00。",
        title="考勤制度",
    )
    personal_name = semantic_relevance_score(
        "你记得我怎么称呼吗？",
        "我的代号是星轨-9152。",
    )

    assert work_hours.matched_concepts == ("work_hours",)
    assert work_hours.score >= 0.60
    assert personal_name >= 0.60


def test_expanded_terms_keep_history_subject_and_add_synonyms_within_budget() -> None:
    terms = expand_retrieval_terms(
        "那具体怎么操作？\n最近对话主题：\n我的内部项目代号是星轨-9152",
        limit=24,
    )
    seal_terms = expand_retrieval_terms("我想拿公章外出怎么办", limit=24)

    assert "代号" in terms
    assert "星轨" in terms
    assert len(terms) <= 24
    assert {"公章", "印章", "借用", "流程"} <= set(seal_terms)
