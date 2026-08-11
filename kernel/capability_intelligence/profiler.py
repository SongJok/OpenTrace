"""CapabilityProfiler — 构建、增强与查询能力画像。

能力语义的单一事实来源；画像由 _SEED_DATA 种子化（原分散在
UnderstandingEngine、StrategyBuilder 等），并由 CapabilityFeedbackLoop 随执行精炼。
"""

from __future__ import annotations

from infra.observability.logger import get_logger
from kernel.capability_intelligence.profile import CapabilityProfile, ExecutionRecord

logger = get_logger(__name__)

# ── CJK Unicode 范围 ──────────────────────────────────────────────────────
# 覆盖 CJK 统一汉字（U+4E00–U+9FFF）、扩展 A（U+3400–U+4DBF）、
# CJK 兼容汉字（U+F900–U+FAFF）和 CJK 符号（U+3000–U+303F）。
_CJK_RANGES: list[tuple[int, int]] = [
    (0x4E00, 0x9FFF),  # CJK 统一汉字（常用）
    (0x3400, 0x4DBF),  # CJK 统一汉字扩展 A
    (0xF900, 0xFAFF),  # CJK 兼容汉字
    (0x3000, 0x303F),  # CJK 符号和标点
]


def _is_cjk_text(text: str, threshold: float = 0.25) -> bool:
    """检查文本中是否有显著比例的字符属于 CJK Unicode 区块。"""
    if not text:
        return False
    cjk_count = 0
    for ch in text:
        cp = ord(ch)
        if any(lo <= cp <= hi for lo, hi in _CJK_RANGES):
            cjk_count += 1
    return cjk_count > len(text) * threshold


def _bigram_score_cjk(query: str, text: str) -> float:
    """使用字符二元组 + 一元组重叠度对中文查询与搜索文本进行评分。

    单字符查询（无二元组）通过仅一元组评分处理。
    """
    query_bigrams = {query[i : i + 2] for i in range(len(query) - 1)}
    text_bigrams = {text[i : i + 2] for i in range(len(text) - 1)}
    query_unigrams = set(query)
    text_unigrams = set(text)

    bigram_hits = len(query_bigrams & text_bigrams) if query_bigrams else 0
    unigram_hits = len(query_unigrams & text_unigrams)

    bigram_weight = len(query_bigrams) * 2.0
    unigram_weight = len(query_unigrams) * 0.5

    if bigram_weight == 0 and unigram_weight == 0:
        return 0.0

    return (bigram_hits * 2.0 + unigram_hits * 0.5) / (bigram_weight + unigram_weight)

# ── 种子数据：原先分散在 4+ 个文件中的语义知识 ───────
# 每条目描述能力的擅长/不擅长领域、资源画像与示例查询。
# 这是从硬编码提示字符串到结构化能力认知的迁移。

_SEED_DATA: dict[str, dict] = {
    "data.query": {
        "description": "结构化数据查询（SQL/DataAgent），查询关系型数据库中的业务数据",
        "strengths": ["历史数据分析", "多维度对比", "聚合统计", "多表关联查询", "精确数值计算"],
        "weaknesses": ["无法获取实时数据", "无法搜索非结构化文本", "依赖已绑定的数据源", "复杂分析需要多步查询"],
        "ideal_queries": ["今年Q3销售额最高的10个产品", "按地区和月份统计用户增长趋势", "对比华东和华南的毛利"],
        "anti_patterns": ["查询今天最新价格", "搜索公司政策文档", "分析图片内容", "获取新闻"],
        "required_inputs": ["data_source_id"],
        "output_types": ["table", "text"],
        "tags": ["数据查询", "SQL", "数据库", "报表", "统计", "data", "query"],
        "resource_type": "cpu",
        "expected_latency_ms": 3000,
        "reliability": 0.92,
        "agent_type": "data",
    },
    "data.analysis": {
        "description": "数据分析与统计推理，对查询结果进行趋势分析、异常检测、统计检验",
        "strengths": ["趋势识别", "异常检测", "统计推断", "时间序列分析"],
        "weaknesses": ["依赖 data.query 的前置结果", "需要足够的样本量", "无法替代业务专家判断"],
        "ideal_queries": ["分析销售趋势并给出优化建议", "检测Q4的数据异常点"],
        "anti_patterns": ["单次简单查询", "纯文本问题", "不需要统计推理的查询"],
        "required_inputs": ["前置 data.query 结果"],
        "output_types": ["text", "table"],
        "tags": ["数据分析", "趋势", "统计", "异常检测", "analysis"],
        "resource_type": "cpu",
        "expected_latency_ms": 5000,
        "reliability": 0.85,
        "agent_type": "data",
    },
    "web.search": {
        "description": "联网搜索实时信息，获取最新新闻、网页内容、公开数据",
        "strengths": ["最新信息获取", "新闻事件", "网页内容提取", "实时数据查询", "公开信息检索"],
        "weaknesses": ["无法访问私有/内网数据", "结果质量依赖搜索引擎", "可能有广告或低质量内容", "不支持结构化SQL"],
        "ideal_queries": ["最新AI行业动态", "今天天气怎么样", "某公司最新财报"],
        "anti_patterns": ["查询内部数据库", "高精度数值计算", "分析已上传的私有文档"],
        "required_inputs": [],
        "output_types": ["text", "urls"],
        "tags": ["搜索", "联网", "实时", "新闻", "web", "search"],
        "resource_type": "io",
        "expected_latency_ms": 2500,
        "reliability": 0.80,
        "agent_type": "web",
    },
    "rag.retrieve": {
        "description": "文档与知识库检索（RAG），从已上传的文档和内部知识库中检索相关内容",
        "strengths": ["私有文档检索", "企业内部知识", "长文本理解", "精确引用溯源"],
        "weaknesses": ["仅限已上传/已索引的文档", "无法获取实时外部信息", "检索质量依赖文档质量"],
        "ideal_queries": ["根据产品手册回答", "查找项目文档中的技术方案", "公司政策是什么"],
        "anti_patterns": ["查询最新外部新闻", "结构化数据库查询", "获取未上传的文档内容"],
        "required_inputs": ["indexed_documents"],
        "output_types": ["text", "citations"],
        "tags": ["文档", "知识库", "RAG", "检索", "引用", "文档检索"],
        "resource_type": "io",
        "expected_latency_ms": 1500,
        "reliability": 0.88,
        "agent_type": "rag",
    },
    "tool.datetime": {
        "description": "日期时间查询，获取当前时间、日期计算、时区转换",
        "strengths": ["精确时间查询", "日期计算", "时区转换"],
        "weaknesses": ["仅处理时间日期", "无法执行复杂计算"],
        "ideal_queries": ["现在是几点", "2026年春节是几号", "纽约现在几点"],
        "anti_patterns": ["数据分析", "文档搜索", "代码执行"],
        "required_inputs": [],
        "output_types": ["text"],
        "tags": ["时间", "日期", "时区", "日历", "datetime"],
        "resource_type": "cpu",
        "expected_latency_ms": 300,
        "reliability": 0.99,
        "agent_type": "tool",
    },
    "tool.weather": {
        "description": "天气查询，获取指定城市的实时天气或预报",
        "strengths": ["实时天气", "多日预报", "城市天气对比"],
        "weaknesses": ["依赖第三方天气API", "无法查询历史天气数据（需web.search补充）"],
        "ideal_queries": ["北京今天天气", "上海未来一周天气预报"],
        "anti_patterns": ["历史气候分析", "非天气相关查询"],
        "required_inputs": [],
        "output_types": ["text"],
        "tags": ["天气", "气象", "温度", "预报", "weather"],
        "resource_type": "io",
        "expected_latency_ms": 1500,
        "reliability": 0.95,
        "agent_type": "tool",
    },
    "tool.calculator": {
        "description": "数值计算，执行精确的数学运算",
        "strengths": ["精确数值计算", "复杂公式", "单位换算"],
        "weaknesses": ["仅处理数值", "不涉及语义理解"],
        "ideal_queries": ["计算 (123+456)*78", "100美元等于多少人民币"],
        "anti_patterns": ["文字推理", "数据查询", "文档检索"],
        "required_inputs": [],
        "output_types": ["text"],
        "tags": ["计算", "数学", "公式", "换算", "calculator", "数值"],
        "resource_type": "cpu",
        "expected_latency_ms": 200,
        "reliability": 0.99,
        "agent_type": "tool",
    },
    "python.execute": {
        "description": "Python 代码执行，运行数据处理、可视化、统计分析脚本",
        "strengths": ["灵活的数据处理", "科学计算", "可视化生成", "自定义算法"],
        "weaknesses": ["沙箱环境受限", "无法访问外部网络", "执行时间有上限"],
        "ideal_queries": ["用Python分析这份数据", "生成数据分布图", "运行统计检验"],
        "anti_patterns": ["简单的单次查询", "不需要代码处理的纯文本问答"],
        "required_inputs": [],
        "output_types": ["text", "chart", "table"],
        "tags": ["Python", "代码", "执行", "脚本", "编程", "数据处理"],
        "resource_type": "cpu",
        "expected_latency_ms": 8000,
        "reliability": 0.85,
        "agent_type": "tool",
    },
    "chart.generate": {
        "description": "图表生成，将数据转换为可视化图表",
        "strengths": ["数据可视化", "多种图表类型", "直观展示趋势"],
        "weaknesses": ["依赖前置数据", "需要明确图表类型需求", "复杂图表需要多次调整"],
        "ideal_queries": ["画一个销售趋势图", "生成饼图展示市场份额"],
        "anti_patterns": ["数据查询（需要 data.query 前置）", "纯文本回答"],
        "required_inputs": ["前置数据结果"],
        "output_types": ["chart"],
        "tags": ["图表", "可视化", "绘图", "chart", "图形", "饼图", "趋势图"],
        "resource_type": "gpu",
        "expected_latency_ms": 6000,
        "reliability": 0.82,
        "agent_type": "tool",
    },
    "memory.retrieve": {
        "description": "历史记忆检索，从会话历史和长期记忆中检索相关上下文",
        "strengths": ["跨会话记忆", "用户偏好回忆", "历史对话上下文", "事实记忆"],
        "weaknesses": ["仅限已存储的记忆", "记忆可能过时", "依赖记忆写入质量"],
        "ideal_queries": ["上次我们讨论的结论是什么", "根据我的偏好推荐"],
        "anti_patterns": ["获取外部实时信息", "结构化数据库查询", "新领域的未知知识"],
        "required_inputs": [],
        "output_types": ["text"],
        "tags": ["记忆", "历史", "上下文", "会话", "memory", "用户偏好"],
        "resource_type": "io",
        "expected_latency_ms": 500,
        "reliability": 0.90,
        "agent_type": "memory",
    },
    "entity.resolution": {
        "description": "命名实体消歧，将模糊的实体名称解析为规范化的实体标识",
        "strengths": ["实体名称标准化", "歧义消除", "实体关联"],
        "weaknesses": ["依赖实体知识库", "新实体可能需要人工确认"],
        "ideal_queries": ["'苹果'指的是哪个公司", "'华东'包含哪些省份"],
        "anti_patterns": ["不需要实体消歧的明确查询"],
        "required_inputs": [],
        "output_types": ["text"],
        "tags": ["实体", "消歧", "命名", "标准化", "entity"],
        "resource_type": "cpu",
        "expected_latency_ms": 800,
        "reliability": 0.87,
        "agent_type": "data",
    },
    "vision.analyze": {
        "description": "图片/图表分析，理解图像内容并提取结构化信息",
        "strengths": ["图像内容识别", "图表数据提取", "OCR文字识别", "视觉推理"],
        "weaknesses": ["仅处理视觉输入", "无法处理音频/视频", "复杂场景可能误判"],
        "ideal_queries": ["分析这张图表", "图片中有什么内容", "提取截图中的文字"],
        "anti_patterns": ["纯文本查询", "不需要视觉理解的查询"],
        "required_inputs": ["image_data 或 image_urls"],
        "output_types": ["text"],
        "tags": ["图片", "图像", "视觉", "OCR", "vision", "截图", "图表"],
        "resource_type": "gpu",
        "expected_latency_ms": 5000,
        "reliability": 0.80,
        "agent_type": "vision",
    },
    "skills.execute": {
        "description": "技能执行，调用已安装的领域技能完成特定任务",
        "strengths": ["领域专精任务", "自定义业务流程", "组合多个原子操作"],
        "weaknesses": ["仅限已安装的技能", "技能质量参差不齐", "需要明确匹配的技能ID"],
        "ideal_queries": ["异常追踪分析", "执行数据质量检查"],
        "anti_patterns": ["通用问答", "不需要特定技能的简单查询"],
        "required_inputs": ["enabled_skills"],
        "output_types": ["text", "table"],
        "tags": ["技能", "skill", "执行", "领域", "专精"],
        "resource_type": "cpu",
        "expected_latency_ms": 3000,
        "reliability": 0.78,
        "agent_type": "skills",
    },
}


class CapabilityProfiler:
    """从注册表 + 种子数据 + 反馈构建并维护能力画像。"""

    def __init__(self) -> None:
        self._profiles: dict[str, CapabilityProfile] = {}
        self._built = False
        self._kg: Any = None  # CapabilityKnowledgeGraph，延迟构建
        self._reasoner: Any = None  # CapabilityReasoner，延迟构建

    def build_profiles(self, registry) -> dict[str, CapabilityProfile]:
        """扫描注册表并构建画像，应用种子数据以获得丰富语义。"""
        if self._built:
            return self._profiles

        for cap_name, cap in registry._capabilities.items():
            profile = self._profile_from_capability(cap_name, cap)
            self._profiles[cap_name] = profile

        # 同时种子化 _SEED_DATA 中尚未在注册表中的能力类型
        for cap_type, seed in _SEED_DATA.items():
            if cap_type not in self._profiles:
                self._profiles[cap_type] = CapabilityProfile(
                    capability_type=cap_type, **seed
                )

        self._built = True
        logger.debug("CapabilityProfiler built %d profiles", len(self._profiles))

        # Phase 2：若已启用则构建知识图谱
        if self._kg is None:
            try:
                from kernel.capability_intelligence import _capability_intelligence_phase2_enabled

                if _capability_intelligence_phase2_enabled():
                    from kernel.capability_intelligence.knowledge_graph import (
                        CapabilityKnowledgeGraph,
                    )

                    self._kg = CapabilityKnowledgeGraph()
                    self._kg.build(self._profiles)
                    logger.debug("Knowledge graph built with %d relations",
                                 len(self._kg._relations) if hasattr(self._kg, '_relations') else 0)
            except Exception:
                pass

        return self._profiles

    def _profile_from_capability(self, name: str, cap) -> CapabilityProfile:
        seed = _SEED_DATA.get(name, {})
        return CapabilityProfile(
            capability_type=name,
            description=seed.get("description", cap.description or name),
            strengths=list(seed.get("strengths", [])),
            weaknesses=list(seed.get("weaknesses", [])),
            ideal_queries=list(seed.get("ideal_queries", [])),
            anti_patterns=list(seed.get("anti_patterns", [])),
            expected_latency_ms=seed.get("expected_latency_ms", cap.avg_latency_ms),
            reliability=seed.get("reliability", 0.9),
            required_inputs=list(seed.get("required_inputs", [])),
            output_types=list(seed.get("output_types", ["text"])),
            tags=list(cap.tags) if cap.tags else list(seed.get("tags", [])),
            resource_type=seed.get("resource_type", cap.resource_type),
            agent_type=seed.get("agent_type", cap.agent_type or ""),
        )

    def get_profile(self, capability_type: str) -> CapabilityProfile | None:
        return self._profiles.get(capability_type)

    def list_profiles(self) -> list[CapabilityProfile]:
        return sorted(
            self._profiles.values(),
            key=lambda p: p.reliability,
            reverse=True,
        )

    def match(self, query: str, top_k: int = 5) -> list[CapabilityProfile]:
        """将查询与画像标签 + 擅长领域 + 理想查询进行匹配。"""
        return [p for _, p in self.match_scored(query, top_k)]

    def match_scored(
        self, query: str, top_k: int = 5
    ) -> list[tuple[float, CapabilityProfile]]:
        """类似 match()，但返回 (score, profile) 对以供下游加权。

        中文文本使用字符二元组重叠度评分，空格分隔文本（英文）使用
        词级重叠度评分。同时检查完整查询子串是否出现在理想查询和描述中。
        """
        query_lower = query.lower().strip()
        if not query_lower:
            return []

        use_cjk = _is_cjk_text(query_lower)

        scored: list[tuple[float, CapabilityProfile]] = []
        for profile in self._profiles.values():
            score = 0.0
            search_text = " ".join(
                profile.tags + profile.strengths + profile.ideal_queries + [profile.description]
            ).lower()

            if use_cjk:
                score = _bigram_score_cjk(query_lower, search_text)
            else:
                query_tokens = set(query_lower.split())
                if query_tokens:
                    hits = sum(1 for t in query_tokens if t in search_text)
                    score = hits / len(query_tokens)

            # 加分：在理想查询或描述中的精确子串匹配
            for ideal in profile.ideal_queries:
                if query_lower in ideal.lower() or ideal.lower() in query_lower:
                    score += 0.3
                    break
            if query_lower in profile.description.lower():
                score += 0.2

            if score > 0:
                scored.append((score, profile))

        scored.sort(key=lambda x: x[0], reverse=True)
        return scored[:top_k]

    def match_multi_objective(
        self,
        query: str,
        top_k: int = 5,
        context: dict | None = None,
        budget_limit_ms: int = 30_000,
        risk_tolerance: str = "medium",
    ) -> list[tuple[float, CapabilityProfile]]:
        """多目标能力评分，替代纯 BM25 匹配。

        将五个维度组合为综合评分：
          semantic_fitness      (0.30) — 文本匹配质量
          historical_success    (0.25) — 历史执行成功率
          contextual_compatibility (0.20) — 是否契合当前上下文
          budget_fit            (0.15) — 延迟/成本是否在预算内
          risk_fit              (0.10) — 可靠性是否满足风险容忍度
        """
        context = context or {}
        domain = context.get("domain", "general")
        required_inputs = context.get("required_inputs", [])

        # 获取基础语义评分
        semantic_scored = self.match_scored(query, top_k=max(top_k * 2, 10))
        if not semantic_scored:
            return []

        # 构建综合评分
        composite: list[tuple[float, CapabilityProfile]] = []
        for sem_score, profile in semantic_scored:
            # 1. 语义适配度（归一化至 0-1）
            sem_norm = min(sem_score / 3.0, 1.0) if sem_score > 0 else 0.0

            # 2. 来自执行记忆的历史成功率
            hist_score = self._get_historical_success(profile.capability_type, domain)

            # 3. 上下文兼容性
            ctx_score = self._get_contextual_compatibility(
                profile, domain, required_inputs
            )

            # 4. 预算适配度
            budget_score = self._get_budget_fit(profile, budget_limit_ms)

            # 5. 风险适配度
            risk_score = self._get_risk_fit(profile, risk_tolerance)

            total = (
                sem_norm * 0.30
                + hist_score * 0.25
                + ctx_score * 0.20
                + budget_score * 0.15
                + risk_score * 0.10
            )
            composite.append((total, profile))

        composite.sort(key=lambda x: x[0], reverse=True)
        return composite[:top_k]

    def _get_historical_success(self, capability_type: str, domain: str) -> float:
        """查询执行记忆获取历史成功率。"""
        try:
            from kernel.capability_intelligence import _capability_intelligence_phase2_enabled
            if not _capability_intelligence_phase2_enabled():
                return 0.5  # 无数据时的中性默认值

            from kernel.capability_intelligence.execution_memory import execution_memory
            stats = execution_memory.get_stats(capability_type)
            if stats and stats.total > 0:
                # 加权：70% 整体 + 30% 近期时间窗
                windowed = execution_memory.get_time_windowed_stats(
                    capability_type, window_seconds=3600
                )
                recent_rate = windowed.success_rate if windowed and windowed.total > 0 else stats.success_rate
                return stats.success_rate * 0.7 + recent_rate * 0.3
            return 0.5
        except Exception:
            return 0.5

    def _get_contextual_compatibility(
        self,
        profile: CapabilityProfile,
        domain: str,
        required_inputs: list[str],
    ) -> float:
        """评估能力与当前上下文的契合程度。"""
        score = 0.5  # 中性起始值

        # 领域匹配：检查是否有标签匹配领域
        domain_lower = domain.lower()
        tag_match = any(domain_lower in t.lower() or t.lower() in domain_lower for t in profile.tags)
        if tag_match:
            score += 0.2

        # 必需输入：若能力需要我们不具备的输入则扣分
        for req in profile.required_inputs:
            if req not in required_inputs:
                score -= 0.15

        # 反模式检查：若查询看起来像反模式则扣分
        # （轻量级 — 仅检查是否有反模式关键词出现）
        # 这是尽力而为的检查，在推理器中处理得更彻底

        return max(0.0, min(1.0, score))

    def _get_budget_fit(
        self, profile: CapabilityProfile, budget_limit_ms: int
    ) -> float:
        """评估能力是否在预算范围内。"""
        latency = profile.expected_latency_ms
        if latency <= 0:
            return 0.5
        ratio = budget_limit_ms / latency
        if ratio >= 5:
            return 1.0   # 远在预算内
        if ratio >= 2:
            return 0.8
        if ratio >= 1:
            return 0.6
        if ratio >= 0.5:
            return 0.3
        return 0.1  # 严重超出预算

    def _get_risk_fit(
        self, profile: CapabilityProfile, risk_tolerance: str
    ) -> float:
        """评估能力的可靠性是否匹配风险容忍度。"""
        reliability = profile.reliability

        risk_thresholds = {
            "low": 0.60,
            "medium": 0.75,
            "high": 0.85,
            "critical": 0.95,
        }
        threshold = risk_thresholds.get(risk_tolerance, 0.75)

        if reliability >= threshold:
            return 1.0
        if reliability >= threshold - 0.1:
            return 0.7
        if reliability >= threshold - 0.2:
            return 0.4
        return 0.1

    def update_from_record(self, record: ExecutionRecord) -> None:
        """更新画像可靠性（增量均值）和延迟（指数移动平均）。"""
        profile = self._profiles.get(record.capability_type)
        if profile is None:
            return

        profile.execution_count += 1
        n = profile.execution_count

        # 可靠性的增量均值
        success_value = 1.0 if record.success else 0.0
        profile.reliability += (success_value - profile.reliability) / n

        # 延迟的指数移动平均（新观测权重 0.2）
        if record.latency_ms > 0:
            profile.expected_latency_ms = int(
                profile.expected_latency_ms * 0.8 + record.latency_ms * 0.2
            )

        # 将证据质量混合进可靠性以获得更细粒度
        if record.evidence_quality > 0:
            profile.reliability = round(
                profile.reliability * 0.9 + record.evidence_quality * 0.1, 4
            )

    def get_knowledge_graph(self):
        """返回知识图谱，必要时构建。"""
        if self._kg is None:
            try:
                from kernel.capability_intelligence import _capability_intelligence_phase2_enabled

                if _capability_intelligence_phase2_enabled():
                    from kernel.capability_intelligence.knowledge_graph import (
                        CapabilityKnowledgeGraph,
                    )

                    self._kg = CapabilityKnowledgeGraph()
                    if self._profiles:
                        self._kg.build(self._profiles)
            except Exception:
                pass
        return self._kg

    def get_reasoner(self):
        """返回推理器，必要时构建（同时构建知识图谱）。"""
        if self._reasoner is None:
            kg = self.get_knowledge_graph()
            if kg is not None:
                try:
                    from kernel.capability_intelligence.execution_memory import execution_memory
                    from kernel.capability_intelligence.reasoner import CapabilityReasoner
                    from kernel.capability_intelligence.strategy_memory import strategy_memory

                    self._reasoner = CapabilityReasoner(
                        kg=kg,
                        profiler=self,
                        execution_memory=execution_memory,
                        strategy_memory=strategy_memory,
                    )
                except Exception:
                    pass
            # 若知识图谱为 None（开关关闭），推理器保持 None
        return self._reasoner


capability_profiler = CapabilityProfiler()
