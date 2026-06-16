"""
DataCriticAdapter — 将 CriticEngine 接入 DataAgent V2 流水线。

将数据查询结果（内容、置信度、元数据）适配为 CriticInput，运行 CriticEngine，
返回含可解释置信度分解、质量告警及改进答案（若适用）的增强输出。
"""
from __future__ import annotations

from kernel.critic_engine.engine import CriticEngine
from kernel.critic_engine.models import CriticInput, CriticOutput


class DataCriticAdapter:
    """将 CriticEngine 适配为数据查询结果质量评估器。

    CriticEngine 提供：分解置信度、拒绝检测、特异性评分和答案实质评估。
    本适配器针对结构化数据结果（SQL + 行数据）进行定制。
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
        """通过 CriticEngine 评估数据查询结果质量。

        Args:
            query: 原始用户查询
            content: 格式化的结果内容
            confidence: 评估前的置信度分数
            fusion_context: 来自融合引擎的额外上下文（如有）
            rows: 查询结果行
            sql: 已执行的 SQL
            error: 执行错误（如有）
            verification_report: 验证 Agent 输出

        Returns:
            包含 need_fix、improved_answer、confidence_breakdown 的 CriticOutput
        """
        # 从数据特定信息构建融合上下文
        ctx_parts: list[str] = []
        if sql:
            ctx_parts.append(f"[data] SQL: {sql[:500]}")
        if rows:
            ctx_parts.append(f"[data] Rows returned: {len(rows)}")
            # 采样列名作为上下文
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
        """运行 Critic 评估并返回增强结果字段。

        返回适合合并到 AgentResult 的字典：
        - content（可能已改进）
        - confidence（已调整）
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
        """将原始置信度与 Critic 信号混合。"""
        if not critic_out.confidence_breakdown:
            return original

        # 以非拒绝和特异性的平均值作为 Critic 信号
        non_refusal = critic_out.confidence_breakdown.get("non_refusal", 0.5)
        specificity = critic_out.confidence_breakdown.get("specificity", 0.5)
        substance = critic_out.confidence_breakdown.get("answer_substance", 0.5)
        source_coverage = critic_out.confidence_breakdown.get("source_coverage", 0.5)

        critic_signal = (non_refusal + specificity + substance + source_coverage) / 4.0

        # 混合比例：60% 原始，40% Critic
        blended = original * 0.6 + critic_signal * 0.4

        # 若 Critic 认为需要修复，施加惩罚
        if critic_out.need_fix:
            blended -= 0.10

        return max(0.05, min(0.99, round(blended, 3)))
