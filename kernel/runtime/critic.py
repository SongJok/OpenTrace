"""
CriticEngineV2 — 使用 LLM（CHEAP_CRITIC 角色）的结构化质量评估。

评估维度：事实性、完整性、证据覆盖度、幻觉风险。
不触发重规划 — 仅提供质量评分和标注。
"""

from __future__ import annotations

from typing import Any

from infra.config.settings import settings
from infra.observability.logger import get_logger

logger = get_logger(__name__)


class CriticEngineV2:
    """LLM 驱动的质量批评（不触发重规划）。

    速度配置走启发式快速路径；质量配置走 LLM 评估。
    """

    def __init__(self) -> None:
        self._llm_enabled: bool | None = None

    @property
    def llm_enabled(self) -> bool:
        if self._llm_enabled is None:
            self._llm_enabled = bool(getattr(settings, "kernel_critic_v2_enabled", False))
        return self._llm_enabled

    async def evaluate(
        self,
        query: str,
        answer: str,
        evidence_count: int = 0,
        adaptive_profile: dict[str, Any] | None = None,
    ) -> CriticResult:
        """结构化评估回答质量。

        返回评分和标注；不修改回答。
        """
        profile_name = str((adaptive_profile or {}).get("name", "balanced") or "balanced")

        if not answer.strip():
            return CriticResult(
                passed=False,
                factuality=0.0,
                completeness=0.0,
                hallucination_risk=1.0,
                evidence_coverage=0.0,
                evidence_utilization=0.0,
                notes="empty_answer",
            )

        if self.llm_enabled and profile_name == "quality":
            return await self._llm_evaluate(query, answer, evidence_count)

        return self._heuristic_evaluate(query, answer, evidence_count, profile_name)

    async def _llm_evaluate(
        self,
        query: str,
        answer: str,
        evidence_count: int,
    ) -> CriticResult:
        """基于 LLM 的结构化评估。"""
        system_prompt = (
            "你是回答质量评估专家。请评估以下回答的质量，输出 JSON。\n"
            "评估维度：\n"
            "- factuality (0-1): 回答是否基于事实，有无编造\n"
            "- completeness (0-1): 回答是否完整覆盖了问题\n"
            "- evidence_coverage (0-1): 回答是否充分利用了提供的证据\n"
            "- hallucination_risk (0-1): 回答中存在幻觉的风险程度\n"
            "输出格式：{\"factuality\": 0.X, \"completeness\": 0.X, "
            "\"evidence_coverage\": 0.X, \"hallucination_risk\": 0.X, \"notes\": \"简短评价\"}"
        )

        user_prompt = (
            f"## 用户提问\n{query}\n\n"
            f"## 回答\n{answer[:2000]}\n\n"
            f"## 证据数量\n{evidence_count} 个来源\n\n"
            "请输出 JSON 评估结果。"
        )

        try:
            import json

            from model.model_gateway.gateway import LLMMessage, LLMRole, get_model_gateway

            gw = get_model_gateway()
            resp = await gw.complete(
                [
                    LLMMessage(role="system", content=system_prompt),
                    LLMMessage(role="user", content=user_prompt),
                ],
                role=LLMRole.CHEAP_CRITIC,
                temperature=0.0,
                max_tokens=300,
            )
            text = (resp.content or "").strip()
            # 去除 markdown 围栏
            text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()

            data = json.loads(text)
            return CriticResult(
                passed=data.get("factuality", 0.5) >= 0.6,
                factuality=float(data.get("factuality", 0.5)),
                completeness=float(data.get("completeness", 0.5)),
                evidence_coverage=float(data.get("evidence_coverage", 0.5)),
                hallucination_risk=float(data.get("hallucination_risk", 0.3)),
                evidence_utilization=float(data.get("evidence_coverage", 0.5)),
                notes=str(data.get("notes", "")),
                method="llm_critic_v2",
            )
        except Exception as exc:
            logger.warning("CriticV2 LLM call failed, falling back to heuristic", error=str(exc))
            return self._heuristic_evaluate(query, answer, evidence_count, "quality")

    def _heuristic_evaluate(
        self,
        query: str,
        answer: str,
        evidence_count: int,
        profile_name: str,
    ) -> CriticResult:
        """基于规则的质量评估。"""
        answer_len = len(answer)

        # 完整性启发式
        if answer_len < 20:
            completeness = 0.1
        elif answer_len < 100:
            completeness = 0.5
        else:
            completeness = 0.8

        # 证据覆盖度启发式
        if evidence_count == 0:
            evidence_coverage = 0.0
        elif evidence_count == 1:
            evidence_coverage = 0.6
        else:
            evidence_coverage = 0.8

        # 事实性启发式（保守估计）
        refusal_patterns = ["无法", "不能", "没有足够信息", "暂无法"]
        if any(p in answer for p in refusal_patterns):
            factuality = 0.9  # 诚实的拒答是事实性的
            completeness = 0.2
        else:
            factuality = 0.7  # 默认值，无法在无 LLM 时验证

        hallucination_risk = 0.3 if answer_len > 50 else 0.1

        passed = factuality >= 0.6 and completeness >= 0.3

        return CriticResult(
            passed=passed,
            factuality=factuality,
            completeness=completeness,
            evidence_coverage=evidence_coverage,
            hallucination_risk=hallucination_risk,
            evidence_utilization=evidence_coverage,
            notes="heuristic_critic_v2",
            method="heuristic_v2",
        )


class CriticResult:
    """结构化批评输出。"""

    def __init__(
        self,
        passed: bool = True,
        factuality: float = 0.7,
        completeness: float = 0.7,
        evidence_coverage: float = 0.5,
        hallucination_risk: float = 0.3,
        evidence_utilization: float = 0.5,
        notes: str = "",
        method: str = "",
    ) -> None:
        self.passed = passed
        self.factuality = factuality
        self.completeness = completeness
        self.evidence_coverage = evidence_coverage
        self.hallucination_risk = hallucination_risk
        self.evidence_utilization = evidence_utilization
        self.notes = notes
        self.method = method

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "factuality": self.factuality,
            "completeness": self.completeness,
            "evidence_coverage": self.evidence_coverage,
            "hallucination_risk": self.hallucination_risk,
            "evidence_utilization": self.evidence_utilization,
            "notes": self.notes,
            "method": self.method,
        }
