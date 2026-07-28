"""异常降级策略的显式分类。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class FailureMode(str, Enum):
    FAIL_CLOSED = "fail_closed"
    FAIL_OPEN = "fail_open"
    RETRY = "retry"
    RECONCILE = "reconcile"


@dataclass(frozen=True)
class FailurePolicy:
    mode: FailureMode
    reason: str
    metric: str
    retry_limit: int = 0

    def validate(self) -> None:
        if not self.reason.strip() or not self.metric.strip():
            raise ValueError("降级策略必须声明 reason 和 metric")
        if self.mode is FailureMode.RETRY and self.retry_limit <= 0:
            raise ValueError("retry 策略必须有正数 retry_limit")
        if self.mode is FailureMode.RECONCILE and self.retry_limit:
            raise ValueError("reconcile 禁止自动重试")


def policy_metadata(policy: FailurePolicy, **context: Any) -> dict[str, Any]:
    policy.validate()
    return {
        "failure_mode": policy.mode.value,
        "failure_reason": policy.reason,
        "failure_metric": policy.metric,
        "retry_limit": policy.retry_limit,
        **context,
    }
