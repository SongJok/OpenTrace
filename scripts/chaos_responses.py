#!/usr/bin/env python3
"""Responses 主路径故障注入编排器。

默认只输出计划；必须显式 --execute 和 --allow-destructive，并限定非 production 环境。
"""

from __future__ import annotations

import argparse
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Scenario:
    name: str
    command: tuple[str, ...]
    expected: str


SCENARIOS = {
    "redis-outage": Scenario(
        "redis-outage",
        ("docker", "compose", "stop", "redis"),
        "Worker 通过 PostgreSQL claim 继续恢复，Outbox 保持 pending",
    ),
    "worker-kill": Scenario(
        "worker-kill",
        ("docker", "compose", "kill", "agent-worker"),
        "lease 到期后由新 Worker 接管且无重复副作用",
    ),
    "duplicate-delivery": Scenario(
        "duplicate-delivery",
        ("python", "-m", "pytest", "-q", "tests/test_responses_contract.py", "-k", "idempot"),
        "重复消息复用工具账本和 Response 幂等键",
    ),
    "model-timeout": Scenario(
        "model-timeout",
        ("python", "-m", "pytest", "-q", "tests/test_kernel_agent_loop.py", "-k", "timeout"),
        "有限重试后持久化明确失败或降级事件",
    ),
    "unknown-side-effect": Scenario(
        "unknown-side-effect",
        ("python", "-m", "pytest", "-q", "tests/test_responses_contract.py", "-k", "reconcil"),
        "副作用未知结果进入 reconciliation 且不自动重试",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true")
    args = parser.parse_args()
    scenario = SCENARIOS[args.scenario]
    print(
        f"scenario={scenario.name}\nexpected={scenario.expected}\ncommand={' '.join(scenario.command)}"
    )
    if not args.execute:
        return 0
    if os.getenv("APP_ENV", "development") == "production":
        raise SystemExit("禁止在 production 直接执行故障注入")
    if scenario.name in {"redis-outage", "worker-kill"} and not args.allow_destructive:
        raise SystemExit("容器故障注入必须显式 --allow-destructive")
    return subprocess.run(scenario.command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
