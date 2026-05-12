"""SQL Ranker — rule-based scoring with semantic quality metrics for candidate SQL statements."""

from __future__ import annotations

import re

from kernel.data_cognition.types import CandidateSQL, SemanticContext, SemanticParseResult


class SQLRanker:
    # Scoring constants
    BASE_SCORE = 0.75

    # Semantic scoring weights (P0)
    WEIGHT_INTENT_COVERAGE = 0.30
    WEIGHT_COLUMN_ACCURACY = 0.25
    WEIGHT_GROUP_BY_CONSISTENCY = 0.15
    WEIGHT_TIME_CORRECTNESS = 0.15
    WEIGHT_FORM_ELEGANCE = 0.15  # legacy form-based scoring

    # Legacy bonuses/penalties
    BONUS_HISTORICAL_SUCCESS = 0.15
    BONUS_DISTINCT = 0.05
    BONUS_LIMIT = 0.08
    PENALTY_SELECT_STAR = 0.15
    PENALTY_EXCESSIVE_TOKENS = 0.10
    PENALTY_DEEP_SUBQUERY = 0.08
    PENALTY_JOIN_DEPTH_EXCESS = 0.08
    PENALTY_EMPTY_RESULT_NO_SEMANTICS = 0.15
    JOIN_DEPTH_THRESHOLD = 2

    def rank(
        self,
        candidates: list[CandidateSQL],
        semantic_ctx: SemanticContext | None = None,
        schema_hint: str = "",
        unmapped_terms: list[str] | None = None,
        result_rows: int | None = None,
        has_empty_semantics: bool = False,
        parse_result: SemanticParseResult | None = None,
    ) -> list[CandidateSQL]:
        """
        Rank candidate SQL statements with semantic-aware scoring.

        Args:
            candidates: List of CandidateSQL to rank
            semantic_ctx: Legacy semantic context for bonus scoring
            schema_hint: Schema hint string
            unmapped_terms: Filter terms that couldn't be mapped
            result_rows: Number of result rows
            has_empty_semantics: Whether empty result is semantically expected
            parse_result: Structured parse result for semantic scoring
        """
        if not candidates:
            return []
        for c in candidates:
            c.score = self._score(
                c,
                semantic_ctx,
                schema_hint,
                unmapped_terms,
                result_rows,
                has_empty_semantics,
                parse_result,
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
        parse_result: SemanticParseResult | None = None,
    ) -> float:
        score = self.BASE_SCORE
        sql = candidate.sql.lower()

        # === SEMANTIC SCORING (primary) ===
        if parse_result:
            semantic_score = self._semantic_score(sql, parse_result)
            # Blend with base score: semantic score is the primary signal
            score = (
                score * (1 - self.WEIGHT_INTENT_COVERAGE - self.WEIGHT_COLUMN_ACCURACY)
                + semantic_score
            )

        # === LEGACY FORM-BASED SCORING (secondary) ===

        # SQL length
        token_count = len(sql.split())
        if token_count <= 10:
            score += 0.05
        elif token_count <= 20:
            score += 0.03
        elif token_count > 100:
            score -= self.PENALTY_EXCESSIVE_TOKENS

        # JOIN complexity
        join_count = sql.count(" join ")
        if join_count == 0:
            score += 0.05
        elif join_count <= 2:
            score += 0.03

        # Subquery depth
        depth = sql.count("select") - 1
        if depth == 0:
            score += 0.03
        elif depth > 2:
            score -= self.PENALTY_DEEP_SUBQUERY

        # Legacy semantic context bonuses
        if ctx:
            for dim_name, info in ctx.dimension_mappings.items():
                for cond in info.get("conditions", []):
                    if cond.lower() in sql:
                        score += 0.08
            for tm in ctx.time_macros:
                if tm.get("column") and tm["column"].lower() in sql:
                    score += 0.05

        if ctx and ctx.time_macros:
            has_time_filter = any(
                kw in sql
                for kw in (
                    "interval",
                    "date_sub",
                    "dateadd",
                    "now()",
                    "current_date",
                    "current_timestamp",
                )
            )
            if not has_time_filter:
                score -= 0.08

        # DISTINCT bonus
        if "distinct" in sql:
            score += self.BONUS_DISTINCT

        # LIMIT bonus
        if "limit" in sql:
            score += self.BONUS_LIMIT

        # Historical success rate
        features = candidate.features
        if features.get("historical_success_rate", 0) > 0.8:
            score += self.BONUS_HISTORICAL_SUCCESS
        elif features.get("historical_success_rate", 0) < 0.3:
            score -= 0.05

        # Penalties
        if unmapped_terms:
            score -= len(unmapped_terms) * 0.08

        if join_count > self.JOIN_DEPTH_THRESHOLD:
            excess = join_count - self.JOIN_DEPTH_THRESHOLD
            score -= excess * self.PENALTY_JOIN_DEPTH_EXCESS

        if result_rows is not None and result_rows == 0 and not has_empty_semantics:
            score -= self.PENALTY_EMPTY_RESULT_NO_SEMANTICS

        if re.search(r"select\s+\*\s+from", sql):
            score -= self.PENALTY_SELECT_STAR

        # Clamp to [0, 1]
        return round(max(0.0, min(1.0, score)), 3)

    def _semantic_score(self, sql: str, parse_result: SemanticParseResult) -> float:
        """Compute semantic quality score based on how well SQL matches user intent."""
        lowered = sql.lower()
        components: list[float] = []

        # 1. Intent coverage: are all metrics/entities present?
        if parse_result.metrics or parse_result.entities:
            coverage = 0.0
            total = len(parse_result.metrics) + len(parse_result.entities)
            for m in parse_result.metrics:
                if m.mapped_column and m.mapped_column.lower() in lowered:
                    coverage += 1.0
            for e in parse_result.entities:
                if e.mapped_table and e.mapped_table.lower() in lowered:
                    coverage += 1.0
            components.append(coverage / total if total > 0 else 1.0)

        # 2. Column accuracy: filter values present in SQL
        if parse_result.filters:
            filter_coverage = 0.0
            for f in parse_result.filters:
                if f.value and f.value.lower() in lowered:
                    filter_coverage += 1.0
            components.append(filter_coverage / len(parse_result.filters))

        # 3. GROUP BY consistency
        if parse_result.group_by:
            has_gb = "group by" in lowered
            all_present = all(g.lower().strip() in lowered for g in parse_result.group_by)
            gb_score = 1.0 if (has_gb and all_present) else (0.5 if has_gb else 0.0)
            components.append(gb_score)

        # 4. Time filter correctness
        if parse_result.time_window and parse_result.time_window.get("days"):
            has_time = any(
                kw in lowered
                for kw in (
                    "date_sub",
                    "dateadd",
                    "interval",
                    "now()",
                    "current_date",
                    "current_timestamp",
                )
            )
            col_hint = parse_result.time_window.get("column_hint", "")
            if has_time:
                time_score = 1.0 if (not col_hint or col_hint.lower() in lowered) else 0.6
            else:
                time_score = 0.0
            components.append(time_score)

        # 5. ORDER BY match
        if parse_result.order_by:
            has_ob = "order by" in lowered
            components.append(1.0 if has_ob else 0.3)

        if not components:
            return 0.5  # No semantic info to check against

        return sum(components) / len(components)
