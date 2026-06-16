"""
EvidenceBus — 运行时中 Evidence 对象流动的发布/订阅通道。

Agent 结果作为 Evidence 通过总线发布。融合和批评引擎订阅以收集
所有证据用于综合与评估。

现包含完整生命周期管理：每个 Evidence 项流经
CREATED → VALIDATED → RANKED → MERGED → (SUPERSEDED | ARCHIVED)。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agents.base import AgentResult

from infra.observability.logger import get_logger
from kernel.runtime.objects import Evidence, Provenance

logger = get_logger(__name__)


class EvidenceBus:
    """进程内证据发布/订阅总线，含生命周期管理。

    Agent 在执行后发布 Evidence。融合/批评引擎收集。
    生命周期管理器强制执行有效的状态转换。
    """

    def __init__(self) -> None:
        self._evidence: list[Evidence] = []
        self._published_ids: set[str] = set()
        self._subscribers: list[Any] = []
        self._lock = asyncio.Lock()
        self._lifecycle: Any = None  # EvidenceLifecycle（延迟加载）

    # ── 生命周期 ────────────────────────────────────────────────────────────

    async def _ensure_lifecycle(self) -> Any:
        if self._lifecycle is None:
            from kernel.runtime.evidence.lifecycle import EvidenceLifecycle
            self._lifecycle = EvidenceLifecycle(evidence_bus=self)
        return self._lifecycle

    # ── 发布 ─────────────────────────────────────────────────────────────

    async def publish(self, evidence: Evidence) -> bool:
        """发布单个 Evidence 项并注册到生命周期。重复 evidence_id 时跳过（幂等）。"""
        eid = evidence.evidence_id
        async with self._lock:
            if eid in self._published_ids:
                logger.debug("Evidence publish skipped (duplicate)", evidence_id=eid[:8])
                return False
            self._published_ids.add(eid)
            self._evidence.append(evidence)
        lc = await self._ensure_lifecycle()
        lc.register(eid)
        logger.debug("Evidence published", evidence_id=eid[:8], state=evidence.state)
        return True

    async def collect(self) -> list[Evidence]:
        """返回目前收集到的所有证据（非破坏性读取）。"""
        async with self._lock:
            return list(self._evidence)

    async def drain(self) -> list[Evidence]:
        """返回所有证据并清空总线。"""
        async with self._lock:
            items = self._evidence[:]
            self._evidence.clear()
            self._published_ids.clear()
            return items

    async def publish_results(self, results: list[AgentResult]) -> list[Evidence]:
        """将 AgentResults 转换为 Evidence，发布并注册到生命周期。

        返回创建的 Evidence 对象。
        """
        try:
            from infra.config.settings import settings

            if bool(getattr(settings, "kernel_agent_runtime_v3_enabled", True)):
                from kernel.agent_runtime.contribution import contribution_from_agent_result

                goal_id = ""
                trace_id = ""
                unified_all = []
                for result in results:
                    md = getattr(result, "metadata", None) or {}
                    goal_id = str(md.get("goal_id") or goal_id or "")
                    trace_id = str(md.get("trace_id") or md.get("request_id") or trace_id or "")
                    contrib = contribution_from_agent_result(
                        result,
                        goal_id=goal_id,
                        trace_id=trace_id,
                    )
                    unified_all.extend(contrib.unified_evidence)
                if unified_all:
                    published: list[Evidence] = []
                    lc = await self._ensure_lifecycle()
                    for u in unified_all:
                        ev = u.to_runtime_evidence()
                        if await self.publish(ev):
                            try:
                                if ev.credibility_score > 0:
                                    lc.validate(ev.evidence_id, ev.credibility_score)
                                    ev.state = "validated"
                                else:
                                    lc.invalidate(ev.evidence_id, reason="low_credibility")
                                    ev.state = "invalidated"
                            except Exception as exc:
                                logger.debug("evidence_bus_lc_validate_skipped", error=str(exc))
                            published.append(ev)
                    logger.info(
                        "EvidenceBus published unified results",
                        total=len(unified_all),
                        new=len(published),
                    )
                    return published
        except Exception as exc:
            logger.debug("Unified evidence publish path skipped", error=str(exc))

        lc = await self._ensure_lifecycle()
        evidence_list: list[Evidence] = []

        for result in results:
            if result.status == "success":
                ev = Evidence(
                    content=result.content,
                    content_type="text",
                    provenance=Provenance(
                        source=result.agent_type,
                        source_type="agent",
                        confidence=result.confidence,
                    ),
                    credibility_score=result.confidence,
                    relevance_score=0.5,
                    citations=[],
                    state="created",
                    metadata={
                        "task_id": result.task_id,
                        "agent_type": result.agent_type,
                        **result.metadata,
                    },
                )
            else:
                ev = Evidence(
                    content=result.error or result.content,
                    content_type="text",
                    provenance=Provenance(
                        source=result.agent_type,
                        source_type="agent",
                        confidence=0.0,
                    ),
                    credibility_score=0.0,
                    relevance_score=0.0,
                    citations=[],
                    state="created",
                    metadata={
                        "task_id": result.task_id,
                        "agent_type": result.agent_type,
                        "status": result.status,
                        **result.metadata,
                    },
                )

            # 注册并验证
            lc.register(ev.evidence_id)
            if result.status == "success":
                try:
                    lc.validate(ev.evidence_id, ev.credibility_score)
                    ev.state = "validated"
                except Exception as exc:
                    logger.debug("evidence_bus_validate_skipped", error=str(exc))
            else:
                try:
                    lc.invalidate(ev.evidence_id, reason=result.error or "agent failed")
                    ev.state = "invalidated"
                except Exception as exc:
                    logger.debug("evidence_bus_invalidate_skipped", error=str(exc))

            evidence_list.append(ev)

        for ev in evidence_list:
            await self.publish(ev)

        logger.info(
            "EvidenceBus published results",
            total=len(evidence_list),
            validated=sum(1 for e in evidence_list if e.state == "validated"),
        )

        return evidence_list

    # ── 排序 ──────────────────────────────────────────────────────────────

    async def rank_evidence(self, query: str) -> list[Any]:
        """按相关性 + 可信度 + 新鲜度排序所有可用证据。"""
        from kernel.runtime.evidence.ranking import EvidenceRanker

        async with self._lock:
            usable = [e for e in self._evidence if getattr(e, "state", "") in ("validated", "created")]
            if not usable:
                usable = [e for e in self._evidence]

        ranker = EvidenceRanker()
        ranked = ranker.rank(query, usable)

        # 更新证据状态
        lc = await self._ensure_lifecycle()
        for r in ranked:
            try:
                if lc.get_state(r.evidence_id) == "validated":
                    lc.rank(r.evidence_id)
            except Exception as exc:
                logger.debug("evidence_bus_rank_skipped", error=str(exc))

        return ranked

    # ── 冲突解决 ────────────────────────────────────────────────────────────

    async def resolve(self, query: str) -> list[str]:
        """排序证据并解决冲突，返回已解决的证据 ID。"""
        ranked = await self.rank_evidence(query)

        from kernel.runtime.evidence.resolution import (
            ResolutionStrategy,
            resolve_evidence_conflicts,
        )

        resolution = resolve_evidence_conflicts(ranked, strategy=ResolutionStrategy.HIGHEST_CONFIDENCE)

        if resolution.unresolved_count > 0:
            logger.warning(
                "EvidenceBus unresolved conflicts",
                unresolved=resolution.unresolved_count,
                flagged=resolution.flagged_for_human,
            )

        # 将已解决的证据标记为 ranked
        lc = await self._ensure_lifecycle()
        for eid in resolution.resolved_evidence_ids:
            try:
                state = lc.get_state(eid)
                if state and state.value == "validated":
                    lc.rank(eid)
            except Exception as exc:
                logger.debug("evidence_bus_resolve_rank_skipped", error=str(exc))

        return resolution.resolved_evidence_ids

    # ── 取代 ─────────────────────────────────────────────────────────────

    async def supersede(self, old_evidence_id: str, new_evidence_id: str, reason: str = "") -> None:
        """将旧证据标记为被新证据取代。"""
        lc = await self._ensure_lifecycle()
        lc.supersede(old_evidence_id, new_evidence_id, reason)

        # 更新总线中的 Evidence 对象
        async with self._lock:
            for ev in self._evidence:
                if ev.evidence_id == old_evidence_id:
                    ev.state = "superseded"
                    ev.superseded_by = new_evidence_id
                elif ev.evidence_id == new_evidence_id:
                    ev.supersedes = old_evidence_id
                    ev.version = getattr(ev, "version", 1) + 1

    # ── 归档 ─────────────────────────────────────────────────────────────

    async def archive_turn(self) -> None:
        """在回合结束时归档所有活跃证据。"""
        lc = await self._ensure_lifecycle()
        async with self._lock:
            for ev in self._evidence:
                if getattr(ev, "state", "") not in ("archived", "superseded"):
                    try:
                        lc.archive(ev.evidence_id)
                        ev.state = "archived"
                    except Exception as exc:
                        logger.debug("evidence_bus_archive_skipped", error=str(exc))

    # ── 查询 ─────────────────────────────────────────────────────────────

    async def get_by_id(self, evidence_id: str) -> Evidence | None:
        async with self._lock:
            for ev in self._evidence:
                if ev.evidence_id == evidence_id:
                    return ev
        return None

    async def get_usable(self) -> list[Evidence]:
        """获取仍可用于融合的证据。"""
        lc = await self._ensure_lifecycle()
        usable_ids = set(lc.get_usable_evidence_ids())
        async with self._lock:
            return [e for e in self._evidence if e.evidence_id in usable_ids]

    @property
    def count(self) -> int:
        return len(self._evidence)

    async def lifecycle_summary(self) -> dict[str, int]:
        lc = await self._ensure_lifecycle()
        return lc.get_lifecycle_summary()

    async def reset(self) -> None:
        """清空所有收集的证据和生命周期状态。"""
        async with self._lock:
            self._evidence.clear()
        lc = await self._ensure_lifecycle()
        lc.reset()


# 模块级单例
evidence_bus = EvidenceBus()
