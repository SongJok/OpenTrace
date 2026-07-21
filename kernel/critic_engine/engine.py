"""批评引擎 — 多候选打分与可解释置信度。"""

from __future__ import annotations

import re

from .models import CandidateScore, CriticInput, CriticOutput


class CriticEngine:
    """增强批评：多候选评分与可解释置信度分解。"""

    def run(self, data: CriticInput) -> CriticOutput:
        answer = (data.answer or "").strip()
        profile_name = str((data.adaptive_profile or {}).get("name", "balanced") or "balanced")
        if not answer:
            return CriticOutput(
                need_fix=True,
                feedback="empty_answer",
                improved_answer="根据当前信息，暂无法生成有效回答。",
            )

        need_fix = False
        feedback = "ok"
        improved = answer

        # ── 置信度分解打分 ──────────────────────────
        confidence_breakdown = self._compute_confidence_breakdown(data, answer)

        # ── 多候选打分 ───────────────────────────────
        candidate_scores: list[CandidateScore] = []
        selected_candidate_index = -1
        if data.candidate_answers:
            candidate_scores = self._score_candidates(data)
            if candidate_scores:
                best = max(candidate_scores, key=lambda c: c.composite)
                selected_candidate_index = next(
                    i for i, c in enumerate(candidate_scores) if c is best
                )
                # 显著更优时选用最佳候选
                best_composite = best.composite
                primary = self._score_single(answer, "primary", data)
                if best_composite > primary.composite + 0.1:
                    improved = best.answer
                    need_fix = True
                    feedback = "selected_better_candidate"

        # ── 基于置信度的调整 ──────────────────────────
        fusion_conf = data.fusion_confidence
        if fusion_conf < 0.6:
            if profile_name == "speed":
                if "⚠️ 当前信息存在不确定性" not in improved:
                    improved = f"{improved}\n\n⚠️ 当前信息存在不确定性"
                    need_fix = True
                    feedback = "low_confidence_speed_warning"
            else:
                if "⚠️ 当前信息存在不确定性" not in improved:
                    improved = f"{improved}\n\n⚠️ 当前信息存在不确定性"
                    need_fix = True
                    feedback = "low_confidence_append_warning"

        if profile_name == "quality":
            if len((data.fusion_context or "").splitlines()) >= 2 and "参考" not in improved:
                improved = f"{improved}\n\n参考：已综合多源证据。"
                need_fix = True
                feedback = "quality_multi_source_enforce"

        if "根据现有信息无法回答" in improved and data.fusion_context.strip():
            improved = "基于已融合的数据源，整理如下：\n" + data.fusion_context[:2000]
            need_fix = True
            feedback = "replace_refusal_with_fusion"

        # 构建置信度说明
        explanation = self._build_confidence_explanation(confidence_breakdown, fusion_conf)

        return CriticOutput(
            need_fix=need_fix,
            feedback=feedback,
            improved_answer=improved,
            confidence_breakdown=confidence_breakdown,
            confidence_explanation=explanation,
            candidate_scores=candidate_scores,
            selected_candidate_index=selected_candidate_index,
        )

    # ── 置信度分解 ─────────────────────────────────────

    def _compute_confidence_breakdown(self, data: CriticInput, answer: str) -> dict[str, float]:
        """将置信度分解为可解释因子。"""
        breakdown: dict[str, float] = {}

        # 1. Source coverage: did we get results from enough agents?
        ctx = data.fusion_context or ""
        sources = len(re.findall(r"\[(data|web|rag|tool|skills|vision)\]", ctx))
        breakdown["source_coverage"] = min(1.0, sources / 3.0) if sources > 0 else 0.3

        # 2. Answer substance: does it actually contain information?
        stripped = answer.strip()
        if len(stripped) < 50:
            breakdown["answer_substance"] = 0.3
        elif len(stripped) < 200:
            breakdown["answer_substance"] = 0.6
        elif len(stripped) < 800:
            breakdown["answer_substance"] = 0.85
        else:
            breakdown["answer_substance"] = 0.95

        # 3. Refusal detection: does the answer refuse to answer?
        refusal_patterns = [
            r"无法回答", r"不能提供", r"抱歉.*无法", r"暂不",
            r"没有找到", r"未检索到", r"信息不足",
        ]
        refusal_count = sum(1 for p in refusal_patterns if re.search(p, answer))
        breakdown["non_refusal"] = max(0.0, 1.0 - refusal_count * 0.25)

        # 4. Specificity: does it contain concrete data (numbers, dates, names)?
        specificity = 0.5
        if re.search(r"\d+", answer):
            specificity += 0.15
        if re.search(r"\d{4}年|\d{2}月|\d{4}-\d{2}-\d{2}", answer):
            specificity += 0.15
        if re.search(r"[一-鿿]{2,}(?:公司|平台|系统|指标|数据|报告)", answer):
            specificity += 0.1
        if len(re.findall(r"\d+\.?\d*%?", answer)) >= 2:
            specificity += 0.1
        breakdown["specificity"] = min(1.0, specificity)

        return breakdown

    def _build_confidence_explanation(
        self, breakdown: dict[str, float], fusion_conf: float
    ) -> str:
        """Build a human-readable confidence explanation."""
        parts: list[str] = []
        sc = breakdown.get("source_coverage", 0)
        if sc < 0.5:
            parts.append("信息来源较少")
        elif sc >= 0.8:
            parts.append("多源信息覆盖良好")

        sub = breakdown.get("answer_substance", 0)
        if sub < 0.5:
            parts.append("回答内容偏短")
        elif sub >= 0.85:
            parts.append("回答内容丰富")

        nr = breakdown.get("non_refusal", 0)
        if nr < 0.7:
            parts.append("存在回避倾向")

        sp = breakdown.get("specificity", 0)
        if sp >= 0.8:
            parts.append("包含具体数据")
        elif sp < 0.5:
            parts.append("缺乏具体信息")

        if fusion_conf >= 0.8:
            parts.append("融合置信度高")
        elif fusion_conf < 0.5:
            parts.append("融合置信度偏低")

        return "；".join(parts) if parts else "综合评估通过"

    # ── Multi-candidate scoring ─────────────────────────────────────

    def _score_candidates(self, data: CriticInput) -> list[CandidateScore]:
        """Score multiple candidate answers."""
        scores: list[CandidateScore] = []
        for i, c in enumerate(data.candidate_answers):
            if not isinstance(c, dict):
                continue
            ans = str(c.get("answer") or c.get("content") or "")
            src = str(c.get("source") or c.get("agent_type") or f"candidate_{i}")
            if not ans.strip():
                continue
            scores.append(self._score_single(ans, src, data))
        return scores

    def _score_single(self, answer: str, source: str, data: CriticInput) -> CandidateScore:
        """Score a single answer across 4 dimensions."""
        query = data.query or ""
        ctx = data.fusion_context or ""

        # Factual consistency: grounded in fusion context?
        factual = 0.6
        ctx_words = set(ctx.lower().split())
        ans_words = set(answer.lower().split())
        if ctx_words and ans_words:
            overlap = len(ctx_words & ans_words) / max(1, len(ans_words))
            factual = min(0.95, 0.5 + overlap * 0.45)

        # Relevance: does it address the query?
        relevance = 0.5
        q_words = set(query.lower().split())
        if q_words and ans_words:
            q_overlap = len(q_words & ans_words) / max(1, len(q_words))
            relevance = min(0.95, 0.4 + q_overlap * 0.55)

        # Completeness: how thorough is the answer?
        stripped = answer.strip()
        length_score = min(1.0, len(stripped) / 600.0)
        has_numbers = 0.05 if re.search(r"\d+", stripped) else 0
        has_structure = 0.05 if (
            "\n" in stripped or "。" in stripped[100:]
        ) else 0
        completeness = min(0.95, length_score * 0.7 + has_numbers + has_structure + 0.2)

        # Coherence: logical flow
        coherence = 0.7
        if len(stripped) < 50:
            coherence = 0.5
        elif re.search(r"(?:首先|其次|最后|第一|第二|第三|此外|另外)", stripped):
            coherence = 0.9
        elif stripped.count("\n") >= 2:
            coherence = 0.85

        return CandidateScore(
            answer=stripped[:300],
            source=source,
            factual_consistency=round(factual, 3),
            relevance=round(relevance, 3),
            completeness=round(completeness, 3),
            coherence=round(coherence, 3),
        )
