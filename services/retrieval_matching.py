"""面向中文企业知识与个人记忆的轻量同义召回和相关性评分。"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 这里使用稳定、可审计的业务词群补足 PostgreSQL simple FTS 对中文和口语改写的不足。
# 词群只用于扩大召回和排序，不改变权限范围，也不生成新的事实。
_CONCEPT_ALIASES: dict[str, tuple[str, ...]] = {
    "organization": ("公司", "企业", "单位", "组织", "机构", "团队"),
    "identity_name": (
        "名称",
        "全称",
        "名字",
        "姓名",
        "代号",
        "暗号",
        "昵称",
        "称呼",
        "叫什么",
        "怎么称呼",
    ),
    "company_profile": ("公司信息", "企业信息", "公司简介", "企业介绍", "公司概况"),
    "office_location": ("地址", "地点", "所在地", "办公地址", "办公地点", "办公室", "总部"),
    "business": ("业务", "主营", "主业", "产品", "服务", "业务范围", "产品矩阵"),
    "culture": ("文化", "价值观", "使命", "愿景", "理念", "人才观"),
    "work_hours": (
        "工作时间",
        "办公时间",
        "上班时间",
        "下班时间",
        "上下班",
        "几点上班",
        "几点下班",
        "作息",
        "班次",
    ),
    "attendance": ("考勤", "打卡", "迟到", "早退", "旷工", "补卡"),
    "leave": ("请假", "病假", "事假", "年假", "婚假", "产假", "陪产假", "丧假", "调休"),
    "salary": ("工资", "薪资", "薪酬", "发薪", "工资到账", "发工资", "计薪"),
    "expense": ("报销", "费用", "差旅", "发票", "出款", "交通费", "招待费"),
    "seal": ("印章", "公章", "章子", "盖章", "用印", "公司章"),
    "borrow": ("借用", "借出", "外借", "带出", "拿出去", "拿公章", "领用"),
    "approval": ("审批", "审核", "复核", "批准", "主管同意", "负责人同意"),
    "procedure": ("流程", "步骤", "手续", "怎么操作", "如何操作", "怎么办", "如何办理", "入口"),
    "apply": ("申请", "申领", "提交", "发起", "办理", "登记"),
    "withdrawal": ("提现", "兑换", "结算", "可提现", "提取"),
    "contact": ("联系人", "负责人", "对接人", "联络人", "电话", "邮箱", "联系方式"),
}

_CONCEPT_WEIGHTS: dict[str, float] = {
    "organization": 0.25,
    "identity_name": 1.2,
    "company_profile": 1.0,
    "procedure": 0.8,
    "apply": 0.7,
}

_STOP_PHRASES = (
    "请问",
    "麻烦",
    "帮我",
    "帮忙",
    "查一下",
    "看一下",
    "告诉我",
    "我想知道",
    "根据企业内部资料",
    "根据企业大脑",
    "根据知识库",
    "根据文档",
    "只依据企业大脑",
    "最近对话主题",
    "那具体怎么操作",
    "具体怎么操作",
    "是什么",
    "什么是",
    "有没有",
    "是否有",
    "怎么做",
    "怎么办",
    "如何做",
    "有哪些",
    "多少",
)

_STOP_TERMS = {
    "什么",
    "怎么",
    "如何",
    "哪个",
    "哪些",
    "是否",
    "一下",
    "当前",
    "最近",
    "对话",
    "主题",
    "这个",
    "那个",
    "我们",
    "你们",
    "他们",
    "请问",
    "麻烦",
    "帮我",
    "告诉",
    "资料",
    "回答",
    "please",
    "what",
    "which",
}


@dataclass(frozen=True, slots=True)
class RetrievalMatch:
    score: float
    concept_score: float
    lexical_score: float
    title_score: float
    matched_concepts: tuple[str, ...]
    matched_terms: tuple[str, ...]


def normalize_retrieval_text(text: str) -> str:
    normalized = str(text or "").lower()
    normalized = re.sub(r"[\s\u3000]+", "", normalized)
    normalized = re.sub(r"[，。！？；：、,.!?;:()（）【】\[\]{}<>《》‘’“”\-_/]+", "", normalized)
    return normalized


def retrieval_concepts(text: str) -> set[str]:
    normalized = normalize_retrieval_text(text)
    if not normalized:
        return set()

    concepts: set[str] = set()
    for concept, aliases in _CONCEPT_ALIASES.items():
        matched = any(normalize_retrieval_text(alias) in normalized for alias in aliases)
        if not matched:
            continue
        if concept == "identity_name":
            specific_identity = any(
                marker in normalized for marker in ("代号", "暗号", "昵称", "称呼", "叫什么")
            )
            organization_name = bool(
                re.search(r"(?:公司|企业|单位|组织|主体)(?:法定)?(?:全称|名称|名字)", normalized)
                or re.search(
                    r"(?:全称|名称|名字)(?:是|为)?(?:公司|企业|单位|组织|主体)", normalized
                )
            )
            personal_name = bool(
                re.search(r"(?:我的|我叫|本人)(?:名字|姓名|代号|暗号|昵称|称呼)", normalized)
            )
            if (
                not specific_identity
                and not organization_name
                and not personal_name
                and len(normalized) > 20
            ):
                continue
        if concept == "business" and "业务" in normalized:
            specific_business = any(
                marker in normalized
                for marker in (
                    "主营",
                    "主业",
                    "核心业务",
                    "业务范围",
                    "业务模式",
                    "产品矩阵",
                    "产品与服务",
                )
            )
            if not specific_business and len(normalized) > 20:
                continue
        concepts.add(concept)
    return concepts


def _query_text_without_fillers(text: str) -> str:
    value = str(text or "").lower()
    for phrase in _STOP_PHRASES:
        value = value.replace(phrase, " ")
    return value


def _lexical_terms(text: str, *, limit: int = 64) -> list[str]:
    value = _query_text_without_fillers(text)
    result: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        normalized = normalize_retrieval_text(term)
        if (
            len(normalized) < 2
            or normalized in _STOP_TERMS
            or normalized in seen
            or normalized.isdigit()
        ):
            return
        seen.add(normalized)
        result.append(normalized)

    for value_candidate in re.findall(r"(?:是|叫|为)\s*([\u4e00-\u9fffA-Za-z0-9_-]{2,32})", value):
        add(value_candidate)
        for fragment in re.findall(r"[a-z0-9][a-z0-9._:-]*|[\u4e00-\u9fff]{2,}", value_candidate):
            add(fragment)
    for token in re.findall(r"[a-z0-9][a-z0-9._:-]*", value):
        add(token)
    for run in re.findall(r"[\u4e00-\u9fff]{2,}", value):
        if len(run) <= 12:
            add(run)
        # 先保留更有区分度的 4/3 字窗口，再补 2 字窗口。
        for width in (4, 3, 2):
            if len(run) < width:
                continue
            for index in range(len(run) - width + 1):
                add(run[index : index + width])
                if len(result) >= limit:
                    return result
    return result[:limit]


def expand_retrieval_terms(text: str, *, limit: int = 48) -> list[str]:
    """生成数据库粗召回词：原问题词优先，再加入命中概念的同义词。"""

    result: list[str] = []
    seen: set[str] = set()

    def add(term: str) -> None:
        normalized = normalize_retrieval_text(term)
        if len(normalized) < 2 or normalized in _STOP_TERMS or normalized in seen:
            return
        seen.add(normalized)
        result.append(normalized)

    normalized_query = normalize_retrieval_text(text)
    concepts = sorted(retrieval_concepts(text))
    for concept in concepts:
        for alias in _CONCEPT_ALIASES[concept]:
            normalized_alias = normalize_retrieval_text(alias)
            if normalized_alias and normalized_alias in normalized_query:
                add(alias)
    for concept in concepts:
        add(_CONCEPT_ALIASES[concept][0])
    for term in _lexical_terms(text, limit=max(limit * 2, 64)):
        add(term)
        if len(result) >= limit:
            return result[:limit]
    for concept in concepts:
        for alias in _CONCEPT_ALIASES[concept]:
            add(alias)
            if len(result) >= limit:
                return result[:limit]
    return result[:limit]


def semantic_relevance(
    query: str,
    text: str,
    *,
    title: str = "",
) -> RetrievalMatch:
    """对短中文问法做可解释的概念覆盖 + 词面覆盖评分。"""

    normalized_query = normalize_retrieval_text(_query_text_without_fillers(query))
    normalized_text = normalize_retrieval_text(text)
    normalized_title = normalize_retrieval_text(title)
    haystack = f"{normalized_title}{normalized_text}"
    if not normalized_query or not haystack:
        return RetrievalMatch(0.0, 0.0, 0.0, 0.0, (), ())

    query_concepts = retrieval_concepts(query)
    document_concepts = retrieval_concepts(f"{title}\n{text}")
    matched_concepts = tuple(sorted(query_concepts & document_concepts))
    concept_denominator = sum(_CONCEPT_WEIGHTS.get(concept, 1.0) for concept in query_concepts)
    concept_numerator = sum(_CONCEPT_WEIGHTS.get(concept, 1.0) for concept in matched_concepts)
    concept_score = concept_numerator / concept_denominator if concept_denominator else 0.0

    query_terms = _lexical_terms(query, limit=32)
    matched_terms = tuple(term for term in query_terms if term in haystack)
    # 长词比偶然命中的 2 字窗口更可信；分母封顶，避免口语长问句被大量窗口稀释。
    matched_weight = sum(min(6, len(term)) for term in matched_terms[:12])
    lexical_score = min(1.0, matched_weight / 12.0)
    title_matches = [term for term in query_terms if term in normalized_title]
    title_score = min(1.0, sum(min(6, len(term)) for term in title_matches[:8]) / 8.0)

    exact_bonus = 0.0
    if len(normalized_query) >= 4 and normalized_query in haystack:
        exact_bonus = 0.22
    elif any(len(term) >= 4 for term in matched_terms):
        exact_bonus = 0.08

    if query_concepts:
        score = 0.66 * concept_score + 0.24 * lexical_score + 0.10 * title_score + exact_bonus
    else:
        score = 0.78 * lexical_score + 0.22 * title_score + exact_bonus
    return RetrievalMatch(
        score=round(min(0.999, score), 4),
        concept_score=round(concept_score, 4),
        lexical_score=round(lexical_score, 4),
        title_score=round(title_score, 4),
        matched_concepts=matched_concepts,
        matched_terms=matched_terms[:12],
    )


def semantic_relevance_score(query: str, text: str, *, title: str = "") -> float:
    return semantic_relevance(query, text, title=title).score
