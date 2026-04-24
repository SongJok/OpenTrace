"""SQL Ranker — rule-based scoring with penalty factors for candidate SQL statements."""

from __future__ import annotations

import re

from kernel.data_cognition.types import CandidateSQL, SemanticContext


class SQLRanker:
    # Scoring constants - use moderate values to preserve relative differences
    BASE_SCORE = 0.75
    # Penalties
    PENALTY_UNMAPPED_FILTER = 0.2
    PENALTY_JOIN_DEPTH_EXCESS = 0.15  # per layer beyond threshold
    PENALTY_EMPTY_RESULT_NO_SEMANTICS = 0.3
    JOIN_DEPTH_THRESHOLD = 2
    # Bonuses (moderate to avoid saturation)
    BONUS_HISTORICAL_SUCCESS = 0.25
    BONUS_TIME_FILTER_MATCH = 0.25
    BONUS_DISTINCT = 0.1
    BONUS_LIMIT = 0.15
    BONUS_SHORT_QUERY = 0.15
    BONUS_MODERATE_QUERY = 0.05
    # Penalties for risky patterns
    PENALTY_SELECT_STAR = 0.25
    PENALTY_EXCESSIVE_TOKENS = 0.25
    PENALTY_DEEP_SUBQUERY = 0.15
    PENALTY_MISSING_TIME_FILTER = 0.15

    def rank(
        self,
        candidates: list[CandidateSQL],
        semantic_ctx: SemanticContext | None = None,
        schema_hint: str = "",
        unmapped_terms: list[str] | None = None,
        result_rows: int | None = None,
        has_empty_semantics: bool = False,
    ) -> list[CandidateSQL]:
        """
        Rank candidate SQL statements with refined scoring.
        
        Args:
            candidates: List of CandidateSQL to rank
            semantic_ctx: Semantic context for bonus scoring
            schema_hint: Schema hint string
            unmapped_terms: List of filter terms that couldn't be mapped (for penalty)
            result_rows: Number of result rows (for empty result penalty)
            has_empty_semantics: Whether empty result is semantically expected
        """
        if not candidates:
            return []
        for c in candidates:
            c.score = self._score(
                c, semantic_ctx, schema_hint,
                unmapped_terms, result_rows, has_empty_semantics
            )
        return sorted(candidates, key=lambda c: c.score, reverse=True)

    def _score(
        self,
        candidate: CandidateSQL,
        ctx: SemanticContext | None,
        schema_hint: str,
        unmapped_terms: list[str] | None = None,
        result_rows: int | None = None,
        has_empty_semantics: bool = False,
    ) -> float:
        score = self.BASE_SCORE
        sql = candidate.sql.lower()

        # === BONUSES ===
        
        # 1. SQL length: shorter is generally better (within reason)
        token_count = len(sql.split())
        if token_count <= 10:
            score += self.BONUS_SHORT_QUERY
        elif token_count <= 20:
            score += self.BONUS_MODERATE_QUERY
        elif token_count > 100:
            score -= self.PENALTY_EXCESSIVE_TOKENS

        # 2. JOIN complexity: moderate JOINs are OK, excessive is risky
        join_count = sql.count(" join ")
        if join_count == 0:
            score += 0.1
        elif join_count <= 2:
            score += 0.05

        # 3. Subquery depth
        depth = sql.count("select") - 1
        if depth == 0:
            score += 0.05
        elif depth > 2:
            score -= self.PENALTY_DEEP_SUBQUERY

        # 4. Semantic match bonus from context
        if ctx:
            for dim_name, info in ctx.dimension_mappings.items():
                for cond in info.get("conditions", []):
                    if cond.lower() in sql:
                        score += 0.15  # Moderate bonus for semantic match
            for tm in ctx.time_macros:
                if tm.get("column") and tm["column"].lower() in sql:
                    score += 0.1

        # 5. Required time filter check
        if ctx and ctx.time_macros:
            has_time_filter = any(
                kw in sql for kw in ("interval", "date_sub", "dateadd", "now()", "current_date", "current_timestamp")
            )
            if has_time_filter:
                score += self.BONUS_TIME_FILTER_MATCH
            else:
                score -= self.PENALTY_MISSING_TIME_FILTER

        # 6. Uses DISTINCT (good for count queries)
        if "distinct" in sql:
            score += self.BONUS_DISTINCT

        # 7. Has LIMIT (safety)
        if "limit" in sql:
            score += self.BONUS_LIMIT

        # 8. Historical success rate from features
        features = candidate.features
        if features.get("historical_success_rate", 0) > 0.8:
            score += self.BONUS_HISTORICAL_SUCCESS
        elif features.get("historical_success_rate", 0) < 0.3:
            score -= 0.1

        # === PENALTIES ===

        # 9. Unmapped filter terms penalty
        if unmapped_terms:
            score -= len(unmapped_terms) * self.PENALTY_UNMAPPED_FILTER

        # 10. Excessive JOIN depth penalty (beyond threshold)
        if join_count > self.JOIN_DEPTH_THRESHOLD:
            excess = join_count - self.JOIN_DEPTH_THRESHOLD
            score -= excess * self.PENALTY_JOIN_DEPTH_EXCESS

        # 11. Empty result without semantic justification
        if result_rows is not None and result_rows == 0 and not has_empty_semantics:
            score -= self.PENALTY_EMPTY_RESULT_NO_SEMANTICS

        # 12. SELECT * penalty (imprecise queries)
        if re.search(r"select\s+\*\s+from", sql):
            score -= self.PENALTY_SELECT_STAR

        # Return score without hard clamping - relative ordering is what matters
        return round(score, 3)
