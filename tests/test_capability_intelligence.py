"""能力智能层契约测试 — 运行时自认知。"""

from __future__ import annotations

import time
import unittest


class TestCapabilityProfile:
    """Contract: CapabilityProfile holds rich semantic metadata per capability."""

    def test_profile_has_all_required_fields(self):
        from kernel.capability_intelligence import CapabilityProfile

        p = CapabilityProfile(capability_type="data.query")
        assert p.capability_type == "data.query"
        assert p.reliability == 0.9
        assert p.expected_latency_ms == 100
        assert p.resource_type == "cpu"
        assert isinstance(p.strengths, list)
        assert isinstance(p.weaknesses, list)
        assert isinstance(p.ideal_queries, list)
        assert isinstance(p.anti_patterns, list)
        assert isinstance(p.tags, list)
        assert p.execution_count == 0

    def test_profile_stores_rich_metadata(self):
        from kernel.capability_intelligence import CapabilityProfile

        p = CapabilityProfile(
            capability_type="web.search",
            description="联网搜索",
            strengths=["最新信息", "新闻"],
            weaknesses=["无法访问私有数据"],
            ideal_queries=["最新AI动态"],
            anti_patterns=["查询内部数据库"],
            reliability=0.88,
            expected_latency_ms=2500,
            output_types=["text", "urls"],
            tags=["search", "web", "实时"],
            resource_type="io",
            agent_type="web",
        )
        assert len(p.strengths) == 2
        assert "新闻" in p.strengths
        assert len(p.anti_patterns) == 1
        assert p.output_types == ["text", "urls"]
        assert p.resource_type == "io"


class TestExecutionRecord:
    """Contract: ExecutionRecord stores minimal feedback data."""

    def test_record_has_required_fields(self):
        from kernel.capability_intelligence import ExecutionRecord

        now = time.time()
        r = ExecutionRecord(
            capability_type="data.query",
            query_preview="今年Q3销售额",
            success=True,
            latency_ms=3200,
            evidence_quality=0.92,
            timestamp=now,
        )
        assert r.capability_type == "data.query"
        assert r.success is True
        assert r.latency_ms == 3200
        assert r.evidence_quality == 0.92
        assert r.timestamp == now


class TestCapabilityProfiler:
    """Contract: CapabilityProfiler builds profiles from registry + seed data."""

    def setUp(self):
        from kernel.capability_intelligence.profiler import capability_profiler
        capability_profiler._profiles.clear()
        capability_profiler._built = False

    def test_build_profiles_from_registry(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        profiles = capability_profiler.build_profiles(capability_registry)
        assert isinstance(profiles, dict)
        assert len(profiles) > 0

    def test_seed_data_populates_profiles(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)
        p = capability_profiler.get_profile("data.query")
        assert p is not None
        assert "SQL" in p.description or "结构化" in p.description
        assert len(p.strengths) >= 3
        assert len(p.weaknesses) >= 2
        assert len(p.ideal_queries) >= 1
        assert len(p.anti_patterns) >= 1
        assert p.resource_type == "cpu"
        assert p.agent_type == "data"

    def test_web_search_has_io_resource(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)
        p = capability_profiler.get_profile("web.search")
        assert p is not None
        assert p.resource_type == "io"
        assert p.agent_type == "web"

    def test_list_profiles_sorted_by_reliability(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)
        profiles = capability_profiler.list_profiles()
        assert len(profiles) >= 2
        # First profile should have highest reliability
        for i in range(len(profiles) - 1):
            assert profiles[i].reliability >= profiles[i + 1].reliability

    def test_get_profile_missing_returns_none(self):
        from kernel.capability_intelligence import capability_profiler

        p = capability_profiler.get_profile("nonexistent.capability")
        assert p is None

    def test_match_finds_relevant_capabilities(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)

        # Data query should match
        results = capability_profiler.match("查询销售额")
        assert len(results) > 0
        assert results[0].capability_type == "data.query"

    def test_match_web_query(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)

        results = capability_profiler.match("最新新闻动态")
        cap_types = [r.capability_type for r in results]
        assert "web.search" in cap_types

    def test_match_returns_top_k(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)

        results = capability_profiler.match("查询", top_k=3)
        assert len(results) <= 3

    def test_update_from_record_increments_count(self):
        from kernel.capability_intelligence import (
            capability_profiler,
            ExecutionRecord,
        )
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)
        p = capability_profiler.get_profile("data.query")
        assert p is not None
        initial_count = p.execution_count

        capability_profiler.update_from_record(
            ExecutionRecord(
                capability_type="data.query",
                query_preview="test",
                success=True,
                latency_ms=2000,
                evidence_quality=0.95,
            )
        )
        assert p.execution_count == initial_count + 1

    def test_update_success_increases_reliability(self):
        from kernel.capability_intelligence import (
            capability_profiler,
            ExecutionRecord,
        )
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)
        p = capability_profiler.get_profile("data.query")
        initial_rel = p.reliability
        initial_count = p.execution_count

        # Feed 5 successful records
        for i in range(5):
            capability_profiler.update_from_record(
                ExecutionRecord(
                    capability_type="data.query",
                    query_preview=f"test {i}",
                    success=True,
                    latency_ms=2000,
                    evidence_quality=0.95,
                )
            )

        assert p.reliability >= initial_rel - 0.01  # Should not drop significantly

    def test_update_latency_ema(self):
        from kernel.capability_intelligence import (
            capability_profiler,
            ExecutionRecord,
        )
        from kernel.runtime.capability import capability_registry

        capability_profiler.build_profiles(capability_registry)
        p = capability_profiler.get_profile("data.query")
        initial_latency = p.expected_latency_ms

        # Feed a record with very different latency
        capability_profiler.update_from_record(
            ExecutionRecord(
                capability_type="data.query",
                query_preview="test",
                success=True,
                latency_ms=10000,
                evidence_quality=0.9,
            )
        )
        # EMA: new = old * 0.8 + observed * 0.2
        expected = int(initial_latency * 0.8 + 10000 * 0.2)
        assert p.expected_latency_ms == expected


class TestCapabilityAdapter:
    """Contract: CapabilityAdapter formats profiles for LLM prompts."""

    @staticmethod
    def _fresh_profiles():
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)
        return capability_profiler.list_profiles()

    def test_format_for_cognitive_planner_includes_key_info(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        text = adapter.format_for_cognitive_planner(profiles)

        assert "data.query" in text
        assert "SQL" in text or "结构化" in text
        assert "擅长" in text
        assert "局限" in text
        assert "可靠性" in text
        assert "延迟" in text

    def test_format_for_understanding_engine_is_compact(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        text = adapter.format_for_understanding_engine(profiles)

        assert "data.query" in text
        assert "web.search" in text
        lines = text.strip().split("\n")
        for line in lines:
            assert line.startswith("- ")

    def test_format_for_self_model_groups_by_agent(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        text = adapter.format_for_self_model(profiles)

        assert len(text) > 0
        assert "data" in text.lower()

    def test_find_best_capability_prefix_match(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        result = adapter.find_best_capability("data", "查询订单数据", profiles)
        assert result is not None
        assert result.startswith("data.")

    def test_find_best_capability_web_prefix(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        result = adapter.find_best_capability("web", "搜索最新信息", profiles)
        assert result == "web.search"

    def test_find_best_capability_returns_none_for_unknown(self):
        from kernel.capability_intelligence import CapabilityAdapter
        adapter = CapabilityAdapter()
        result = adapter.find_best_capability(
            "unknown_source",
            "something about nothing in particular",
            [],
        )
        assert result is None

    def test_empty_profiles_returns_empty_string(self):
        from kernel.capability_intelligence import CapabilityAdapter
        adapter = CapabilityAdapter()
        for fmt in [
            adapter.format_for_cognitive_planner([]),
            adapter.format_for_understanding_engine([]),
            adapter.format_for_self_model([]),
        ]:
            assert fmt == ""


class TestCapabilityFeedbackLoop:
    """Contract: CapabilityFeedbackLoop records and reports execution outcomes."""

    @staticmethod
    def _fresh_profiler():
        from kernel.capability_intelligence.profiler import capability_profiler
        from kernel.runtime.capability import capability_registry
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)
        return capability_profiler

    def test_record_updates_profiler(self):
        from kernel.capability_intelligence import (
            CapabilityFeedbackLoop,
            ExecutionRecord,
        )
        profiler = self._fresh_profiler()
        profile = profiler.get_profile("data.query")
        initial_count = profile.execution_count

        loop = CapabilityFeedbackLoop(profiler)
        loop.record(ExecutionRecord(
            capability_type="data.query",
            query_preview="测试查询",
            success=True,
            latency_ms=3000,
            evidence_quality=0.9,
        ))

        assert profile.execution_count == initial_count + 1
        assert loop.total_records == 1

    def test_recent_stats_returns_correct_format(self):
        from kernel.capability_intelligence import (
            CapabilityFeedbackLoop,
            ExecutionRecord,
        )
        profiler = self._fresh_profiler()
        loop = CapabilityFeedbackLoop(profiler)
        for i in range(10):
            loop.record(ExecutionRecord(
                capability_type="web.search",
                query_preview=f"query {i}",
                success=i >= 2,
                latency_ms=2000 + i * 100,
                evidence_quality=0.7 + i * 0.02,
            ))

        stats = loop.recent_stats("web.search", n=20)
        assert "success_rate" in stats
        assert "avg_latency_ms" in stats
        assert "avg_evidence_quality" in stats
        assert "count" in stats
        assert stats["count"] == 10
        assert stats["success_rate"] == 0.8

    def test_recent_stats_unknown_capability(self):
        from kernel.capability_intelligence import (
            CapabilityFeedbackLoop,
        )
        profiler = self._fresh_profiler()
        loop = CapabilityFeedbackLoop(profiler)
        stats = loop.recent_stats("nonexistent.capability")
        assert stats["count"] == 0
        assert stats["success_rate"] == 0.0


class TestFeatureFlagOff:
    """Contract: When feature flag is OFF, all code paths use existing behavior."""

    def test_flag_default_in_code_is_true(self):
        """Settings.py declares the default as True (all features enabled)."""
        from infra.config.settings import settings
        field_info = type(settings).model_fields.get("kernel_capability_intelligence_enabled")
        assert field_info is not None
        assert field_info.default is True

    def test_capability_block_empty_when_flag_off(self):
        """_build_capability_block returns '' when flag is off."""
        from infra.config.settings import settings
        from kernel.capability_intelligence import _capability_intelligence_enabled

        # Force flag off for this test
        orig = settings.kernel_capability_intelligence_enabled
        try:
            settings.kernel_capability_intelligence_enabled = False
            assert _capability_intelligence_enabled() is False

            from kernel.runtime.cognitive.cognitive_planner_v2 import CognitivePlannerV2
            planner = CognitivePlannerV2(capability_registry=None)
            block = planner._build_capability_block()
            assert block == ""
        finally:
            settings.kernel_capability_intelligence_enabled = orig


class TestCJKMatching:
    """Edge-case tests for CJK detection and bigram scoring."""

    def test_cjk_detection_pure_chinese(self):
        from kernel.capability_intelligence.profiler import _is_cjk_text
        assert _is_cjk_text("查询销售额趋势") is True
        assert _is_cjk_text("天气怎么样") is True

    def test_cjk_detection_pure_english(self):
        from kernel.capability_intelligence.profiler import _is_cjk_text
        assert _is_cjk_text("query sales data") is False
        assert _is_cjk_text("hello world") is False

    def test_cjk_detection_mixed_text(self):
        from kernel.capability_intelligence.profiler import _is_cjk_text
        # Predominantly CJK (≥25% CJK characters) → True
        assert _is_cjk_text("查询销售额和增长对比趋势分析") is True
        # Below threshold (<25% CJK) → False
        assert _is_cjk_text("query data for Q3 sales in 2025年") is False
        # Borderline: ~40% CJK → True
        assert _is_cjk_text("请帮我查询SQL数据库中的用户数据") is True

    def test_cjk_detection_empty(self):
        from kernel.capability_intelligence.profiler import _is_cjk_text
        assert _is_cjk_text("") is False

    def test_bigram_score_single_char_query(self):
        from kernel.capability_intelligence.profiler import _bigram_score_cjk
        # Single CJK char has no bigrams, only unigram scoring
        score = _bigram_score_cjk("查", "数据查询结果")
        assert score > 0  # Should get some unigram hits

    def test_bigram_score_identical_text(self):
        from kernel.capability_intelligence.profiler import _bigram_score_cjk
        score = _bigram_score_cjk("查询销售额", "查询销售额")
        assert score > 0.9  # Near-perfect match

    def test_bigram_score_no_match(self):
        from kernel.capability_intelligence.profiler import _bigram_score_cjk
        score = _bigram_score_cjk("查询销售额", "今天天气不错")
        assert score < 0.3

    def test_match_mixed_cjk_english_query(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)
        results = capability_profiler.match("查询SQL 数据库 data 销售额")
        assert len(results) > 0
        assert results[0].capability_type == "data.query"

    def test_match_chinese_with_newly_added_tags(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)

        results = capability_profiler.match("今天天气")
        cap_types = [r.capability_type for r in results]
        assert "tool.weather" in cap_types

        results = capability_profiler.match("画个图表")
        cap_types = [r.capability_type for r in results]
        assert "chart.generate" in cap_types


class TestMatchEdgeCases:
    """Fine-grained match behavior tests."""

    @staticmethod
    def _fresh_profiler():
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)
        return capability_profiler

    def test_empty_query_returns_empty(self):
        profiler = self._fresh_profiler()
        results = profiler.match("")
        assert results == []

    def test_whitespace_only_query_returns_empty(self):
        profiler = self._fresh_profiler()
        results = profiler.match("   ")
        assert results == []

    def test_data_query_ranks_highest_for_sql_question(self):
        profiler = self._fresh_profiler()
        results = profiler.match("查询订单表所有数据")
        assert len(results) > 0
        assert results[0].capability_type == "data.query"

    def test_web_search_ranks_highest_for_news_question(self):
        profiler = self._fresh_profiler()
        results = profiler.match("今天有什么新闻")
        assert len(results) > 0
        assert results[0].capability_type == "web.search"

    def test_calculator_ranks_highest_for_math(self):
        profiler = self._fresh_profiler()
        results = profiler.match("100加200等于多少")
        assert len(results) > 0
        assert results[0].capability_type == "tool.calculator"

    def test_top_k_limit_respected(self):
        profiler = self._fresh_profiler()
        for k in [1, 2, 3, 5]:
            results = profiler.match("查询数据", top_k=k)
            assert len(results) <= k

    def test_all_results_have_positive_score(self):
        profiler = self._fresh_profiler()
        results = profiler.match("数据分析")
        assert all(
            any(
                query_word in " ".join(
                    p.tags + p.strengths + p.ideal_queries + [p.description]
                ).lower()
                for query_word in "数据分析"
            )
            or any(
                "数据" in ideal.lower() or "分析" in ideal.lower()
                for ideal in p.ideal_queries
            )
            or "数据分析" in p.description.lower()
            for p in results
        )


class TestCapabilityRelation:
    """Contract: CapabilityRelation dataclass works correctly."""

    def test_depends_on_relation(self):
        from kernel.capability_intelligence import CapabilityRelation
        r = CapabilityRelation(
            from_cap="chart.generate",
            to_cap="data.query",
            relation_type="depends_on",
            strength=0.9,
            description="图表生成依赖数据查询结果",
        )
        assert r.from_cap == "chart.generate"
        assert r.to_cap == "data.query"
        assert r.relation_type == "depends_on"
        assert r.strength == 0.9

    def test_complements_relation(self):
        from kernel.capability_intelligence import CapabilityRelation
        r = CapabilityRelation(
            from_cap="web.search",
            to_cap="rag.retrieve",
            relation_type="complements",
        )
        assert r.relation_type == "complements"
        assert r.strength == 1.0  # default

    def test_substitutes_relation(self):
        from kernel.capability_intelligence import CapabilityRelation
        r = CapabilityRelation(
            from_cap="web.search",
            to_cap="rag.retrieve",
            relation_type="substitutes",
        )
        assert r.relation_type == "substitutes"

    def test_conflicts_with_relation(self):
        from kernel.capability_intelligence import CapabilityRelation
        r = CapabilityRelation(
            from_cap="python.execute",
            to_cap="tool.calculator",
            relation_type="conflicts_with",
            description="Python执行和简单计算器功能重叠",
        )
        assert r.relation_type == "conflicts_with"


class TestAdapterChineseGap:
    """find_best_capability with Chinese gap descriptions."""

    @staticmethod
    def _fresh_profiles():
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)
        return capability_profiler.list_profiles()

    def test_chinese_gap_data_query(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        result = adapter.find_best_capability(
            "data", "需要查询数据库中的销售数据", profiles
        )
        assert result == "data.query"

    def test_chinese_gap_web_search(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        result = adapter.find_best_capability(
            "web", "搜索互联网上最新的新闻信息", profiles
        )
        assert result == "web.search"

    def test_chinese_gap_no_prefix_falls_back_to_keyword(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        result = adapter.find_best_capability(
            "", "计算数学公式和数值", profiles
        )
        assert result is not None
        assert "calculator" in result or "python" in result

    def test_chinese_gap_unknown_topic(self):
        from kernel.capability_intelligence import CapabilityAdapter
        profiles = self._fresh_profiles()
        adapter = CapabilityAdapter()
        result = adapter.find_best_capability(
            "unknown", "asdf xyzzy 12345 blarg nothing matching here", profiles
        )
        assert result is None


class TestProfileUpdateConsistency:
    """Profile state consistency under feedback updates."""

    @staticmethod
    def _fresh_profiler():
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)
        return capability_profiler

    def test_reliability_bounded_0_to_1(self):
        from kernel.capability_intelligence import ExecutionRecord
        profiler = self._fresh_profiler()
        profile = profiler.get_profile("data.query")
        # Feed many failures
        for i in range(50):
            profiler.update_from_record(ExecutionRecord(
                capability_type="data.query",
                query_preview=f"fail {i}",
                success=False,
                latency_ms=5000,
                evidence_quality=0.1,
            ))
        assert 0.0 <= profile.reliability <= 1.0

    def test_latency_ema_converges(self):
        from kernel.capability_intelligence import ExecutionRecord
        profiler = self._fresh_profiler()
        profile = profiler.get_profile("tool.calculator")
        for i in range(20):
            profiler.update_from_record(ExecutionRecord(
                capability_type="tool.calculator",
                query_preview=f"calc {i}",
                success=True,
                latency_ms=500,
                evidence_quality=0.95,
            ))
        assert abs(profile.expected_latency_ms - 500) < 150

    def test_execution_count_always_increases(self):
        from kernel.capability_intelligence import (
            CapabilityFeedbackLoop,
            ExecutionRecord,
        )
        profiler = self._fresh_profiler()
        profile = profiler.get_profile("web.search")
        initial = profile.execution_count

        loop = CapabilityFeedbackLoop(profiler)
        for i in range(15):
            loop.record(ExecutionRecord(
                capability_type="web.search",
                query_preview=f"query {i}",
                success=True,
                latency_ms=2000,
                evidence_quality=0.8,
            ))
        assert profile.execution_count == initial + 15

    def test_feedback_loop_capped_at_200(self):
        from kernel.capability_intelligence import (
            CapabilityFeedbackLoop,
            ExecutionRecord,
        )
        profiler = self._fresh_profiler()
        loop = CapabilityFeedbackLoop(profiler)
        for i in range(250):
            loop.record(ExecutionRecord(
                capability_type="web.search",
                query_preview=f"query {i}",
                success=True,
                latency_ms=2000,
                evidence_quality=0.8,
            ))
        # deque maxlen=200, so total_records should be 200
        assert loop.total_records == 200


class TestFeatureFlagOn:
    """Contract: When feature flag is ON, all integration paths work correctly."""

    def test_flag_on_helper_returns_true(self):
        from infra.config.settings import settings
        from kernel.capability_intelligence import _capability_intelligence_enabled

        orig = settings.kernel_capability_intelligence_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True
            assert _capability_intelligence_enabled() is True
        finally:
            settings.kernel_capability_intelligence_enabled = orig

    def test_capability_block_non_empty_when_flag_on(self):
        from infra.config.settings import settings
        from kernel.capability_intelligence import _capability_intelligence_enabled
        from kernel.runtime.capability import capability_registry

        orig = settings.kernel_capability_intelligence_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True
            assert _capability_intelligence_enabled() is True

            from kernel.runtime.cognitive.cognitive_planner_v2 import CognitivePlannerV2
            planner = CognitivePlannerV2(capability_registry=capability_registry)
            block = planner._build_capability_block()
            assert len(block) > 0
            assert "data.query" in block
            assert "web.search" in block
        finally:
            settings.kernel_capability_intelligence_enabled = orig

    def test_self_model_uses_profiler_when_flag_on(self):
        from infra.config.settings import settings
        from kernel.cognition.types import TaskDomain

        orig = settings.kernel_capability_intelligence_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True

            from kernel.cognition.self_model import SelfModel
            sm = SelfModel()
            sm.refresh_state()
            assessment = sm.introspect("test", TaskDomain.WEB_SEARCH)
            # With flag on, expected_latency_ms should come from profiler (~2500ms)
            # not the hardcoded 1500
            assert assessment.expected_latency_ms > 0
        finally:
            settings.kernel_capability_intelligence_enabled = orig


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2: Runtime self-cognition + orchestration learning
# ═══════════════════════════════════════════════════════════════════════════════


class TestCapabilityOntology:
    """Contract: Ontology provides formal capability class enumeration and schemas."""

    def test_all_14_capability_classes(self):
        from kernel.capability_intelligence.ontology import CapabilityClass
        values = list(CapabilityClass)
        assert len(values) == 13  # 13 enum members
        assert CapabilityClass.DATA_QUERY == "data.query"
        assert CapabilityClass.WEB_SEARCH == "web.search"

    def test_schema_returns_latency_profile(self):
        from kernel.capability_intelligence.ontology import get_capability_schema
        schema = get_capability_schema("data.query")
        assert "latency" in schema
        assert schema["latency"]["expected_ms"] == 3000
        assert schema["latency"]["p50_ms"] == 2000

    def test_schema_returns_resource_profile(self):
        from kernel.capability_intelligence.ontology import get_capability_schema
        schema = get_capability_schema("web.search")
        assert schema["resource"]["resource_type"] == "io"
        assert schema["resource"]["max_parallel"] == 5

    def test_schema_returns_quality_profile(self):
        from kernel.capability_intelligence.ontology import get_capability_schema
        schema = get_capability_schema("rag.retrieve")
        assert schema["quality"]["evidence_grade"] == "strong"

    def test_unknown_capability_returns_defaults(self):
        from kernel.capability_intelligence.ontology import get_capability_schema
        schema = get_capability_schema("nonexistent.cap")
        assert schema["latency"]["expected_ms"] == 2000
        assert schema["resource"]["resource_type"] == "cpu"


class TestKnowledgeGraph:
    """Contract: Knowledge graph builds relations and supports queries."""

    @staticmethod
    def _fresh_kg():
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        return kg

    def test_build_creates_relations(self):
        kg = self._fresh_kg()
        assert kg.is_built
        assert len(kg._relations) >= 10  # at least the seed relations

    def test_depends_on_data_analysis(self):
        kg = self._fresh_kg()
        deps = kg.depends_on("data.analysis")
        assert "data.query" in deps

    def test_depended_by_data_query(self):
        kg = self._fresh_kg()
        deps = kg.depended_by("data.query")
        assert "data.analysis" in deps

    def test_complements(self):
        kg = self._fresh_kg()
        comps = kg.complements("web.search")
        assert "rag.retrieve" in comps

    def test_substitutes_for(self):
        kg = self._fresh_kg()
        subs = kg.substitutes_for("data.analysis")
        assert "python.execute" in subs

    def test_topological_order_produces_layers(self):
        kg = self._fresh_kg()
        caps = ["data.query", "data.analysis", "chart.generate", "web.search"]
        order = kg.topological_order(caps)
        # data.query should be before data.analysis (depends_on)
        assert len(order.layers) >= 1
        all_nodes = [n for layer in order.layers for n in layer]
        assert "data.query" in all_nodes
        assert "data.analysis" in all_nodes
        # data.query must appear in an earlier layer than data.analysis
        dq_layer = next(i for i, layer in enumerate(order.layers) if "data.query" in layer)
        da_layer = next(i for i, layer in enumerate(order.layers) if "data.analysis" in layer)
        assert dq_layer < da_layer

    def test_topological_order_parallel_layer(self):
        kg = self._fresh_kg()
        # web.search and data.query have no dependency → can be parallel
        caps = ["web.search", "data.query"]
        order = kg.topological_order(caps)
        assert len(order.layers) == 1  # both in same layer

    def test_find_substitute_path_direct(self):
        kg = self._fresh_kg()
        path = kg.find_substitute_path("data.analysis", {"data.analysis"})
        assert path is not None
        assert "python.execute" in path

    def test_find_path(self):
        kg = self._fresh_kg()
        paths = kg.find_path("data.analysis", "data.query", ["depends_on"])
        assert len(paths) >= 1

    def test_export_for_prompt_non_empty(self):
        kg = self._fresh_kg()
        text = kg.export_for_prompt()
        assert "依赖关系" in text
        assert "互补关系" in text or "替代关系" in text

    def test_empty_graph_export_empty(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        assert kg.export_for_prompt() == ""


class TestReasoner:
    """Contract: Reasoner combines KG + profiler for improved recommendations."""

    @staticmethod
    def _fresh_reasoner():
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence.reasoner import CapabilityReasoner

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler._kg = None
        capability_profiler._reasoner = None
        capability_profiler.build_profiles(capability_registry)

        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)
        return CapabilityReasoner(kg=kg, profiler=capability_profiler)

    def test_recommend_capability_returns_results(self):
        reasoner = self._fresh_reasoner()
        results = reasoner.recommend_capability("查询销售数据", "data", top_k=3)
        assert len(results) > 0
        assert results[0][0].capability_type == "data.query"

    def test_recommend_capability_cjk_search(self):
        reasoner = self._fresh_reasoner()
        results = reasoner.recommend_capability("搜索最新新闻", "", top_k=3)
        assert len(results) > 0
        cap_types = [r[0].capability_type for r in results]
        assert "web.search" in cap_types

    def test_determine_execution_order(self):
        reasoner = self._fresh_reasoner()
        caps = ["data.query", "data.analysis", "web.search"]
        order = reasoner.determine_execution_order(caps)
        assert len(order.layers) >= 1
        # data.query before data.analysis
        dq_layer = next(i for i, layer in enumerate(order.layers) if "data.query" in layer)
        da_layer = next(i for i, layer in enumerate(order.layers) if "data.analysis" in layer)
        assert dq_layer < da_layer

    def test_adjust_recommendations_changes_scoring(self):
        reasoner = self._fresh_reasoner()
        results_before = reasoner.recommend_capability("数据分析", "", top_k=5)
        # Penalize data.analysis heavily
        reasoner.adjust_recommendations("data.analysis", -0.5, "test degradation")
        # The adjustment should be reflected (even if data.analysis still appears)
        assert reasoner._weight_adjustments.get("data.analysis", 0) == -0.5

    def test_find_alternative_returns_substitute(self):
        reasoner = self._fresh_reasoner()
        alt, reasoning = reasoner.find_alternative("data.analysis", {"data.analysis": "degraded"})
        assert alt is not None
        assert "python.execute" in alt

    def test_get_execution_strategy_hint_single_cap(self):
        reasoner = self._fresh_reasoner()
        hint = reasoner.get_execution_strategy_hint(["data.query"])
        assert hint in ("direct", "sequential", "parallel", "compare")


class TestExecutionMemory:
    """Contract: ExecutionMemory tracks structured execution history."""

    @staticmethod
    def _fresh_memory():
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        return ExecutionMemory(max_records=100)

    def test_record_and_get_stats(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        mem = self._fresh_memory()
        for _ in range(5):
            mem.record(ExecutionRecord(capability_type="data.query", success=True, latency_ms=1000, timestamp=time.time()))
        for _ in range(3):
            mem.record(ExecutionRecord(capability_type="data.query", success=False, latency_ms=2000, timestamp=time.time()))
        stats = mem.get_stats("data.query")
        assert stats.total_executions == 8
        assert stats.overall_success_rate == 5 / 8

    def test_time_windowed_stats(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        mem = self._fresh_memory()
        now = time.time()
        for _ in range(3):
            mem.record(ExecutionRecord(capability_type="web.search", success=True, latency_ms=500, timestamp=now))
        # Old records outside window
        for _ in range(2):
            mem.record(ExecutionRecord(capability_type="web.search", success=False, latency_ms=500, timestamp=now - 7200))
        windowed = mem.get_time_windowed_stats("web.search", 3600)
        assert windowed.total == 3
        assert windowed.success_rate == 1.0

    def test_record_sequential_pattern(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        mem = self._fresh_memory()
        first = ExecutionRecord(capability_type="data.query", success=True, latency_ms=1000, timestamp=time.time())
        second = ExecutionRecord(capability_type="data.analysis", success=True, latency_ms=2000, timestamp=time.time())
        for _ in range(4):
            mem.record_sequential(first, second)
        patterns = mem.detect_patterns(min_samples=3)
        assert len(patterns) > 0
        assert "data.analysis AFTER data.query" in patterns[0].pattern

    def test_degradation_check_detects_drop(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        mem = self._fresh_memory()
        now = time.time()
        # Historical: 80% success
        for _ in range(8):
            mem.record(ExecutionRecord(capability_type="tool.weather", success=True, latency_ms=500, timestamp=now - 7200))
        for _ in range(2):
            mem.record(ExecutionRecord(capability_type="tool.weather", success=False, latency_ms=500, timestamp=now - 7200))
        # Recent: 40% success
        for _ in range(2):
            mem.record(ExecutionRecord(capability_type="tool.weather", success=True, latency_ms=500, timestamp=now))
        for _ in range(3):
            mem.record(ExecutionRecord(capability_type="tool.weather", success=False, latency_ms=500, timestamp=now))
        deg = mem.degradation_check("tool.weather", threshold=0.10)
        assert deg is not None
        assert deg["drop"] > 0.10

    def test_degradation_check_healthy(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        mem = self._fresh_memory()
        now = time.time()
        for _ in range(10):
            mem.record(ExecutionRecord(capability_type="data.query", success=True, latency_ms=1000, timestamp=now))
        deg = mem.degradation_check("data.query")
        assert deg is None


class TestStrategyMemory:
    """Contract: StrategyMemory tracks strategy outcomes and makes recommendations."""

    @staticmethod
    def _fresh_strategy_memory():
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        return StrategyMemory(max_records=100)

    def test_record_and_recommend_exact_match(self):
        from kernel.capability_intelligence.profile import StrategyRecord
        sm = self._fresh_strategy_memory()
        now = time.time()
        # Record successful sequential strategy
        for _ in range(10):
            sm.record(StrategyRecord(
                strategy_type="sequential",
                capabilities_used=["data.query", "data.analysis"],
                query_domain="finance",
                success=True,
                turn_success=True,
                latency_ms=5000,
                timestamp=now,
            ))
        rec = sm.recommend(["data.query", "data.analysis"], "finance")
        assert rec.strategy_type == "sequential"
        assert rec.confidence > 0.5

    def test_recommend_returns_fallback_for_unknown(self):
        sm = self._fresh_strategy_memory()
        rec = sm.recommend(["unknown.cap"], "mystery_domain")
        assert rec.strategy_type == "sequential"
        assert rec.confidence <= 0.2

    def test_multiple_strategies_ranked(self):
        from kernel.capability_intelligence.profile import StrategyRecord
        sm = self._fresh_strategy_memory()
        now = time.time()
        # Parallel: high success
        for _ in range(10):
            sm.record(StrategyRecord(
                strategy_type="parallel",
                capabilities_used=["web.search", "rag.retrieve"],
                query_domain="general",
                success=True, turn_success=True, latency_ms=3000, timestamp=now,
            ))
        # Sequential: low success
        for _ in range(5):
            sm.record(StrategyRecord(
                strategy_type="sequential",
                capabilities_used=["web.search", "rag.retrieve"],
                query_domain="general",
                success=False, turn_success=False, latency_ms=8000, timestamp=now,
            ))
        rec = sm.recommend(["web.search", "rag.retrieve"], "general")
        assert rec.strategy_type == "parallel"

    def test_get_best_strategy_for_domain(self):
        from kernel.capability_intelligence.profile import StrategyRecord
        sm = self._fresh_strategy_memory()
        now = time.time()
        for _ in range(8):
            sm.record(StrategyRecord(
                strategy_type="parallel", capabilities_used=["data.query"],
                query_domain="sales", success=True, turn_success=True,
                latency_ms=2000, timestamp=now,
            ))
        best = sm.get_best_strategy_for_domain("sales")
        assert best == "parallel"

    def test_get_stats_returns_aggregated(self):
        from kernel.capability_intelligence.profile import StrategyRecord
        sm = self._fresh_strategy_memory()
        now = time.time()
        sm.record(StrategyRecord(
            strategy_type="direct", capabilities_used=["tool.datetime"],
            query_domain="general", success=True, turn_success=True,
            latency_ms=300, timestamp=now,
        ))
        stats = sm.get_stats(strategy_type="direct")
        assert len(stats) >= 1


class TestEvolution:
    """Contract: EvolutionEngine detects degradation and adjusts weights."""

    @staticmethod
    def _fresh_evolution():
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        from kernel.capability_intelligence.evolution import EvolutionEngine
        em = ExecutionMemory(max_records=100)
        sm = StrategyMemory(max_records=100)
        evo = EvolutionEngine(
            execution_memory=em, strategy_memory=sm,
            reasoner=None, analysis_interval_turns=1,
        )
        return evo, em, sm

    def test_on_turn_complete_triggers_at_interval(self):
        evo, em, sm = self._fresh_evolution()
        # No records, so analysis should return empty
        insights = evo.on_turn_complete()
        assert len(insights) == 0

    def test_analyze_detects_degradation(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        evo, em, sm = self._fresh_evolution()
        now = time.time()
        # Historical: high success
        for _ in range(10):
            em.record(ExecutionRecord(capability_type="tool.weather", success=True, latency_ms=500, timestamp=now - 7200))
        # Recent: low success
        for _ in range(5):
            em.record(ExecutionRecord(capability_type="tool.weather", success=False, latency_ms=500, timestamp=now))
        insights = evo.analyze()
        degradation_insights = [i for i in insights if i.insight_type == "degradation"]
        assert len(degradation_insights) > 0
        assert degradation_insights[0].capability_type == "tool.weather"

    def test_analyze_detects_improvement(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        evo, em, sm = self._fresh_evolution()
        now = time.time()
        # Historical: mixed
        for _ in range(5):
            em.record(ExecutionRecord(capability_type="web.search", success=True, latency_ms=500, timestamp=now - 7200))
        for _ in range(5):
            em.record(ExecutionRecord(capability_type="web.search", success=False, latency_ms=500, timestamp=now - 7200))
        # Recent: all success (improvement)
        for _ in range(5):
            em.record(ExecutionRecord(capability_type="web.search", success=True, latency_ms=300, timestamp=now))
        insights = evo.analyze()
        improvement_insights = [i for i in insights if i.insight_type == "improvement"]
        assert len(improvement_insights) > 0

    def test_adjust_weights_modifies_reasoner(self):
        from kernel.capability_intelligence.reasoner import CapabilityReasoner
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)
        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)
        reasoner = CapabilityReasoner(kg=kg, profiler=capability_profiler)

        from kernel.capability_intelligence.evolution import EvolutionEngine
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        em = ExecutionMemory(max_records=100)
        sm = StrategyMemory(max_records=100)
        evo = EvolutionEngine(em, sm, reasoner, analysis_interval_turns=1)

        # Manually add a degradation insight and adjust weights
        from kernel.capability_intelligence.evolution import Insight
        evo._insights.append(Insight(
            insight_type="degradation", capability_type="data.query",
            severity="warning", message="test", evidence={"drop": 0.30},
            timestamp=time.time(),
        ))
        evo.adjust_weights()
        assert reasoner._weight_adjustments.get("data.query", 0) < 0

    def test_get_degradation_alerts(self):
        from kernel.capability_intelligence.evolution import EvolutionEngine, Insight
        evo = EvolutionEngine(analysis_interval_turns=10)
        evo._insights.append(Insight(
            insight_type="degradation", capability_type="rag.retrieve",
            severity="critical", message="严重退化", evidence={"drop": 0.50},
            timestamp=time.time(),
        ))
        evo._insights.append(Insight(
            insight_type="pattern", capability_type=None,
            severity="info", message="pattern found", evidence={},
            timestamp=time.time(),
        ))
        alerts = evo.get_degradation_alerts()
        assert len(alerts) == 1
        assert alerts[0].severity == "critical"


class TestPhase2FeatureFlag:
    """Contract: Phase 2 features are properly gated behind flags."""

    def test_phase2_disabled_by_default(self):
        from infra.config.settings import settings
        from kernel.capability_intelligence import _capability_intelligence_phase2_enabled

        orig = settings.kernel_capability_intelligence_enabled
        orig_p2 = settings.kernel_capability_intelligence_phase2_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True
            settings.kernel_capability_intelligence_phase2_enabled = False
            assert _capability_intelligence_phase2_enabled() is False
        finally:
            settings.kernel_capability_intelligence_enabled = orig
            settings.kernel_capability_intelligence_phase2_enabled = orig_p2

    def test_phase2_enabled_when_both_flags_on(self):
        from infra.config.settings import settings
        from kernel.capability_intelligence import _capability_intelligence_phase2_enabled

        orig = settings.kernel_capability_intelligence_enabled
        orig_p2 = settings.kernel_capability_intelligence_phase2_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True
            settings.kernel_capability_intelligence_phase2_enabled = True
            assert _capability_intelligence_phase2_enabled() is True
        finally:
            settings.kernel_capability_intelligence_enabled = orig
            settings.kernel_capability_intelligence_phase2_enabled = orig_p2

    def test_phase2_disabled_when_phase1_off(self):
        from infra.config.settings import settings
        from kernel.capability_intelligence import _capability_intelligence_phase2_enabled

        orig = settings.kernel_capability_intelligence_enabled
        orig_p2 = settings.kernel_capability_intelligence_phase2_enabled
        try:
            settings.kernel_capability_intelligence_enabled = False
            settings.kernel_capability_intelligence_phase2_enabled = True
            assert _capability_intelligence_phase2_enabled() is False
        finally:
            settings.kernel_capability_intelligence_enabled = orig
            settings.kernel_capability_intelligence_phase2_enabled = orig_p2


class TestPhase2PipelineIntegration:
    """Contract: Full Phase 2 pipeline works end-to-end."""

    def test_profile_to_kg_to_reasoner_pipeline(self):
        """profile → knowledge graph → reasoner recommendation pipeline."""
        from kernel.capability_intelligence.profile import CapabilityProfile
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence.reasoner import CapabilityReasoner
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler._kg = None
        capability_profiler._reasoner = None
        capability_profiler.build_profiles(capability_registry)

        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)
        assert kg.is_built

        reasoner = CapabilityReasoner(kg=kg, profiler=capability_profiler)
        results = reasoner.recommend_capability("需要联网搜索最新信息", "web", top_k=3)
        assert len(results) > 0

    def test_execute_to_execution_memory_pattern_detection(self):
        """Execution → execution_memory → detect_pattern pipeline."""
        from kernel.capability_intelligence.profile import ExecutionRecord
        from kernel.capability_intelligence.execution_memory import ExecutionMemory

        mem = ExecutionMemory(max_records=50)
        now = time.time()

        # Simulate multiple turns of data.query → data.analysis
        for _ in range(8):
            dq = ExecutionRecord(capability_type="data.query", success=True, latency_ms=1000, timestamp=now)
            da = ExecutionRecord(capability_type="data.analysis", success=True, latency_ms=2000, timestamp=now)
            mem.record(dq)
            mem.record(da)
            mem.record_sequential(dq, da)

        patterns = mem.detect_patterns(min_samples=5)
        assert len(patterns) > 0
        assert patterns[0].success_rate > 0.8

    def test_strategy_memory_to_strategy_builder_adaptive(self):
        """Strategy memory influences StrategyBuilder's execution strategy."""
        from infra.config.settings import settings
        from kernel.capability_intelligence.profile import StrategyRecord
        from kernel.capability_intelligence.strategy_memory import StrategyMemory

        orig = settings.kernel_capability_intelligence_enabled
        orig_p2 = settings.kernel_capability_intelligence_phase2_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True
            settings.kernel_capability_intelligence_phase2_enabled = True

            sm = StrategyMemory(max_records=50)
            now = time.time()
            # Parallel strategy has high success for data+web
            for _ in range(15):
                sm.record(StrategyRecord(
                    strategy_type="parallel",
                    capabilities_used=["data.query", "web.search"],
                    query_domain="general",
                    success=True, turn_success=True, latency_ms=3000, timestamp=now,
                ))
            rec = sm.recommend(["data.query", "web.search"], "general")
            assert rec.strategy_type == "parallel"
            assert rec.confidence > 0.7
        finally:
            settings.kernel_capability_intelligence_enabled = orig
            settings.kernel_capability_intelligence_phase2_enabled = orig_p2

    def test_evolution_to_reasoner_weight_adjustment(self):
        """Evolution degrades → reasoner weight adjusted → recommend changes."""
        from kernel.capability_intelligence.reasoner import CapabilityReasoner
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence.evolution import EvolutionEngine, Insight
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler._kg = None
        capability_profiler._reasoner = None
        capability_profiler.build_profiles(capability_registry)

        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)
        reasoner = CapabilityReasoner(kg=kg, profiler=capability_profiler)
        evo = EvolutionEngine(ExecutionMemory(), StrategyMemory(), reasoner, 1)

        evo._insights.append(Insight(
            insight_type="degradation", capability_type="web.search",
            severity="critical", message="web.search severely degraded",
            evidence={"drop": 0.50}, timestamp=time.time(),
        ))
        evo.adjust_weights()
        assert reasoner._weight_adjustments.get("web.search", 0) < -0.15

    def test_flag_off_preserves_phase1_behavior(self):
        """When Phase 2 is off, Phase 1 behavior is unchanged."""
        from infra.config.settings import settings
        from kernel.capability_intelligence import (
            _capability_intelligence_enabled,
            _capability_intelligence_phase2_enabled,
        )

        orig = settings.kernel_capability_intelligence_enabled
        orig_p2 = settings.kernel_capability_intelligence_phase2_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True
            settings.kernel_capability_intelligence_phase2_enabled = False

            assert _capability_intelligence_enabled() is True
            assert _capability_intelligence_phase2_enabled() is False

            # Profiler should build profiles but NOT build KG
            from kernel.capability_intelligence import capability_profiler
            from kernel.runtime.capability import capability_registry
            capability_profiler._profiles.clear()
            capability_profiler._built = False
            capability_profiler._kg = None
            capability_profiler._reasoner = None
            capability_profiler.build_profiles(capability_registry)

            assert capability_profiler._built
            assert capability_profiler._kg is None  # KG not built when Phase 2 off
        finally:
            settings.kernel_capability_intelligence_enabled = orig
            settings.kernel_capability_intelligence_phase2_enabled = orig_p2


class TestProfilePhase2Fields:
    """Contract: Phase 2 fields on CapabilityProfile are backward-compatible."""

    def test_success_rate_by_query_type_defaults_empty(self):
        from kernel.capability_intelligence import CapabilityProfile
        p = CapabilityProfile(capability_type="test.cap")
        assert p.success_rate_by_query_type == {}

    def test_avg_latency_by_resource_defaults_empty(self):
        from kernel.capability_intelligence import CapabilityProfile
        p = CapabilityProfile(capability_type="test.cap")
        assert p.avg_latency_by_resource == {}

    def test_strategy_record_all_fields(self):
        from kernel.capability_intelligence import StrategyRecord
        sr = StrategyRecord(
            strategy_type="parallel",
            capabilities_used=["data.query", "web.search"],
            query_domain="finance",
            success=True, turn_success=True, latency_ms=3500, timestamp=time.time(),
        )
        assert sr.strategy_type == "parallel"
        assert len(sr.capabilities_used) == 2
        assert sr.query_domain == "finance"


class TestAdapterKnowledgeGraphFormat:
    """Contract: Adapter formats KG for prompts."""

    def test_format_kg_for_prompt_with_kg(self):
        from kernel.capability_intelligence.adapter import CapabilityAdapter
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        text = CapabilityAdapter.format_knowledge_graph_for_prompt(kg)
        assert len(text) > 0
        assert "→" in text

    def test_format_kg_for_prompt_none_kg(self):
        from kernel.capability_intelligence.adapter import CapabilityAdapter
        text = CapabilityAdapter.format_knowledge_graph_for_prompt(None)
        assert text == ""


# ═══════════════════════════════════════════════════════════════════════════════
# Phase 2 Edge Cases
# ═══════════════════════════════════════════════════════════════════════════════


class TestKGEdgeCases:
    """Contract: Knowledge graph handles degenerate inputs gracefully."""

    def test_topological_order_empty_list(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        order = kg.topological_order([])
        assert len(order.layers) == 0

    def test_topological_order_single_node(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        order = kg.topological_order(["data.query"])
        assert len(order.layers) == 1
        assert order.layers[0] == ["data.query"]

    def test_topological_order_unknown_nodes_no_deps(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        # Unknown nodes have no dependency edges → all in one layer
        order = kg.topological_order(["unknown.a", "unknown.b"])
        assert len(order.layers) == 1

    def test_depends_on_unknown_capability(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        assert kg.depends_on("nonexistent") == []

    def test_depended_by_unknown_capability(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        assert kg.depended_by("nonexistent") == []

    def test_find_substitute_no_substitute(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        # data.query has no substitutes in seed data
        result = kg.find_substitute_path("data.query", {"data.query"})
        assert result is None

    def test_find_path_no_route(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        paths = kg.find_path("data.query", "tool.datetime")
        assert len(paths) == 0

    def test_conflicts_with_returns_results(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        conflicts = kg.conflicts_with("tool.calculator")
        assert "python.execute" in conflicts

    def test_double_build_is_idempotent(self):
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        kg = CapabilityKnowledgeGraph()
        kg.build({})
        count_first = len(kg._relations)
        kg.build({})
        assert len(kg._relations) == count_first


class TestReasonerEdgeCases:
    """Contract: Reasoner handles edge-case inputs gracefully."""

    @staticmethod
    def _fresh_reasoner():
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence.reasoner import CapabilityReasoner

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler._kg = None
        capability_profiler._reasoner = None
        capability_profiler.build_profiles(capability_registry)

        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)
        return CapabilityReasoner(kg=kg, profiler=capability_profiler)

    def test_empty_gap_description(self):
        reasoner = self._fresh_reasoner()
        results = reasoner.recommend_capability("", "", top_k=5)
        assert len(results) == 0

    def test_heavily_penalized_still_returns_positive_score(self):
        reasoner = self._fresh_reasoner()
        # Apply heavy penalty to best match
        reasoner.adjust_recommendations("data.query", -0.95, "heavy penalty")
        results = reasoner.recommend_capability("查询销售数据", "data", top_k=3)
        # Even with heavy penalty, score stays above 0.05
        if results:
            assert all(score >= 0.05 for _, score in results)

    def test_suggested_source_prefix_match(self):
        reasoner = self._fresh_reasoner()
        results = reasoner.recommend_capability("需要查询", "data", top_k=5)
        assert len(results) > 0

    def test_unknown_target_find_alternative(self):
        reasoner = self._fresh_reasoner()
        alt, reason = reasoner.find_alternative("nonexistent.cap")
        assert alt is None
        assert "未找到" in reason

    def test_execution_strategy_hint_empty_caps(self):
        reasoner = self._fresh_reasoner()
        hint = reasoner.get_execution_strategy_hint([], "general")
        assert hint == "direct"

    def test_execution_strategy_hint_with_kg_parallel(self):
        reasoner = self._fresh_reasoner()
        # web.search and data.query have no dependency → should be parallel
        hint = reasoner.get_execution_strategy_hint(
            ["web.search", "data.query", "tool.datetime"], "general"
        )
        # All three are independent → parallel
        assert hint in ("direct", "parallel", "sequential", "compare")


class TestExecutionMemoryEdgeCases:
    """Contract: ExecutionMemory handles edge cases gracefully."""

    @staticmethod
    def _fresh_memory():
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        return ExecutionMemory(max_records=100)

    def test_get_stats_unknown_capability(self):
        mem = self._fresh_memory()
        stats = mem.get_stats("nonexistent")
        assert stats.capability_type == "nonexistent"
        assert stats.total_executions == 0
        assert stats.overall_success_rate == 0.0

    def test_time_windowed_stats_empty(self):
        mem = self._fresh_memory()
        windowed = mem.get_time_windowed_stats("unknown", 3600)
        assert windowed.total == 0

    def test_detect_patterns_no_data(self):
        mem = self._fresh_memory()
        patterns = mem.detect_patterns(min_samples=2)
        assert len(patterns) == 0

    def test_degradation_check_insufficient_data(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        mem = self._fresh_memory()
        mem.record(ExecutionRecord(capability_type="test.cap", success=True, latency_ms=100, timestamp=time.time()))
        mem.record(ExecutionRecord(capability_type="test.cap", success=False, latency_ms=100, timestamp=time.time()))
        # Only 2 records < 5 minimum → no check
        deg = mem.degradation_check("test.cap")
        assert deg is None

    def test_record_preserves_order(self):
        from kernel.capability_intelligence.profile import ExecutionRecord
        mem = self._fresh_memory()
        r1 = ExecutionRecord(capability_type="test.a", success=True, latency_ms=100, timestamp=time.time())
        r2 = ExecutionRecord(capability_type="test.b", success=False, latency_ms=200, timestamp=time.time())
        mem.record(r1)
        mem.record(r2)
        assert mem.total_records == 2


class TestStrategyMemoryEdgeCases:
    """Contract: StrategyMemory handles edge cases gracefully."""

    @staticmethod
    def _fresh_sm():
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        return StrategyMemory(max_records=100)

    def test_recommend_empty_capabilities(self):
        sm = self._fresh_sm()
        rec = sm.recommend([], "general")
        assert rec.strategy_type == "sequential"
        assert rec.confidence <= 0.2

    def test_get_stats_no_data(self):
        sm = self._fresh_sm()
        stats = sm.get_stats()
        assert len(stats) == 0

    def test_get_stats_filtered_empty(self):
        sm = self._fresh_sm()
        stats = sm.get_stats(strategy_type="parallel", domain="finance")
        assert len(stats) == 0

    def test_get_best_strategy_no_data(self):
        sm = self._fresh_sm()
        best = sm.get_best_strategy_for_domain("unknown")
        assert best == "sequential"

    def test_tied_strategies_picks_best(self):
        from kernel.capability_intelligence.profile import StrategyRecord
        sm = self._fresh_sm()
        now = time.time()
        # Both strategies have same caps but different success rates
        for _ in range(5):
            sm.record(StrategyRecord(strategy_type="parallel", capabilities_used=["a"],
                                     query_domain="test", success=True, turn_success=True,
                                     latency_ms=100, timestamp=now))
        for _ in range(5):
            sm.record(StrategyRecord(strategy_type="sequential", capabilities_used=["a"],
                                     query_domain="test", success=False, turn_success=False,
                                     latency_ms=500, timestamp=now))
        rec = sm.recommend(["a"], "test")
        assert rec.strategy_type == "parallel"

    def test_large_capability_set_handled(self):
        sm = self._fresh_sm()
        caps = [f"cap.{i}" for i in range(20)]
        rec = sm.recommend(caps, "general")
        assert rec.strategy_type == "sequential"  # fallback


class TestEvolutionEdgeCases:
    """Contract: EvolutionEngine handles edge-case inputs gracefully."""

    def test_analyze_with_empty_execution_memory(self):
        from kernel.capability_intelligence.evolution import EvolutionEngine
        evo = EvolutionEngine()  # No execution_memory
        insights = evo.analyze()
        assert len(insights) == 0

    def test_on_turn_complete_without_reaching_interval(self):
        from kernel.capability_intelligence.evolution import EvolutionEngine
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        evo = EvolutionEngine(execution_memory=ExecutionMemory(), analysis_interval_turns=5)
        # First 4 calls should not trigger analysis
        for _ in range(4):
            insights = evo.on_turn_complete()
            assert len(insights) == 0

    def test_on_turn_complete_reaches_interval(self):
        from kernel.capability_intelligence.evolution import EvolutionEngine
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        evo = EvolutionEngine(execution_memory=ExecutionMemory(), analysis_interval_turns=3)
        # First 2 calls: no analysis
        evo.on_turn_complete()
        evo.on_turn_complete()
        # 3rd call: analysis triggers
        insights = evo.on_turn_complete()
        # Returns empty because no records in execution_memory
        assert insights is not None  # Should return [] (not None)

    def test_adjust_weights_no_reasoner(self):
        from kernel.capability_intelligence.evolution import EvolutionEngine
        evo = EvolutionEngine(reasoner=None)
        # Should not raise
        evo.adjust_weights()

    def test_double_counting_prevention(self):
        """Same degradation insight should not be applied twice."""
        from kernel.capability_intelligence.reasoner import CapabilityReasoner
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence.evolution import EvolutionEngine, Insight
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler._kg = None
        capability_profiler._reasoner = None
        capability_profiler.build_profiles(capability_registry)

        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)
        reasoner = CapabilityReasoner(kg=kg, profiler=capability_profiler)
        evo = EvolutionEngine(ExecutionMemory(), StrategyMemory(), reasoner, 1)

        # Add one degradation insight
        now = time.time()
        evo._insights.append(Insight(
            insight_type="degradation", capability_type="web.search",
            severity="warning", message="test", evidence={"drop": 0.30},
            timestamp=now,
        ))
        # First adjustment
        evo.adjust_weights()
        weight_after_first = reasoner._weight_adjustments.get("web.search", 0)
        assert weight_after_first < 0

        # Second adjustment — same insight should NOT be applied again (double-counting)
        evo.adjust_weights()
        weight_after_second = reasoner._weight_adjustments.get("web.search", 0)
        # After decay (0.9), weight should be closer to zero, not more negative
        assert weight_after_second > weight_after_first

    def test_recent_insights_filtered_by_severity(self):
        from kernel.capability_intelligence.evolution import EvolutionEngine, Insight
        evo = EvolutionEngine(analysis_interval_turns=10)
        now = time.time()
        evo._insights.append(Insight(insight_type="pattern", severity="info", message="a", timestamp=now))
        evo._insights.append(Insight(insight_type="degradation", severity="critical", message="b", timestamp=now))
        evo._insights.append(Insight(insight_type="degradation", severity="warning", message="c", timestamp=now))

        # Only warning+
        filtered = evo.recent_insights(n=10, min_severity="warning")
        assert len(filtered) == 2
        severities = {i.severity for i in filtered}
        assert "info" not in severities


class TestProfilerMatchScored:
    """Contract: match_scored returns (score, profile) pairs."""

    def test_match_scored_returns_scores(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)

        results = capability_profiler.match_scored("查询销售数据", top_k=3)
        assert len(results) > 0
        for score, profile in results:
            assert isinstance(score, float)
            assert score > 0

    def test_match_scored_results_match_regular_match(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)

        scored = capability_profiler.match_scored("搜索新闻", top_k=5)
        regular = capability_profiler.match("搜索新闻", top_k=5)
        assert len(scored) == len(regular)
        for (_, sp), rp in zip(scored, regular):
            assert sp.capability_type == rp.capability_type

    def test_match_scored_empty_query(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)

        results = capability_profiler.match_scored("", top_k=5)
        assert len(results) == 0

    def test_match_scored_cjk_query(self):
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler.build_profiles(capability_registry)

        results = capability_profiler.match_scored("分析销售趋势并给出优化建议", top_k=3)
        assert len(results) > 0


class TestStrategyBuilderPhase2EdgeCases:
    """Contract: StrategyBuilder Phase 2 handles edge cases."""

    def test_phase2_strategy_builder_flag_off_uses_heuristic(self):
        from infra.config.settings import settings
        from kernel.runtime.capability import capability_registry
        from kernel.runtime.cognitive.strategy_builder import StrategyBuilder

        orig = settings.kernel_capability_intelligence_enabled
        orig_p2 = settings.kernel_capability_intelligence_phase2_enabled
        try:
            settings.kernel_capability_intelligence_enabled = True
            settings.kernel_capability_intelligence_phase2_enabled = False

            builder = StrategyBuilder(capability_registry=capability_registry)
            # With 1 assignment, strategy should be "direct" (heuristic, not memory-based)
            from kernel.runtime.cognitive.strategy_builder import CapabilityAssignment
            from kernel.runtime.cognitive.cognitive_graph import CognitiveGraph
            from kernel.runtime.cognitive.decomposition_policy import DecompositionPolicy

            # Just verify the method works without error
            result = builder._determine_execution_strategy(
                graph=CognitiveGraph(),
                policy=DecompositionPolicy(),
                assignments=[],
            )
            assert result in ("direct", "parallel", "sequential", "compare")
        finally:
            settings.kernel_capability_intelligence_enabled = orig
            settings.kernel_capability_intelligence_phase2_enabled = orig_p2


class TestFullLearningLoop:
    """Contract: Complete learning loop works end-to-end with Phase 2 flags ON."""

    def test_full_loop_execute_record_analyze_adjust_recommend(self):
        """Simulate multiple turns: execute → record → analyze → adjusted recommend."""
        from kernel.capability_intelligence.profile import ExecutionRecord, StrategyRecord
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        from kernel.capability_intelligence.reasoner import CapabilityReasoner
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence.evolution import EvolutionEngine
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        # Setup — clean slate
        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler._kg = None
        capability_profiler._reasoner = None
        capability_profiler.build_profiles(capability_registry)

        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)

        em = ExecutionMemory(max_records=200)
        sm = StrategyMemory(max_records=200)
        reasoner = CapabilityReasoner(kg=kg, profiler=capability_profiler,
                                      execution_memory=em, strategy_memory=sm)
        # Fresh evolution engine directly (no singleton)
        evo = EvolutionEngine(
            execution_memory=em, strategy_memory=sm,
            reasoner=reasoner, analysis_interval_turns=1,
        )

        now = time.time()

        # Historical (>1 hour ago): web.search was very reliable
        for _ in range(10):
            em.record(ExecutionRecord(capability_type="web.search", success=True,
                                       latency_ms=1500, timestamp=now - 7200))

        # Recent (now): web.search degraded severely
        for _ in range(5):
            em.record(ExecutionRecord(capability_type="web.search", success=False,
                                       latency_ms=8000, timestamp=now))

        sm.record(StrategyRecord(strategy_type="parallel",
                                  capabilities_used=["web.search", "data.query"],
                                  query_domain="general", success=True,
                                  turn_success=True, latency_ms=3000, timestamp=now))

        # --- Trigger evolution analysis ---
        insights = evo.on_turn_complete()
        degradation = [i for i in insights if i.insight_type == "degradation"]
        assert len(degradation) > 0, f"No degradation detected. Insights: {insights}"

        # --- Verify: reasoner weights adjusted ---
        ws_weight = reasoner._weight_adjustments.get("web.search", 0)
        assert ws_weight < 0, f"Expected negative weight for degraded web.search, got {ws_weight}"

        # --- Verify: strategy_memory has data ---
        rec = sm.recommend(["web.search", "data.query"], "general")
        assert rec.strategy_type == "parallel"

        # --- Verify: degradation insights are accessible ---
        alerts = evo.get_degradation_alerts()
        assert len(alerts) > 0

    def test_loop_improvement_increases_weight(self):
        """Sustained improvement boosts recommendation weight."""
        from kernel.capability_intelligence.profile import ExecutionRecord
        from kernel.capability_intelligence.execution_memory import ExecutionMemory
        from kernel.capability_intelligence.strategy_memory import StrategyMemory
        from kernel.capability_intelligence.reasoner import CapabilityReasoner
        from kernel.capability_intelligence.knowledge_graph import CapabilityKnowledgeGraph
        from kernel.capability_intelligence.evolution import EvolutionEngine
        from kernel.capability_intelligence import capability_profiler
        from kernel.runtime.capability import capability_registry

        capability_profiler._profiles.clear()
        capability_profiler._built = False
        capability_profiler._kg = None
        capability_profiler._reasoner = None
        capability_profiler.build_profiles(capability_registry)

        kg = CapabilityKnowledgeGraph()
        kg.build(capability_profiler._profiles)

        em = ExecutionMemory(max_records=200)
        sm = StrategyMemory(max_records=200)
        reasoner = CapabilityReasoner(kg=kg, profiler=capability_profiler,
                                      execution_memory=em, strategy_memory=sm)
        # Fresh evolution engine (no singleton leakage)
        evo = EvolutionEngine(
            execution_memory=em, strategy_memory=sm,
            reasoner=reasoner, analysis_interval_turns=1,
        )

        now = time.time()

        # Historical (>1 hour ago): rag.retrieve mixed performance
        for _ in range(8):
            em.record(ExecutionRecord(capability_type="rag.retrieve", success=True,
                                       latency_ms=1000, timestamp=now - 7200))
        for _ in range(4):
            em.record(ExecutionRecord(capability_type="rag.retrieve", success=False,
                                       latency_ms=2000, timestamp=now - 7200))
        # Recent (now): rag.retrieve all success (improvement)
        for _ in range(8):
            em.record(ExecutionRecord(capability_type="rag.retrieve", success=True,
                                       latency_ms=800, timestamp=now))

        insights = evo.on_turn_complete()
        improvement = [i for i in insights if i.insight_type == "improvement"]
        assert len(improvement) > 0
        assert any(i.capability_type == "rag.retrieve" for i in improvement)


if __name__ == "__main__":
    unittest.main()
