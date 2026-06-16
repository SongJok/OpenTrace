"""
证据生命周期 — 管理证据在状态机中的完整生命周期。

编排：创建 → 验证 → 排序 → 合并 → 取代 → 归档。
与 EvidenceBus（存储）、EvidenceRanker（评分）、EvidenceResolution（冲突）协同工作。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .state_machine import EvidenceState, EvidenceStateMachine, InvalidTransitionError

from infra.observability.logger import get_logger

logger = get_logger(__name__)


class EvidenceLifecycle:
    """管理结构化证据生命周期。

    用法：
        lc = EvidenceLifecycle()
        lc.create(content="...", provenance=Provenance(...), credibility=0.8)
        lc.validate("evidence_id")
        lc.rank("evidence_id", score=0.9)
        lc.supersede("old_id", "new_id", reason="newer data available")
        lc.archive("evidence_id")
    """

    def __init__(self, evidence_bus: Any = None) -> None:
        self._evidence_bus = evidence_bus
        self._states: dict[str, EvidenceStateMachine] = {}
        self._metadata: dict[str, dict[str, Any]] = {}

    async def _ensure_bus(self) -> Any:
        if self._evidence_bus is None:
            from kernel.runtime.evidence_bus import evidence_bus
            self._evidence_bus = evidence_bus
        return self._evidence_bus

    # ── 状态转换 ───────────────────────────────────────────────────────────

    def register(self, evidence_id: str, initial_state: EvidenceState = EvidenceState.CREATED) -> None:
        """在生命周期管理器中注册新的证据项。"""
        if evidence_id in self._states:
            logger.debug("Evidence already registered", evidence_id=evidence_id)
            return
        self._states[evidence_id] = EvidenceStateMachine(initial_state)
        self._metadata[evidence_id] = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "transitions": [],
        }

    def get_state(self, evidence_id: str) -> EvidenceState | None:
        sm = self._states.get(evidence_id)
        return sm.state if sm else None

    def transition(
        self, evidence_id: str, target: EvidenceState, force: bool = False
    ) -> EvidenceState:
        """将证据转换到新状态。"""
        if evidence_id not in self._states:
            self.register(evidence_id)

        sm = self._states[evidence_id]
        try:
            if force:
                new_state = sm.force_transition(target)
            else:
                new_state = sm.transition(target)
        except InvalidTransitionError as exc:
            logger.warning(
                "Invalid evidence transition",
                evidence_id=evidence_id,
                current=sm.state.value,
                target=target.value,
                error=str(exc),
            )
            raise

        self._metadata[evidence_id].setdefault("transitions", []).append({
            "from": sm.history[-2].value if len(sm.history) > 1 else "none",
            "to": new_state.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        logger.debug(
            "Evidence transition",
            evidence_id=evidence_id[:8],
            from_state=sm.history[-2].value if len(sm.history) > 1 else "none",
            to_state=new_state.value,
        )
        return new_state

    # ── 生命周期操作 ─────────────────────────────────────────────────────────

    def validate(self, evidence_id: str, credibility_score: float) -> EvidenceState:
        """验证证据：可信度 > 0 → VALIDATED，否则 INVALIDATED。"""
        if credibility_score > 0.0:
            return self.transition(evidence_id, EvidenceState.VALIDATED)
        return self.transition(evidence_id, EvidenceState.INVALIDATED)

    def rank(self, evidence_id: str) -> EvidenceState:
        """将证据标记为已排序（可进入融合）。"""
        return self.transition(evidence_id, EvidenceState.RANKED)

    def merge(self, evidence_id: str) -> EvidenceState:
        """将证据标记为已合并（已被 FusionEngine 消费）。"""
        return self.transition(evidence_id, EvidenceState.MERGED)

    def supersede(
        self,
        old_evidence_id: str,
        new_evidence_id: str,
        reason: str = "",
    ) -> tuple[EvidenceState, EvidenceState]:
        """用新证据取代旧证据。"""
        old_state = self.transition(old_evidence_id, EvidenceState.SUPERSEDED)
        self._metadata[old_evidence_id]["superseded_by"] = new_evidence_id
        self._metadata[old_evidence_id]["supersede_reason"] = reason
        if new_evidence_id in self._states:
            self._metadata[new_evidence_id]["supersedes"] = old_evidence_id
        return old_state, self.get_state(new_evidence_id) or EvidenceState.CREATED

    def archive(self, evidence_id: str) -> EvidenceState:
        """归档证据（终态）。"""
        return self.transition(evidence_id, EvidenceState.ARCHIVED)

    def invalidate(self, evidence_id: str, reason: str = "") -> EvidenceState:
        """使证据失效（验证未通过）。"""
        self._metadata[evidence_id]["invalidation_reason"] = reason
        return self.transition(evidence_id, EvidenceState.INVALIDATED)

    # ── 查询 ─────────────────────────────────────────────────────────────

    def get_usable_evidence_ids(self) -> list[str]:
        """返回仍可用于融合的证据 ID。"""
        return [
            eid for eid, sm in self._states.items()
            if sm.is_usable()
        ]

    def get_by_state(self, state: EvidenceState) -> list[str]:
        return [
            eid for eid, sm in self._states.items()
            if sm.state == state
        ]

    def get_history(self, evidence_id: str) -> list[dict[str, Any]]:
        return list(self._metadata.get(evidence_id, {}).get("transitions", []))

    def get_lifecycle_summary(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sm in self._states.values():
            key = sm.state.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    def reset(self) -> None:
        """清除所有生命周期状态（会话间重置）。"""
        self._states.clear()
        self._metadata.clear()
