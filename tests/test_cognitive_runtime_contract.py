"""
Contract tests for the Cognitive Runtime V2 architecture.

Covers:
  - CognitiveGraph, GoalHierarchy, UncertaintyModel (P0-1)
  - EvidenceStateMachine, EvidenceLifecycle (P1-1)
  - ConfidenceDecay, ContradictionDetector, FactSupersessionEngine (P1-2)
  - ContextCompressor, ContextRanker (P0-2)
  - DecompositionPolicy, StrategyBuilder, ExecutionProjection (P0-1)
  - EvidenceRanker, EvidenceResolution (P1-1)

These are contract-level tests — they verify public APIs, edge cases,
and expected invariants without mocking or external dependencies.
"""

import pytest
from datetime import datetime, timezone


# ═══════════════════════════════════════════════════════════════════════════════
# Section 1: Evidence State Machine (P1-1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvidenceStateMachine:
    """Contract: EvidenceStateMachine enforces legal state transitions."""

    def test_initial_state_is_created(self):
        from kernel.runtime.evidence import EvidenceState, EvidenceStateMachine
        sm = EvidenceStateMachine()
        assert sm.state == EvidenceState.CREATED

    def test_valid_linear_path(self):
        from kernel.runtime.evidence import EvidenceState, EvidenceStateMachine
        sm = EvidenceStateMachine(EvidenceState.CREATED)
        sm.transition(EvidenceState.VALIDATED)
        sm.transition(EvidenceState.RANKED)
        sm.transition(EvidenceState.MERGED)
        sm.transition(EvidenceState.ARCHIVED)
        assert sm.state == EvidenceState.ARCHIVED
        assert sm.is_terminal() is True

    def test_invalid_transition_raises(self):
        from kernel.runtime.evidence import (
            EvidenceState,
            EvidenceStateMachine,
            InvalidTransitionError,
        )
        sm = EvidenceStateMachine(EvidenceState.CREATED)
        with pytest.raises(InvalidTransitionError):
            sm.transition(EvidenceState.MERGED)  # Can't jump CREATED → MERGED

    def test_force_transition_bypasses_validation(self):
        from kernel.runtime.evidence import EvidenceState, EvidenceStateMachine
        sm = EvidenceStateMachine()
        sm.force_transition(EvidenceState.MERGED)
        assert sm.state == EvidenceState.MERGED

    def test_can_transition_predicate(self):
        from kernel.runtime.evidence import EvidenceState, EvidenceStateMachine
        sm = EvidenceStateMachine()
        assert sm.can_transition(EvidenceState.VALIDATED) is True
        assert sm.can_transition(EvidenceState.MERGED) is False
        assert sm.can_transition(EvidenceState.INVALIDATED) is True

    def test_is_usable_vs_terminal(self):
        from kernel.runtime.evidence import EvidenceState, EvidenceStateMachine
        sm = EvidenceStateMachine()
        assert sm.is_usable() is True  # CREATED is usable
        assert sm.is_terminal() is False

        sm.transition(EvidenceState.ARCHIVED)
        assert sm.is_usable() is False  # ARCHIVED is terminal
        assert sm.is_terminal() is True

    def test_history_tracks_all_transitions(self):
        from kernel.runtime.evidence import EvidenceState, EvidenceStateMachine
        sm = EvidenceStateMachine()
        sm.transition(EvidenceState.VALIDATED)
        sm.transition(EvidenceState.RANKED)
        assert len(sm.history) == 3
        assert sm.history[0] == EvidenceState.CREATED
        assert sm.history[1] == EvidenceState.VALIDATED
        assert sm.history[2] == EvidenceState.RANKED

    def test_seven_states_all_defined(self):
        from kernel.runtime.evidence import EvidenceState
        expected = {"created", "validated", "ranked", "merged",
                     "superseded", "archived", "invalidated"}
        actual = {s.value for s in EvidenceState}
        assert actual == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Section 2: Evidence Lifecycle (P1-1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvidenceLifecycle:
    """Contract: EvidenceLifecycle manages evidence through the state machine."""

    def test_register_and_get_state(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        lc.register("ev-1")
        assert lc.get_state("ev-1") == EvidenceState.CREATED

    def test_validate_with_positive_credibility(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        lc.register("ev-1")
        state = lc.validate("ev-1", 0.8)
        assert state == EvidenceState.VALIDATED

    def test_validate_with_zero_credibility_invalidates(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        lc.register("ev-1")
        state = lc.validate("ev-1", 0.0)
        assert state == EvidenceState.INVALIDATED

    def test_rank_from_validated(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        lc.register("ev-1")
        lc.validate("ev-1", 0.9)
        state = lc.rank("ev-1")
        assert state == EvidenceState.RANKED

    def test_merge(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        lc.register("ev-1")
        lc.validate("ev-1", 0.9)
        lc.rank("ev-1")
        state = lc.merge("ev-1")
        assert state == EvidenceState.MERGED

    def test_supersede_old_and_new(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        lc.register("old")
        lc.validate("old", 0.7)
        old_state, new_state = lc.supersede("old", "new", reason="updated")
        assert old_state == EvidenceState.SUPERSEDED
        assert new_state == EvidenceState.CREATED

    def test_archive(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        lc.register("ev-1")
        state = lc.archive("ev-1")
        assert state == EvidenceState.ARCHIVED

    def test_get_usable_evidence_ids(self):
        from kernel.runtime.evidence import EvidenceLifecycle
        lc = EvidenceLifecycle()
        for i in range(10):
            lc.register(f"ev-{i}")
        # Validate half, invalidate half
        for i in range(5):
            lc.validate(f"ev-{i}", 0.8)
        for i in range(5, 10):
            lc.validate(f"ev-{i}", 0.0)
        usable = lc.get_usable_evidence_ids()
        assert len(usable) == 5  # Only the validated ones

    def test_get_by_state(self):
        from kernel.runtime.evidence import EvidenceLifecycle, EvidenceState
        lc = EvidenceLifecycle()
        for i in range(5):
            lc.register(f"ev-{i}")
            if i < 3:
                lc.validate(f"ev-{i}", 0.8)

        validated = lc.get_by_state(EvidenceState.VALIDATED)
        created = lc.get_by_state(EvidenceState.CREATED)
        assert len(validated) == 3
        assert len(created) == 2

    def test_lifecycle_summary_counts(self):
        from kernel.runtime.evidence import EvidenceLifecycle
        lc = EvidenceLifecycle()
        lc.register("a")
        lc.register("b")
        lc.validate("a", 0.8)
        summary = lc.get_lifecycle_summary()
        assert summary.get("created", 0) == 1
        assert summary.get("validated", 0) == 1

    def test_reset_clears_all(self):
        from kernel.runtime.evidence import EvidenceLifecycle
        lc = EvidenceLifecycle()
        lc.register("ev-1")
        lc.reset()
        assert lc.get_state("ev-1") is None
        assert len(lc.get_usable_evidence_ids()) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Section 3: Confidence Decay (P1-2)
# ═══════════════════════════════════════════════════════════════════════════════


class TestConfidenceDecay:
    """Contract: apply_confidence_decay correctly decays memory confidence."""

    def test_facts_decay_slower_than_conversation(self):
        from kernel.runtime.memory.confidence_decay import apply_confidence_decay
        from datetime import timedelta
        three_days_ago = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
        mems = [
            {"content": "fact", "memory_type": "fact", "confidence": 0.9,
             "created_at": three_days_ago,
             "last_accessed_at": three_days_ago, "access_count": 0},
            {"content": "chat", "memory_type": "conversation", "confidence": 0.9,
             "created_at": three_days_ago,
             "last_accessed_at": three_days_ago, "access_count": 0},
        ]
        decayed = apply_confidence_decay(mems)
        # Fact should retain more confidence than conversation (longer half-life)
        assert decayed[0]["confidence"] > decayed[1]["confidence"], \
            f"fact({decayed[0]['confidence']:.3f}) should decay slower than conversation({decayed[1]['confidence']:.3f})"

    def test_recent_memories_decay_less(self):
        from kernel.runtime.memory.confidence_decay import apply_confidence_decay
        now = datetime.now(timezone.utc).isoformat()
        mems = [
            {"content": "old", "memory_type": "fact", "confidence": 0.9,
             "created_at": "2026-01-01T00:00:00Z",
             "last_accessed_at": "2026-01-01T00:00:00Z", "access_count": 0},
            {"content": "new", "memory_type": "fact", "confidence": 0.9,
             "created_at": now, "last_accessed_at": now, "access_count": 0},
        ]
        decayed = apply_confidence_decay(mems)
        assert decayed[1]["confidence"] > decayed[0]["confidence"]

    def test_frequently_accessed_resists_decay(self):
        from kernel.runtime.memory.confidence_decay import apply_confidence_decay
        from datetime import timedelta
        ten_days_ago = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
        mems = [
            {"content": "popular", "memory_type": "fact", "confidence": 0.9,
             "created_at": ten_days_ago,
             "last_accessed_at": ten_days_ago, "access_count": 100},
            {"content": "unpopular", "memory_type": "fact", "confidence": 0.9,
             "created_at": ten_days_ago,
             "last_accessed_at": ten_days_ago, "access_count": 0},
        ]
        decayed = apply_confidence_decay(mems)
        assert decayed[0]["confidence"] > decayed[1]["confidence"], \
            "frequently accessed memories should resist decay better"

    def test_never_decays_below_min_confidence(self):
        from kernel.runtime.memory.confidence_decay import apply_confidence_decay
        mems = [
            {"content": "ancient", "memory_type": "conversation", "confidence": 0.9,
             "created_at": "2020-01-01T00:00:00Z",
             "last_accessed_at": "2020-01-01T00:00:00Z", "access_count": 0},
        ]
        decayed = apply_confidence_decay(mems)
        assert decayed[0]["confidence"] >= 0.1  # min_confidence

    def test_below_threshold_marked_for_archive(self):
        from kernel.runtime.memory.confidence_decay import apply_confidence_decay
        mems = [
            {"content": "ancient", "memory_type": "conversation", "confidence": 0.4,
             "created_at": "2020-01-01T00:00:00Z",
             "last_accessed_at": "2020-01-01T00:00:00Z", "access_count": 0},
        ]
        decayed = apply_confidence_decay(mems)
        assert decayed[0].get("should_archive") is True


# ═══════════════════════════════════════════════════════════════════════════════
# Section 4: Contradiction Detector (P1-2)
# ═══════════════════════════════════════════════════════════════════════════════


class TestContradictionDetector:
    """Contract: ContradictionDetector finds conflicting memories."""

    def test_detects_explicit_contradiction(self):
        from kernel.runtime.memory import ContradictionDetector
        detector = ContradictionDetector()
        existing = [{"content": "产品已上线", "memory_type": "fact", "confidence": 0.9, "memory_id": "e1"}]
        new = {"content": "产品还没有上线", "memory_type": "fact", "confidence": 0.7, "memory_id": "n1"}
        result = detector.detect(existing, new)
        assert len(result) >= 1

    def test_no_contradiction_on_same_fact(self):
        from kernel.runtime.memory import ContradictionDetector
        detector = ContradictionDetector()
        existing = [{"content": "2024年营收5000万", "memory_type": "fact", "confidence": 0.9, "memory_id": "e1"}]
        new = {"content": "2024年营收5000万", "memory_type": "fact", "confidence": 0.9, "memory_id": "n1"}
        result = detector.detect(existing, new)
        assert len(result) == 0

    def test_resolve_auto_resolves_moderate(self):
        from kernel.runtime.memory import ContradictionDetector
        detector = ContradictionDetector()
        contradictions = [
            type("MC", (), {
                "memory_a_id": "a", "memory_b_id": "b",
                "memory_a_content": "X", "memory_b_content": "Y",
                "contradiction_type": "factual", "severity": "moderate",
                "resolution": None, "auto_resolved": False,
            })()
        ]
        resolved = detector.resolve(contradictions)
        assert resolved[0].auto_resolved is True

    def test_critical_flags_for_human(self):
        from kernel.runtime.memory import ContradictionDetector
        detector = ContradictionDetector()
        contradictions = [
            type("MC", (), {
                "memory_a_id": "a", "memory_b_id": "b",
                "memory_a_content": "X", "memory_b_content": "Y",
                "contradiction_type": "factual", "severity": "critical",
                "resolution": None, "auto_resolved": False,
            })()
        ]
        resolved = detector.resolve(contradictions)
        assert resolved[0].auto_resolved is False  # Critical → flag human

    def test_numeric_contradiction_detected(self):
        from kernel.runtime.memory import ContradictionDetector
        detector = ContradictionDetector()
        existing = [{"content": "公司2024年营收5000万", "memory_type": "fact", "confidence": 0.9, "memory_id": "e1"}]
        new = {"content": "公司2024年营收3000万", "memory_type": "fact", "confidence": 0.7, "memory_id": "n1"}
        result = detector.detect(existing, new)
        assert len(result) >= 1, "Numeric contradiction should be detected"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 5: Fact Supersession (P1-2)
# ═══════════════════════════════════════════════════════════════════════════════


class TestFactSupersessionEngine:
    """Contract: FactSupersessionEngine tracks fact replacement chains."""

    def test_register_and_get_latest(self):
        from kernel.runtime.memory import FactSupersessionEngine
        engine = FactSupersessionEngine()
        engine.register_fact("revenue.2024", "m1")
        assert engine.get_latest("revenue.2024") == "m1"

    def test_supersede_replaces_active(self):
        from kernel.runtime.memory import FactSupersessionEngine
        engine = FactSupersessionEngine()
        engine.register_fact("revenue.2024", "m1")
        engine.supersede("revenue.2024", "m1", "m2", reason="corrected data")
        assert engine.get_latest("revenue.2024") == "m2"
        assert engine.is_superseded("m1") is True
        assert engine.is_superseded("m2") is False

    def test_lineage_chain(self):
        from kernel.runtime.memory import FactSupersessionEngine
        engine = FactSupersessionEngine()
        engine.register_fact("ceo", "m1")
        engine.supersede("ceo", "m1", "m2", reason="leadership change")
        engine.supersede("ceo", "m2", "m3", reason="latest update")
        lineage = engine.get_lineage("m1")
        assert "m2" in lineage
        assert "m3" in lineage
        assert len(lineage) == 3

    def test_get_history_returns_all_records(self):
        from kernel.runtime.memory import FactSupersessionEngine
        engine = FactSupersessionEngine()
        engine.register_fact("ceo", "m1")
        engine.supersede("ceo", "m1", "m2", reason="change")
        engine.supersede("ceo", "m2", "m3", reason="change again")
        history = engine.get_history("ceo")
        assert len(history) == 2

    def test_summary_counts(self):
        from kernel.runtime.memory import FactSupersessionEngine
        engine = FactSupersessionEngine()
        engine.register_fact("a", "m1")
        engine.register_fact("b", "m2")
        engine.supersede("a", "m1", "m3", "update")
        s = engine.summary()
        assert s["total_supersessions"] == 1
        assert s["active_fact_count"] == 2
        assert s["entity_count"] == 2


# ═══════════════════════════════════════════════════════════════════════════════
# Section 6: Context Compressor (P0-2)
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextCompressor:
    """Contract: ContextCompressor preserves key info while reducing size."""

    def test_short_text_passes_through(self):
        from kernel.runtime.context_runtime import ContextCompressor
        compressor = ContextCompressor(max_tokens=1000)
        result = compressor.compress("短文本")
        assert result.compression_ratio == 1.0
        assert result.quality_score == 1.0

    def test_long_text_compressed(self):
        from kernel.runtime.context_runtime import ContextCompressor
        compressor = ContextCompressor(max_tokens=20)
        long_text = "这是一段很长的文本。" * 50
        result = compressor.compress(long_text, "test")
        assert result.compression_ratio < 1.0
        assert len(result.content) < len(long_text)

    def test_empty_text(self):
        from kernel.runtime.context_runtime import ContextCompressor
        compressor = ContextCompressor()
        result = compressor.compress("")
        assert result.compressed_length == 0
        assert result.quality_score == 1.0

    def test_key_information_preserved(self):
        from kernel.runtime.context_runtime import ContextCompressor
        compressor = ContextCompressor(max_tokens=30)
        text = "无关内容。" * 5 + "关键数据：Q4销售额同比增长15%。" + "其他内容。" * 10
        result = compressor.compress(text)
        # Key info with numbers should be preserved
        assert "15%" in result.content or "关键数据" in result.content

    def test_source_label_in_result(self):
        from kernel.runtime.context_runtime import ContextCompressor
        compressor = ContextCompressor(max_tokens=5)
        result = compressor.compress("很长的文本内容。" * 20, "memory")
        assert result.original_length > result.compressed_length


# ═══════════════════════════════════════════════════════════════════════════════
# Section 7: Context Ranker (P0-2)
# ═══════════════════════════════════════════════════════════════════════════════


class TestContextRanker:
    """Contract: ContextRanker orders blocks by relevance to query."""

    def test_most_relevant_first(self):
        from kernel.runtime.context_runtime import ContextRanker, RankedContextBlock
        ranker = ContextRanker()
        blocks = [
            RankedContextBlock(content="Q4华东区销售数据分析报告", source_type="data_source"),
            RankedContextBlock(content="用户喜欢干净整洁的UI", source_type="preferences"),
        ]
        ranked = ranker.rank("Q4华东区销售", blocks)
        assert ranked[0].source_type == "data_source"
        assert ranked[0].relevance_score > ranked[1].relevance_score

    def test_empty_query_gives_equal_scores(self):
        from kernel.runtime.context_runtime import ContextRanker, RankedContextBlock
        ranker = ContextRanker()
        blocks = [
            RankedContextBlock(content="内容A", source_type="history"),
            RankedContextBlock(content="内容B", source_type="history"),
        ]
        ranked = ranker.rank("", blocks)
        # With no query tokens, all should have similar scores
        assert abs(ranked[0].relevance_score - ranked[1].relevance_score) < 0.01

    def test_empty_blocks_returns_empty(self):
        from kernel.runtime.context_runtime import ContextRanker
        ranker = ContextRanker()
        result = ranker.rank("query", [])
        assert result == []

    def test_ranks_are_set(self):
        from kernel.runtime.context_runtime import ContextRanker, RankedContextBlock
        ranker = ContextRanker()
        blocks = [
            RankedContextBlock(content="最相关的内容", source_type="data_source"),
            RankedContextBlock(content="一般内容", source_type="history"),
        ]
        ranked = ranker.rank("最相关", blocks)
        assert ranked[0].rank == 1
        assert ranked[1].rank == 2

    def test_top_k_truncation(self):
        from kernel.runtime.context_runtime import ContextRanker, RankedContextBlock
        ranker = ContextRanker()
        blocks = [
            RankedContextBlock(content=f"block{i}", source_type="history")
            for i in range(10)
        ]
        ranked = ranker.rank("block5", blocks, top_k=3)
        assert len(ranked) == 3


# ═══════════════════════════════════════════════════════════════════════════════
# Section 8: Decomposition Policy (P0-1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestDecompositionPolicy:
    """Contract: DecompositionPolicy selects the right execution strategy."""

    def test_single_goal_no_gaps_is_direct(self):
        from kernel.runtime.cognitive import (
            CognitiveGraph, GoalHierarchy, GoalNode, GoalType,
            DecompositionStrategy, build_decomposition_policy,
        )
        root = GoalNode(description="你好", goal_type=GoalType.PRIMARY)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)
        cg = CognitiveGraph(goal_hierarchy=h, complexity_score=0.1, domain="conversation")
        dp = build_decomposition_policy(cg)
        assert dp.strategy == DecompositionStrategy.DIRECT

    def test_comparison_goals_use_compare(self):
        from kernel.runtime.cognitive import (
            CognitiveGraph, GoalHierarchy, GoalNode, GoalType,
            DecompositionStrategy, build_decomposition_policy,
        )
        root = GoalNode(description="对比", goal_type=GoalType.COMPARISON)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)
        cg = CognitiveGraph(goal_hierarchy=h, complexity_score=0.5)
        dp = build_decomposition_policy(cg)
        assert dp.strategy == DecompositionStrategy.COMPARE

    def test_multi_goal_with_deps_is_sequential(self):
        from kernel.runtime.cognitive import (
            CognitiveGraph, GoalHierarchy, GoalNode, GoalType,
            DecompositionStrategy, build_decomposition_policy,
        )
        root = GoalNode(description="主任务", goal_type=GoalType.PRIMARY)
        child = GoalNode(description="子任务", goal_type=GoalType.DECOMPOSITION, depends_on=[root.goal_id])
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)
        h.add_goal(child)
        cg = CognitiveGraph(goal_hierarchy=h, complexity_score=0.4)
        dp = build_decomposition_policy(cg)
        assert dp.strategy == DecompositionStrategy.SEQUENTIAL

    def test_high_complexity_is_sequential(self):
        from kernel.runtime.cognitive import (
            CognitiveGraph, GoalHierarchy, GoalNode, GoalType,
            DecompositionStrategy, RiskAnalysis, build_decomposition_policy,
        )
        root = GoalNode(description="复杂任务", goal_type=GoalType.PRIMARY)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)
        cg = CognitiveGraph(
            goal_hierarchy=h, complexity_score=0.9,
            risk_analysis=RiskAnalysis(risk_level="high"),
        )
        dp = build_decomposition_policy(cg)
        assert dp.strategy == DecompositionStrategy.SEQUENTIAL


# ═══════════════════════════════════════════════════════════════════════════════
# Section 9: Evidence Ranking (P1-1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvidenceRanker:
    """Contract: EvidenceRanker scores evidence by multiple dimensions."""

    def test_rank_orders_by_composite_score(self):
        from kernel.runtime.evidence.ranking import EvidenceRanker
        from kernel.runtime.objects import Evidence, Provenance

        ranker = EvidenceRanker()
        evidence_list = [
            Evidence(content="Q4销售额增长15%", credibility_score=0.9,
                      provenance=Provenance(source="data", confidence=0.9), evidence_id="1"),
            Evidence(content="今天天气不错", credibility_score=0.5,
                      provenance=Provenance(source="web", confidence=0.5), evidence_id="2"),
        ]
        ranked = ranker.rank("Q4销售额", evidence_list)
        assert len(ranked) == 2
        assert ranked[0].evidence_id == "1"  # More relevant
        assert ranked[0].composite_score > ranked[1].composite_score

    def test_empty_list_returns_empty(self):
        from kernel.runtime.evidence.ranking import EvidenceRanker
        result = EvidenceRanker().rank("query", [])
        assert result == []

    def test_authority_scores(self):
        from kernel.runtime.evidence.ranking import EvidenceRanker
        assert EvidenceRanker._compute_authority("data") == 0.9
        assert EvidenceRanker._compute_authority("rag") == 0.7
        assert EvidenceRanker._compute_authority("web") == 0.5
        assert EvidenceRanker._compute_authority("unknown") == 0.5

    def test_custom_weights_affect_scoring(self):
        from kernel.runtime.evidence.ranking import EvidenceRanker
        from kernel.runtime.objects import Evidence, Provenance

        # Credibility-heavy ranker
        cred_ranker = EvidenceRanker(w_credibility=0.9, w_relevance=0.05, w_freshness=0.03, w_authority=0.02)
        ev1 = Evidence(content="不太相关但可信", credibility_score=0.95,
                        provenance=Provenance(source="data"), evidence_id="1")
        ev2 = Evidence(content="Q4相关但低可信", credibility_score=0.3,
                        provenance=Provenance(source="web"), evidence_id="2")

        ranked = cred_ranker.rank("Q4", [ev1, ev2])
        # With credibility-heavy weights, ev1 should be ranked higher
        assert ranked[0].evidence_id == "1"


# ═══════════════════════════════════════════════════════════════════════════════
# Section 10: Evidence Resolution (P1-1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestEvidenceResolution:
    """Contract: Evidence resolution detects and resolves conflicts."""

    def test_single_evidence_no_conflict(self):
        from kernel.runtime.evidence.resolution import resolve_evidence_conflicts, ResolutionStrategy
        from kernel.runtime.objects import Evidence, Provenance

        ev = [Evidence(content="data", credibility_score=0.9,
                       provenance=Provenance(source="data"), evidence_id="1")]
        result = resolve_evidence_conflicts(ev)
        assert len(result.conflicts) == 0
        assert len(result.resolved_evidence_ids) == 1

    def test_confident_winner_survives(self):
        from kernel.runtime.evidence.resolution import resolve_evidence_conflicts, ResolutionStrategy
        from kernel.runtime.evidence.ranking import EvidenceRanker
        from kernel.runtime.objects import Evidence, Provenance

        ev1 = Evidence(content="销售额增加20%", credibility_score=0.9,
                        provenance=Provenance(source="data"), evidence_id="1")
        ev2 = Evidence(content="销售额减少10%", credibility_score=0.4,
                        provenance=Provenance(source="web"), evidence_id="2")

        ranker = EvidenceRanker()
        ranked = ranker.rank("销售额", [ev1, ev2])
        result = resolve_evidence_conflicts(ranked, ResolutionStrategy.HIGHEST_CONFIDENCE)
        assert "1" in result.resolved_evidence_ids  # Higher confidence wins

    def test_empty_evidence_no_error(self):
        from kernel.runtime.evidence.resolution import resolve_evidence_conflicts
        result = resolve_evidence_conflicts([])
        assert result.resolved_evidence_ids == []


# ═══════════════════════════════════════════════════════════════════════════════
# Section 11: Cognitive Graph (P0-1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestCognitiveGraph:
    """Contract: CognitiveGraph correctly models goals and dependencies."""

    def test_goal_hierarchy_traversal(self):
        from kernel.runtime.cognitive import GoalNode, GoalHierarchy, GoalType

        root = GoalNode(description="root", goal_type=GoalType.PRIMARY)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)

        for i in range(3):
            child = GoalNode(description=f"child{i}", goal_type=GoalType.DECOMPOSITION,
                             parent_id=root.goal_id)
            h.add_goal(child)
            root.children.append(child.goal_id)

        assert len(h.get_leaf_goals()) == 3
        assert len(h.get_root_goals()) == 1
        assert len(h.all_goals) == 4

    def test_topological_order_respects_dependencies(self):
        from kernel.runtime.cognitive import GoalNode, GoalHierarchy, GoalType

        root = GoalNode(description="root", goal_type=GoalType.PRIMARY)
        child1 = GoalNode(description="child1", goal_type=GoalType.DECOMPOSITION)
        child2 = GoalNode(description="child2", goal_type=GoalType.DECOMPOSITION,
                          depends_on=[child1.goal_id])

        h = GoalHierarchy(root_goal=root)
        for g in [root, child1, child2]:
            h.add_goal(g)

        order = h.topological_order()
        # child1 must appear before child2
        idx1 = order.index(child1)
        idx2 = order.index(child2)
        assert idx1 < idx2

    def test_uncertainty_model_has_uncertainty(self):
        from kernel.runtime.cognitive import UncertaintyModel
        um = UncertaintyModel()
        assert um.has_uncertainty is False
        assert um.gap_count == 0

        um = UncertaintyModel(unknown_facts=["fact1"], ambiguous_terms=["term1"])
        assert um.has_uncertainty is True
        assert um.gap_count == 2

    def test_cognitive_graph_summary(self):
        from kernel.runtime.cognitive import CognitiveGraph, GoalNode, GoalHierarchy, GoalType
        root = GoalNode(description="test", goal_type=GoalType.PRIMARY)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)
        cg = CognitiveGraph(goal_hierarchy=h, domain="sales", complexity_score=0.5)
        s = cg.summary()
        assert s["domain"] == "sales"
        assert s["goal_count"] == 1
        assert s["complexity_score"] == 0.5


# ═══════════════════════════════════════════════════════════════════════════════
# Section 12: Strategy Builder + Execution Projection (P0-1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestStrategyAndProjection:
    """Contract: StrategyBuilder → ExecutionProjection pipeline works end-to-end."""

    def test_build_strategy_from_cognitive_plan(self):
        from kernel.runtime.cognitive import (
            CognitiveGraph, CognitivePlan, GoalHierarchy, GoalNode, GoalType,
            InformationGap, StrategyBuilder,
        )
        root = GoalNode(description="分析Q4销售", goal_type=GoalType.PRIMARY)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)

        cg = CognitiveGraph(
            goal_hierarchy=h,
            information_gaps=[
                InformationGap(description="Q4数据", suggested_source="data", priority="high"),
            ],
            complexity_score=0.5,
        )
        plan = CognitivePlan(cognitive_graph=cg)

        builder = StrategyBuilder()
        strategy = builder.build(plan)
        assert len(strategy.assignments) >= 1
        assert strategy.plan_id == plan.plan_id

    def test_projection_to_execution_plan(self):
        from kernel.runtime.cognitive import (
            CognitiveGraph, CognitivePlan, GoalHierarchy, GoalNode, GoalType,
            InformationGap, StrategyBuilder,
        )
        from kernel.runtime.cognitive.execution_projection import build_execution_projection

        root = GoalNode(description="查询数据", goal_type=GoalType.PRIMARY)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)

        cg = CognitiveGraph(
            goal_hierarchy=h,
            information_gaps=[
                InformationGap(description="数据", suggested_source="data", priority="high"),
            ],
        )
        plan = CognitivePlan(cognitive_graph=cg)
        strategy = StrategyBuilder().build(plan)
        proj = build_execution_projection(strategy)

        # Convert to execution plan
        ep = proj.to_execution_plan()
        assert len(ep.subtasks) > 0
        assert ep.risk_level == "low"

        # Convert to execution graph
        eg = proj.to_execution_graph()
        assert len(eg) == len(ep.subtasks)
        for node in eg:
            assert node.node_id != ""
            assert node.capability_name != ""

    def test_projection_summary(self):
        from kernel.runtime.cognitive import (
            CognitiveGraph, CognitivePlan, GoalHierarchy, GoalNode, GoalType,
            StrategyBuilder,
        )
        from kernel.runtime.cognitive.execution_projection import build_execution_projection

        root = GoalNode(description="简单查询", goal_type=GoalType.PRIMARY)
        h = GoalHierarchy(root_goal=root)
        h.add_goal(root)
        cg = CognitiveGraph(goal_hierarchy=h)
        plan = CognitivePlan(cognitive_graph=cg)
        strategy = StrategyBuilder().build(plan)
        proj = build_execution_projection(strategy)

        summary = proj.summary()
        assert "group_count" in summary
        assert "total_nodes" in summary
