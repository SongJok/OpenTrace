"""
证据状态机 — 强制执行 Evidence 对象的合法状态转换。

证据不能在状态之间任意跳转。状态机强制执行合法转换图：

  CREATED → VALIDATED → RANKED → MERGED → ARCHIVED
                  ↓         ↓         ↓
              INVALIDATED  SUPERSEDED  SUPERSEDED
"""

from __future__ import annotations

from enum import Enum


class EvidenceState(str, Enum):
    CREATED = "created"         # 由 Agent 新产生的
    VALIDATED = "validated"     # 可信度已检查，内容已验证
    RANKED = "ranked"           # 相对其他证据已评分
    MERGED = "merged"           # 已与其他证据融合（在 FusionEngine 中）
    SUPERSEDED = "superseded"   # 被更新/更好的证据取代
    ARCHIVED = "archived"       # 已持久化，不再活跃
    INVALIDATED = "invalidated" # 验证失败，不应使用


# 合法状态转换
_TRANSITIONS: dict[EvidenceState, set[EvidenceState]] = {
    EvidenceState.CREATED: {
        EvidenceState.VALIDATED,
        EvidenceState.INVALIDATED,
        EvidenceState.ARCHIVED,
    },
    EvidenceState.VALIDATED: {
        EvidenceState.RANKED,
        EvidenceState.SUPERSEDED,
        EvidenceState.INVALIDATED,
        EvidenceState.ARCHIVED,
    },
    EvidenceState.RANKED: {
        EvidenceState.MERGED,
        EvidenceState.SUPERSEDED,
        EvidenceState.ARCHIVED,
    },
    EvidenceState.MERGED: {
        EvidenceState.ARCHIVED,
        EvidenceState.SUPERSEDED,
    },
    EvidenceState.SUPERSEDED: {
        EvidenceState.ARCHIVED,
    },
    EvidenceState.ARCHIVED: set(),        # 终态
    EvidenceState.INVALIDATED: {
        EvidenceState.ARCHIVED,
    },
}


class InvalidTransitionError(ValueError):
    """当尝试非法状态转换时抛出。"""
    pass


class EvidenceStateMachine:
    """管理 Evidence 对象的状态转换。

    用法：
        sm = EvidenceStateMachine(EvidenceState.CREATED)
        sm.transition(EvidenceState.VALIDATED)  # 正常
        sm.transition(EvidenceState.MERGED)     # 抛出 InvalidTransitionError
    """

    def __init__(self, initial_state: EvidenceState = EvidenceState.CREATED) -> None:
        self._state = initial_state
        self._history: list[EvidenceState] = [initial_state]

    @property
    def state(self) -> EvidenceState:
        return self._state

    @property
    def history(self) -> list[EvidenceState]:
        return list(self._history)

    def can_transition(self, target: EvidenceState) -> bool:
        """检查转换是否合法，但不执行。"""
        return target in _TRANSITIONS.get(self._state, set())

    def transition(self, target: EvidenceState) -> EvidenceState:
        """尝试状态转换；如果非法则抛出 InvalidTransitionError。"""
        if not self.can_transition(target):
            raise InvalidTransitionError(
                f"Cannot transition from {self._state.value} to {target.value}. "
                f"Allowed: {[s.value for s in _TRANSITIONS.get(self._state, set())]}"
            )
        self._state = target
        self._history.append(target)
        return self._state

    def force_transition(self, target: EvidenceState) -> EvidenceState:
        """强制转换，跳过验证（谨慎使用）。"""
        self._state = target
        self._history.append(target)
        return self._state

    def is_terminal(self) -> bool:
        return len(_TRANSITIONS.get(self._state, set())) == 0

    def is_usable(self) -> bool:
        """此证据是否仍可用于融合。"""
        return self._state in {
            EvidenceState.CREATED,
            EvidenceState.VALIDATED,
            EvidenceState.RANKED,
            EvidenceState.MERGED,
        }


def state_transition(current: EvidenceState, target: EvidenceState) -> EvidenceState:
    """便捷函数：验证并返回新状态。"""
    sm = EvidenceStateMachine(current)
    return sm.transition(target)
