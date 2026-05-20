"""
DataCriticAdapter — bridges CriticEngine into the DataAgent V2 pipeline.

Adapts data query results (content + confidence + metadata) into CriticInput,
runs CriticEngine, and returns enriched output with explainable confidence
breakdown, quality warnings, and improved_answer when applicable.
"""
from __future__ import annotations

from kernel.critic_engine.engine import CriticEngine
from kernel.critic_engine.models import CriticInput, CriticOutput


class DataCriticAdapter:
    """Adapt CriticEngine for data query result quality assessment.

    CriticEngine provides: decomposed confidence, refusal detection,
    specificity scoring, and answer substance evaluation. This adapter
    tailors it for structured data results (SQL + rows).
    """

    def __init__(self) -> None:
        self._engine = CriticEngine()

    def assess(
        self,
        query: str,
        content: str,
        confidence: float,
        fusion_context: str = "",
        rows: list[dict] | None = None,
        sql: str = "",
        error: str = "",
        verification_report: dict | None = None,
    ) -> CriticOutput:
        """Assess data query result quality through CriticEngine.

        Args:
            query: Original user query
            content: Formatted result content
            confidence: Pre-critic confidence score
            fusion_context: Additional context from fusion engine (if any)
            rows: Query result rows
            sql: Executed SQL
            error: Execution error if any
            verification_report: Verification agent output

        Returns:
            CriticOutput with need_fix, improved_answer, confidence_breakdown
        """
        # Build fusion context from data-specific information
        ctx_parts: list[str] = []
        if sql:
            ctx_parts.append(f"[data] SQL: {sql[:500]}")
        if rows:
            ctx_parts.append(f"[data] Rows returned: {len(rows)}")
            # Sample column names for context
            if rows and rows[0]:
                cols = list(rows[0].keys())[:20]
                ctx_parts.append(f"[data] Columns: {', '.join(cols)}")
        if verification_report:
            status = verification_report.get("status", "unknown")
            issues = verification_report.get("issues", [])
            ctx_parts.append(f"[data] Verification: {status} ({len(issues)} issues)")
        if error:
            ctx_parts.append(f"[data] Error: {error[:300]}")

        built_context = "\n".join(ctx_parts)

        critic_input = CriticInput(
            query=query,
            answer=content,
            fusion_context=built_context,
            fusion_confidence=confidence,
            adaptive_profile={"name": "data"},
        )

        return self._engine.run(critic_input)

    def enrich_result(
        self,
        content: str,
        confidence: float,
        query: str,
        rows: list[dict] | None = None,
        sql: str = "",
        error: str = "",
        verification_report: dict | None = None,
    ) -> dict:
        """Run critic assessment and return enriched result fields.

        Returns dict with keys suitable for merging into AgentResult:
        - content (possibly improved)
        - confidence (adjusted)
        - confidence_breakdown
        - confidence_explanation
        - critic_feedback
        """
        critic_out = self.assess(
            query=query,
            content=content,
            confidence=confidence,
            rows=rows,
            sql=sql,
            error=error,
            verification_report=verification_report,
        )

        enriched: dict = {
            "content": critic_out.improved_answer or content,
            "confidence": self._adjust_confidence(confidence, critic_out),
            "confidence_breakdown": critic_out.confidence_breakdown,
            "confidence_explanation": critic_out.confidence_explanation,
            "critic_feedback": critic_out.feedback,
            "critic_need_fix": critic_out.need_fix,
        }

        return enriched

    def _adjust_confidence(
        self, original: float, critic_out: CriticOutput
    ) -> float:
        """Blend original confidence with critic signals."""
        if not critic_out.confidence_breakdown:
            return original

        # Average of non-refusal and specificity as critic signal
        non_refusal = critic_out.confidence_breakdown.get("non_refusal", 0.5)
        specificity = critic_out.confidence_breakdown.get("specificity", 0.5)
        substance = critic_out.confidence_breakdown.get("answer_substance", 0.5)
        source_coverage = critic_out.confidence_breakdown.get("source_coverage", 0.5)

        critic_signal = (non_refusal + specificity + substance + source_coverage) / 4.0

        # Blend: 60% original, 40% critic
        blended = original * 0.6 + critic_signal * 0.4

        # If critic says need_fix, apply a penalty
        if critic_out.need_fix:
            blended -= 0.10

        return max(0.05, min(0.99, round(blended, 3)))
