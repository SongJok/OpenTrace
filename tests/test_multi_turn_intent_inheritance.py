"""多轮对话 intent 继承契约测试。

覆盖 Bug 2 / Bug 3 / Bug 4 的场景：
  - 追问继承上一轮 sticky domain (data_query/document_qa/web_search)
  - 显式关键词优先于继承
  - 无 prior 回退到 general_qa
"""


from kernel.cognitive_controls import (
    _STICKY_DOMAINS,
    _detect_follow_up,
    classify_intent,
)

# ── classify_intent 多轮继承 ───────────────────────────────────────────────

class TestIntentInheritance:
    """Bug 2: classify_intent() 多轮追问继承 sticky domain。"""

    def test_data_follow_up_inherits(self):
        """“按地区拆分呢？” + prior data_query → task_type=data_query"""
        lock = classify_intent(
            "按地区拆分呢？",
            prior_intent="data_query",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "data_query"
        assert "data.query" in lock.allowed_capabilities
        assert lock.confidence == 0.65  # 继承降置信度

    def test_data_drill_down_metric_follow_up(self):
        """“那上个月呢？” data→data 追问保持 data_query（时间下钻）"""
        lock = classify_intent(
            "那上个月呢？",
            prior_intent="data_query",
            prior_domain="data",
            conversation_phase="drill_down",
        )
        assert lock.task_type == "data_query"
        assert "data.query" in lock.allowed_capabilities

    def test_data_correction_stays_data_not_rag(self):
        """“不对，按销售额不是利润” + prior data_query → 仍为 data_query"""
        lock = classify_intent(
            "不对，按销售额不是利润",
            prior_intent="data_query",
            prior_domain="data",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "data_query"
        assert lock.task_type != "document_qa"

    def test_data_follow_up_no_doc_keyword_stays_data(self):
        """“再拆一下区域” 无文档关键词 → 继承 data"""
        lock = classify_intent(
            "再拆一下区域",
            prior_intent="data_query",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "data_query"

    def test_doc_follow_up_inherits(self):
        """“具体内容是什么？” + prior document_qa → task_type=document_qa"""
        lock = classify_intent(
            "具体内容是什么？",
            prior_intent="document_qa",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "document_qa"
        assert "rag.retrieve" in lock.allowed_capabilities
        assert lock.confidence == 0.65

    def test_web_follow_up_inherits(self):
        """“有进展吗？” + prior web_search + drill_down → 继承 web_search（不含显式关键词）"""
        lock = classify_intent(
            "有进展吗？",
            prior_intent="web_search",
            conversation_phase="drill_down",
        )
        assert lock.task_type == "web_search"
        assert "web.search" in lock.allowed_capabilities
        assert lock.confidence == 0.65  # 继承降置信度

    def test_web_explicit_keyword_always_wins(self):
        """“最新进展呢？” 含“最新” → 显式关键词优先，confidence=0.78"""
        lock = classify_intent(
            "最新进展呢？",
            prior_intent="data_query",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "web_search"
        assert lock.confidence == 0.78  # 显式关键词，非继承

    def test_short_query_detected_as_follow_up(self):
        """短追问 ≤15 字符 → 继承（无需 conversation_phase 信号）"""
        lock = classify_intent(
            "那地区呢？",
            prior_intent="data_query",
            conversation_phase=None,
        )
        assert lock.task_type == "data_query"

    def test_explicit_keyword_overrides_prior(self):
        """“今天天气？” + prior data_query → weather（显式关键词不被覆盖）"""
        lock = classify_intent(
            "今天天气怎么样？",
            prior_intent="data_query",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "weather"
        assert "tool.weather" in lock.allowed_capabilities

    def test_no_prior_no_inherit(self):
        """无 prior → 短追问回退 general_qa"""
        lock = classify_intent("按地区拆分呢？", prior_intent=None)
        assert lock.task_type == "general_qa"

    def test_non_sticky_domain_no_inherit(self):
        """非 sticky domain (weather) 不继承"""
        lock = classify_intent(
            "明天呢？",
            prior_intent="weather",
            conversation_phase="follow_up",
        )
        # weather 不在 STICKY_DOMAINS 中，追问应回退 general_qa
        assert lock.task_type == "general_qa"

    def test_greeting_not_overridden_by_prior(self):
        """“你好” + prior data_query → greeting（问候优先级最高）"""
        lock = classify_intent(
            "你好",
            prior_intent="data_query",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "greeting"

    def test_identity_not_overridden_by_prior(self):
        """“你是谁” + prior data_query → identity"""
        lock = classify_intent(
            "你是谁",
            prior_intent="data_query",
            conversation_phase="follow_up",
        )
        assert lock.task_type == "identity"

    def test_general_qa_no_keyword(self):
        """普通问答无关键词 → general_qa"""
        lock = classify_intent("今天心情不错")
        assert lock.task_type == "general_qa"
        assert "model.answer" in lock.allowed_capabilities

    def test_force_mode_always_works(self):
        """force_mode 依然正常工作"""
        lock = classify_intent("随便什么问题", force_mode="web")
        assert lock.task_type == "web"
        assert "web.search" in lock.allowed_capabilities
        assert lock.confidence == 1.0


# ── _detect_follow_up 辅助函数 ──────────────────────────────────────────────

class TestDetectFollowUp:
    """_detect_follow_up() 追问检测逻辑。"""

    def test_follow_up_phase(self):
        assert _detect_follow_up("任意文本", "follow_up") is False
        assert _detect_follow_up("这个是什么", "follow_up") is True

    def test_drill_down_phase(self):
        assert _detect_follow_up("任意文本", "drill_down") is True

    def test_short_query(self):
        # 任意短句不再自动视为追问；需续问前缀或 phase
        assert _detect_follow_up("短", None) is False
        assert _detect_follow_up("那地区呢？", None) is True
        assert _detect_follow_up("队长是什么", None) is False
        assert _detect_follow_up("这是一个超过十五个字符的长查询文本用来测试", None) is False

    def test_marker_prefix(self):
        assert _detect_follow_up("具体来说怎么做", None) is True
        assert _detect_follow_up("按地区拆分", None) is True
        assert _detect_follow_up("那结果呢", None) is True

    def test_q_word_contains(self):
        assert _detect_follow_up("这个怎么做呢", None) is True
        assert _detect_follow_up("为什么会这样", None) is True

    def test_unrelated_query(self):
        assert _detect_follow_up("我想看一部最新的科幻冒险电影推荐", None) is False


# ── _STICKY_DOMAINS 定义 ──────────────────────────────────────────────────

class TestStickyDomains:
    """验证 STICKY_DOMAINS 常量包含预期的 domain 类型。"""

    def test_sticky_domains_contain_expected(self):
        assert "data_query" in _STICKY_DOMAINS
        assert "document_qa" in _STICKY_DOMAINS
        assert "web_search" in _STICKY_DOMAINS

    def test_non_sticky_domains_excluded(self):
        assert "greeting" not in _STICKY_DOMAINS
        assert "weather" not in _STICKY_DOMAINS
        assert "time" not in _STICKY_DOMAINS
        assert "general_qa" not in _STICKY_DOMAINS
        assert "translation" not in _STICKY_DOMAINS
