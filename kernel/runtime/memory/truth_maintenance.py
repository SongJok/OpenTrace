"""
真值维护系统 — 编排所有记忆完整性检查。

定期（或按需）运行：
1. 对所有记忆应用置信度衰减
2. 检测记忆间的矛盾
3. 解决矛盾（自动或标记待审核）
4. 取代过时事实
5. 归档低于置信度阈值的记忆
6. 生成 TMSReport 总结健康状况

这是防止长期记忆污染的记忆治理层。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .confidence_decay import ConfidenceDecayPolicy, apply_confidence_decay
from .contradiction_resolution import ContradictionDetector, MemoryContradiction, ResolutionAction
from .fact_supersession import FactSupersessionEngine

from infra.observability.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TMSReport:
    """真值维护系统运行报告。"""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # 衰减结果
    memories_checked: int = 0
    memories_decayed: int = 0
    memories_archived: int = 0

    # 矛盾结果
    contradictions_detected: int = 0
    contradictions_resolved: int = 0
    contradictions_flagged: int = 0

    # 取代结果
    supersessions_applied: int = 0

    # 健康状况
    overall_health: str = "healthy"  # healthy | degraded | critical
    recommendations: list[str] = field(default_factory=list)

    details: dict[str, Any] = field(default_factory=dict)


class TruthMaintenanceSystem:
    """认知运行时的中央真值维护系统。

    通过定期运行检查确保记忆随时间的完整性：
    置信度衰减、矛盾检测、事实取代和归档。
    """

    def __init__(
        self,
        memory_fabric: Any = None,
        supersession_engine: FactSupersessionEngine | None = None,
        contradiction_detector: ContradictionDetector | None = None,
    ) -> None:
        self._memory_fabric = memory_fabric
        self._supersession = supersession_engine or FactSupersessionEngine()
        self._contradiction_detector = contradiction_detector or ContradictionDetector()

    async def run(
        self,
        memories: list[dict[str, Any]] | None = None,
        decay_policy: ConfidenceDecayPolicy | None = None,
        auto_archive: bool = True,
    ) -> TMSReport:
        """执行完整的真值维护周期。

        Args:
            memories: 要检查的记忆。如果为 None，从 MemoryFabric 获取。
            decay_policy: 自定义衰减策略；如果为 None 使用默认值。
            auto_archive: 如果为 True，归档低于阈值的记忆。

        Returns:
            总结所有操作的 TMSReport。
        """
        report = TMSReport()
        if memories is None:
            memories = await self._fetch_memories()

        if not memories:
            report.overall_health = "healthy"
            return report

        report.memories_checked = len(memories)

        # ── 阶段 1：置信度衰减 ──
        decayed = apply_confidence_decay(memories, decay_policy)
        report.memories_decayed = sum(
            1 for m in decayed
            if m.get("confidence", 0.5) < m.get("original_confidence", m.get("confidence", 0.5)) + 0.001
        )

        # 归档低于阈值的记忆
        if auto_archive:
            to_archive = [m for m in decayed if m.get("should_archive")]
            report.memories_archived = len(to_archive)
            if to_archive:
                await self._archive_memories(to_archive)

        # ── 阶段 2：矛盾检测 ──
        all_contradictions: list[MemoryContradiction] = []
        for i, mem in enumerate(decayed):
            others = decayed[:i] + decayed[i + 1:]
            contradictions = self._contradiction_detector.detect(others, mem)
            all_contradictions.extend(contradictions)

        report.contradictions_detected = len(all_contradictions)

        if all_contradictions:
            resolved = self._contradiction_detector.resolve(all_contradictions)
            report.contradictions_resolved = sum(1 for c in resolved if c.auto_resolved)
            report.contradictions_flagged = sum(1 for c in resolved if not c.auto_resolved)

            if report.contradictions_flagged > 0:
                report.recommendations.append(
                    f"{report.contradictions_flagged} contradictions flagged for human review"
                )
                report.details["flagged_contradictions"] = [
                    {
                        "memory_a": c.memory_a_content[:100],
                        "memory_b": c.memory_b_content[:100],
                        "severity": c.severity,
                    }
                    for c in resolved if not c.auto_resolved
                ]

        # ── 阶段 3：取代检查 ──
        for mem in decayed:
            if mem.get("superseded_by"):
                report.supersessions_applied += 1

        # ── 阶段 4：健康评估 ──
        report.overall_health = self._assess_health(report, len(memories))
        if report.overall_health != "healthy":
            report.recommendations.append(
                f"Memory health is {report.overall_health} — "
                f"{report.memories_archived} archived, "
                f"{report.contradictions_flagged} flagged"
            )

        logger.info(
            "TMS cycle complete",
            health=report.overall_health,
            checked=report.memories_checked,
            archived=report.memories_archived,
            contradictions=report.contradictions_detected,
        )

        return report

    # ── 辅助方法 ─────────────────────────────────────────────────────────────

    async def _fetch_memories(self) -> list[dict[str, Any]]:
        """从 MemoryFabric 获取记忆以供 TMS 处理。"""
        if self._memory_fabric is None:
            from kernel.runtime.memory_fabric import memory_fabric
            self._memory_fabric = memory_fabric

        try:
            ctx, events = await self._memory_fabric.retrieve_context(
                query="",  # 空查询 = 所有记忆
                top_k=100,
            )
            return events if events else []
        except Exception as exc:
            logger.warning("TMS fetch memories failed", error=str(exc))
            return []

    async def _archive_memories(self, memories: list[dict[str, Any]]) -> None:
        """归档低于置信度阈值的记忆。"""
        if self._memory_fabric is None:
            return
        for mem in memories[:50]:  # 每周期最多 50 条
            try:
                mem_id = mem.get("memory_id", "")
                if mem_id:
                    # 记录归档事件
                    await self._memory_fabric.record_event(
                        event_type="memory_archived",
                        payload={
                            "memory_id": mem_id,
                            "reason": mem.get("archive_reason", ""),
                            "confidence": mem.get("confidence", 0),
                        },
                    )
            except Exception as exc:
                logger.debug("tms_archive_event_skipped", error=str(exc))

    @staticmethod
    def _assess_health(report: TMSReport, total: int) -> str:
        """评估整体记忆健康状况。"""
        if total == 0:
            return "healthy"

        archive_ratio = report.memories_archived / total
        contradiction_ratio = report.contradictions_flagged / max(total, 1)

        if archive_ratio > 0.5 or contradiction_ratio > 0.3:
            return "critical"
        if archive_ratio > 0.2 or contradiction_ratio > 0.1:
            return "degraded"
        return "healthy"


# ── 便捷函数 ────────────────────────────────────────────────────────────


async def run_truth_maintenance(
    memory_fabric: Any = None,
    auto_archive: bool = True,
) -> TMSReport:
    """运行完整的真值维护周期。便捷封装。"""
    tms = TruthMaintenanceSystem(memory_fabric=memory_fabric)
    return await tms.run(auto_archive=auto_archive)
