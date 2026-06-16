"""EvolutionEngine — 通过执行分析持续改进。

周期性分析执行历史的退化趋势、改进模式与策略有效性；
调整 reasoner 推荐权重，使后续决策偏向更高成功率的能力与策略。

按轮次驱动（非定时）— 每 N 轮执行一次分析。
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class Insight:
    """演化引擎发现的单条洞察。"""

    insight_type: str = ""  # "degradation"（退化）, "improvement"（改进）, "pattern"（模式）, "recommendation"（建议）
    capability_type: str | None = None
    severity: str = "info"  # "info"（信息）, "warning"（警告）, "critical"（严重）
    message: str = ""
    evidence: dict = field(default_factory=dict)
    timestamp: float = 0.0


class EvolutionEngine:
    """持续改进引擎 — 周期性分析执行历史以发现洞察并调整能力权重。

    模块级单例：`evolution_engine = EvolutionEngine(...)`

    Phase 2：分析按轮次驱动，由 on_turn_complete() 每 N 轮触发。无后台线程。
    """

    def __init__(
        self,
        execution_memory=None,
        strategy_memory=None,
        reasoner=None,
        analysis_interval_turns: int = 10,
    ) -> None:
        self._exec_memory = execution_memory
        self._strategy_memory = strategy_memory
        self._reasoner = reasoner
        self._interval = analysis_interval_turns
        self._turn_count = 0
        self._insights: deque[Insight] = deque(maxlen=100)
        # 跟踪已应用的 (capability_type, insight_type) 对
        # 以防止 adjust_weights() 中重复计数
        self._applied_adjustments: dict[str, float] = {}  # cap_type -> 上次应用时间戳

    def on_turn_complete(self) -> list[Insight]:
        """每轮完成后调用。递增计数器；若达到间隔则执行完整分析。返回新产生的洞察。"""
        self._turn_count += 1
        if self._turn_count % self._interval != 0:
            return []
        return self.analyze()

    def analyze(self) -> list[Insight]:
        """完整分析流程：
        1. 退化检测
        2. 改进检测
        3. 模式验证
        4. 策略有效性
        5. 应用权重调整

        返回本次分析产生的所有洞察。
        """
        new_insights: list[Insight] = []
        now = time.time()

        if self._exec_memory is None:
            return new_insights

        # 1. 退化检测 — 检查所有已知能力类型
        all_caps: set[str] = set()
        for key in self._exec_memory._by_capability:
            all_caps.add(key)

        for cap_type in all_caps:
            deg = self._exec_memory.degradation_check(cap_type, threshold=0.15)
            if deg is not None:
                severity = "critical" if deg["drop"] > 0.30 else "warning"
                insight = Insight(
                    insight_type="degradation",
                    capability_type=cap_type,
                    severity=severity,
                    message=(
                        f"{cap_type} 近期成功率从 {deg['overall_rate']:.0%} "
                        f"下降至 {deg['recent_rate']:.0%}（降幅 {deg['drop']:.0%}）"
                    ),
                    evidence=deg,
                    timestamp=now,
                )
                new_insights.append(insight)
                self._insights.append(insight)

        # 2. 改进检测
        for cap_type in all_caps:
            stats = self._exec_memory.get_stats(cap_type)
            overall = self._exec_memory.get_time_windowed_stats(cap_type, 3600)
            if overall.total >= 3 and overall.success_rate > 0.85:
                if overall.success_rate > stats.overall_success_rate + 0.10:
                    insight = Insight(
                        insight_type="improvement",
                        capability_type=cap_type,
                        severity="info",
                        message=(
                            f"{cap_type} 近期表现提升（{overall.success_rate:.0%} "
                            f"vs 整体 {stats.overall_success_rate:.0%}）"
                        ),
                        evidence={"recent_rate": overall.success_rate, "overall_rate": stats.overall_success_rate},
                        timestamp=now,
                    )
                    new_insights.append(insight)
                    self._insights.append(insight)

        # 3. 模式验证
        patterns = self._exec_memory.detect_patterns(min_samples=3)
        for p in patterns:
            if p.sample_count >= 5 and p.success_rate > 0.70:
                insight = Insight(
                    insight_type="pattern",
                    capability_type=None,
                    severity="info",
                    message=f"发现高成功率模式: {p.description}",
                    evidence={"pattern": p.pattern, "rate": p.success_rate, "samples": p.sample_count},
                    timestamp=now,
                )
                new_insights.append(insight)
                self._insights.append(insight)

        # 4. 应用权重调整
        self.adjust_weights()

        if new_insights:
            logger.info("Evolution analysis complete", insights=len(new_insights))

        return new_insights

    def adjust_weights(self) -> None:
        """根据检测到的模式对推理器应用权重调整。

        退化 → 负向调整（降低推荐权重）。
        改进 → 正向调整（提高推荐权重）。

        使用 _applied_adjustments 防止重复计数：每个
        (capability_type, insight_type) 对在每个周期内只应用一次。
        旧的调整随时间衰减至零。
        """
        if self._reasoner is None:
            return

        # 收集近期的退化/改进洞察（2 小时内）
        recent = [i for i in self._insights if i.timestamp > time.time() - 7200]

        for insight in recent:
            if insight.capability_type is None:
                continue

            cap = insight.capability_type
            # 跳过已在本周期应用过的能力+洞察类型组合
            key = f"{cap}:{insight.insight_type}"
            last_applied = self._applied_adjustments.get(key, 0.0)
            if last_applied >= insight.timestamp:
                continue  # 已处理过此洞察

            if insight.insight_type == "degradation":
                drop = insight.evidence.get("drop", 0.0)
                adj = max(-0.20, -drop * 0.5)
                self._reasoner.adjust_recommendations(
                    cap, adj, reason=insight.message,
                )
                self._applied_adjustments[key] = insight.timestamp
            elif insight.insight_type == "improvement":
                boost = min(0.15, insight.evidence.get("recent_rate", 0) * 0.1)
                self._reasoner.adjust_recommendations(
                    cap, boost, reason=insight.message,
                )
                self._applied_adjustments[key] = insight.timestamp

        # 清理旧调整（随时间衰减至零）
        for cap_type in list(self._reasoner._weight_adjustments.keys()):
            current = self._reasoner._weight_adjustments[cap_type]
            if abs(current) < 0.01:
                del self._reasoner._weight_adjustments[cap_type]
                # 同时清理已衰减能力的应用跟踪记录
                stale_keys = [
                    k for k in self._applied_adjustments
                    if k.startswith(f"{cap_type}:")
                ]
                for k in stale_keys:
                    del self._applied_adjustments[k]
            else:
                # 以 10% 的比率向零衰减
                self._reasoner._weight_adjustments[cap_type] = current * 0.9

    def recent_insights(
        self, n: int = 10, min_severity: str = "info"
    ) -> list[Insight]:
        """返回最近的洞察，可按严重程度过滤。"""
        severity_order = {"info": 0, "warning": 1, "critical": 2}
        threshold = severity_order.get(min_severity, 0)

        filtered = [
            i for i in self._insights
            if severity_order.get(i.severity, 0) >= threshold
        ]
        return list(filtered)[-n:]

    def get_degradation_alerts(self) -> list[Insight]:
        """仅返回警告/严重级别的退化洞察。"""
        return [
            i for i in self._insights
            if i.insight_type == "degradation" and i.severity in ("warning", "critical")
        ]

    @property
    def total_insights(self) -> int:
        return len(self._insights)


# 模块级单例 — 首次使用时延迟初始化
evolution_engine: EvolutionEngine | None = None


def _ensure_evolution_engine(
    execution_memory=None,
    strategy_memory=None,
    reasoner=None,
    interval: int = 10,
) -> EvolutionEngine:
    """延迟初始化演化引擎单例。"""
    global evolution_engine
    if evolution_engine is None:
        evolution_engine = EvolutionEngine(
            execution_memory=execution_memory,
            strategy_memory=strategy_memory,
            reasoner=reasoner,
            analysis_interval_turns=interval,
        )
    return evolution_engine
