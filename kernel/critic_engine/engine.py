from __future__ import annotations

from .models import CriticInput, CriticOutput


class CriticEngine:
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

        if data.fusion_confidence < 0.6:
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

        return CriticOutput(need_fix=need_fix, feedback=feedback, improved_answer=improved)
