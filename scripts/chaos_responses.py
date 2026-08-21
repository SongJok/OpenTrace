#!/usr/bin/env python3
"""Responses v2 故障演练编排器。

合同场景运行确定性故障测试；容器场景只允许显式 staging/chaos Compose 项目，并在 finally
恢复服务。执行结果写入不含 Response 正文和事件载荷的独占 JSON 证据文件。
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class Scenario:
    name: str
    kind: str
    expected: str
    command: tuple[str, ...] = ()
    service: str | None = None
    injection: str | None = None


SCENARIOS = {
    "redis-outage": Scenario(
        "redis-outage",
        "container",
        "Redis 停止期间 Response 仍由 PostgreSQL claim 收敛，事件序列连续，随后恢复 Redis",
        service="redis",
        injection="stop",
    ),
    "worker-kill": Scenario(
        "worker-kill",
        "container",
        "执行中 Worker 被 SIGKILL 后由持久租约恢复，事件序列连续，随后恢复 Worker",
        service="agent-worker",
        injection="kill",
    ),
    "duplicate-delivery": Scenario(
        "duplicate-delivery",
        "contract",
        "重复决定和恢复投递不产生额外 resume 或副作用",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_responses_contract.py::test_repeated_matching_approval_is_idempotent_without_extra_resume",
        ),
    ),
    "model-timeout": Scenario(
        "model-timeout",
        "contract",
        "超时保持有界并保留持久审批/工具状态",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_kernel_agent_loop.py::KernelFlowContractTests::test_approval_restore_keeps_governed_sql_timeout_and_no_retry",
        ),
    ),
    "unknown-side-effect": Scenario(
        "unknown-side-effect",
        "contract",
        "生产副作用未知结果进入 reconciliation 且不自动重试",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_kernel_agent_loop.py::KernelFlowContractTests::test_production_side_effect_timeout_requires_reconciliation",
        ),
    ),
    "connector-control-outage": Scenario(
        "connector-control-outage",
        "contract",
        "运行控制存储不可用时写操作失败关闭",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_production_intelligence_foundation.py::test_connector_runtime_control_rate_limit_and_store_failure_semantics",
        ),
    ),
    "asset-sync-race": Scenario(
        "asset-sync-race",
        "contract",
        "同来源同步在锁内重检游标，过期/并发游标不能提交",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_production_intelligence_foundation.py::test_asset_sync_serializes_sources_and_rechecks_cursor_inside_claim",
        ),
    ),
    "four-eye-replay": Scenario(
        "four-eye-replay",
        "contract",
        "同一账号重复批准不能满足四眼要求",
        (
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "tests/test_responses_contract.py::test_same_approver_cannot_count_twice_for_four_eye_approval",
        ),
    ),
}

_PROJECT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{2,63}$")
_TERMINAL = frozenset({"completed", "failed", "incomplete", "cancelled", "requires_action"})


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _run(command: list[str] | tuple[str, ...]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _safe_process_result(result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
    return {
        "returncode": result.returncode,
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("演练 API 禁止重定向，避免 Token 被转发到其他主机")


def _validate_base_url(base_url: str) -> None:
    parsed = urlsplit(base_url)
    host = str(parsed.hostname or "").lower()
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("--base-url 禁止 userinfo、query、fragment，且必须包含主机")
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host == "localhost"
    if parsed.scheme != "https" and not (parsed.scheme == "http" and is_loopback):
        raise RuntimeError("演练 Token 只允许发送到 HTTPS，HTTP 仅允许 loopback")
    allowed_host = str(os.getenv("CHAOS_API_HOST") or "").strip().lower()
    if not is_loopback and allowed_host != host:
        raise RuntimeError("非本机演练必须通过 CHAOS_API_HOST 精确绑定 API 主机")


def _request_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        opener = urllib.request.build_opener(_NoRedirect)
        with opener.open(request, timeout=10) as response:
            raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise RuntimeError("演练 API 响应超过 2 MB 上限")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def _response_snapshot(base_url: str, response_id: str, token: str) -> dict[str, Any]:
    payload = _request_json(f"{base_url.rstrip('/')}/api/v2/responses/{response_id}", token)
    if not isinstance(payload, dict):
        raise RuntimeError("Response 查询结果不是对象")
    # 演练证据禁止保存正文、参数、租户、用户和事件 payload。
    return {
        key: payload.get(key)
        for key in (
            "id",
            "status",
            "attempt_count",
            "max_attempts",
            "error_code",
            "created_at",
            "completed_at",
        )
    }


def _event_snapshot(base_url: str, response_id: str, token: str) -> list[dict[str, Any]]:
    payload = _request_json(
        f"{base_url.rstrip('/')}/api/v2/responses/{response_id}/events?starting_after=-1",
        token,
    )
    if not isinstance(payload, list):
        raise RuntimeError("Response 事件查询结果不是数组")
    return [
        {
            "sequence_number": item.get("sequence_number"),
            "type": item.get("type"),
            "created_at": item.get("created_at"),
        }
        for item in payload
        if isinstance(item, dict)
    ]


def _assert_contiguous(events: list[dict[str, Any]]) -> None:
    sequences = [item.get("sequence_number") for item in events]
    if not sequences or any(not isinstance(value, int) for value in sequences):
        raise RuntimeError("演练后没有完整的持久事件序列")
    if sequences[0] != 0 or sequences != list(range(len(sequences))):
        raise RuntimeError(f"事件 sequence_number 不连续: {sequences}")


def _wait_service_running(base: list[str], service: str, *, timeout_seconds: int = 60) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        status = _run([*base, "ps", "--status", "running", "--services", service])
        if status.returncode == 0 and service in status.stdout.splitlines():
            return
        time.sleep(1)
    raise RuntimeError(f"服务 {service!r} 未在 {timeout_seconds}s 内恢复 running")


def _poll_terminal(
    base_url: str,
    response_id: str,
    token: str,
    *,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = _response_snapshot(base_url, response_id, token)
        if last.get("status") in _TERMINAL:
            return last
        time.sleep(1)
    raise RuntimeError(f"Response 未在 {timeout_seconds}s 内收敛，最后状态={last.get('status')}")


def _write_evidence(path: Path, evidence: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(evidence, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise RuntimeError(f"拒绝覆盖既有演练证据: {path}") from exc


def _validate_container_target(args: argparse.Namespace) -> tuple[list[str], str]:
    target_env = str(os.getenv("CHAOS_TARGET_ENV") or "").lower()
    if target_env != "staging" or os.getenv("APP_ENV", "development").lower() == "production":
        raise RuntimeError("容器故障演练只允许 CHAOS_TARGET_ENV=staging 且 APP_ENV 非 production")
    project = str(args.compose_project or "")
    if not _PROJECT_PATTERN.fullmatch(project) or not any(
        marker in project for marker in ("staging", "chaos")
    ):
        raise RuntimeError("--compose-project 必须是显式包含 staging 或 chaos 的安全项目名")
    compose_file = Path(args.compose_file).resolve()
    if not compose_file.is_file():
        raise RuntimeError(f"Compose 文件不存在: {compose_file}")
    token = os.getenv("CHAOS_API_TOKEN", "")
    if not token:
        raise RuntimeError("必须通过 CHAOS_API_TOKEN 提供演练租户 Token，禁止写入命令行")
    if not args.response_id:
        raise RuntimeError("容器故障演练必须提供 --response-id")
    _validate_base_url(args.base_url)
    base = [
        "docker",
        "compose",
        "--project-name",
        project,
        "--file",
        str(compose_file),
    ]
    configured = _run([*base, "config", "--services"])
    if configured.returncode != 0:
        raise RuntimeError(f"无法读取目标 Compose: {configured.stderr[-1000:]}")
    return base, token


def _run_contract(scenario: Scenario) -> tuple[bool, dict[str, Any]]:
    started = time.monotonic()
    result = _run(scenario.command)
    return result.returncode == 0, {
        "command": list(scenario.command),
        "duration_seconds": round(time.monotonic() - started, 3),
        "process": _safe_process_result(result),
    }


def _run_container(
    scenario: Scenario,
    args: argparse.Namespace,
) -> tuple[bool, dict[str, Any]]:
    base, token = _validate_container_target(args)
    response_id = str(args.response_id)
    before = _response_snapshot(args.base_url, response_id, token)
    if before.get("status") in _TERMINAL:
        raise RuntimeError("注入前 Response 已结束，不能作为恢复演练对象")
    if scenario.name == "worker-kill" and before.get("status") != "in_progress":
        raise RuntimeError("worker-kill 必须选择已进入 in_progress 的 Response")
    service = str(scenario.service)
    services = set(_run([*base, "config", "--services"]).stdout.splitlines())
    if service not in services:
        raise RuntimeError(f"目标 Compose 不包含服务 {service!r}")
    running = _run([*base, "ps", "--status", "running", "--services", service])
    if running.returncode != 0 or service not in running.stdout.splitlines():
        raise RuntimeError(f"注入前服务 {service!r} 不是 running，拒绝生成无效演练")
    compose_before = _safe_process_result(_run([*base, "ps", "--format", "json"]))
    injected_at = _utc_now()
    inject = _run([*base, str(scenario.injection), service])
    if inject.returncode != 0:
        raise RuntimeError(f"故障注入失败: {inject.stderr[-1000:]}")
    terminal: dict[str, Any] = {}
    error: str | None = None
    recovery: subprocess.CompletedProcess[str] | None = None
    started = time.monotonic()
    try:
        if scenario.name == "worker-kill":
            recovery = _run([*base, "up", "-d", service])
            if recovery.returncode != 0:
                raise RuntimeError(f"Worker 恢复失败: {recovery.stderr[-1000:]}")
        terminal = _poll_terminal(
            args.base_url,
            response_id,
            token,
            timeout_seconds=args.timeout_seconds,
        )
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        error = str(exc)
    finally:
        if recovery is None:
            recovery = _run([*base, "up", "-d", service])
    if recovery.returncode != 0:
        recovery_error = f"服务恢复失败: {recovery.stderr[-1000:]}"
        error = f"{error}; {recovery_error}" if error else recovery_error
    else:
        try:
            _wait_service_running(base, service)
        except RuntimeError as exc:
            error = f"{error}; {exc}" if error else str(exc)
    events = _event_snapshot(args.base_url, response_id, token)
    try:
        _assert_contiguous(events)
    except RuntimeError as exc:
        error = f"{error}; {exc}" if error else str(exc)
    details = {
        "target": {
            "environment": "staging",
            "compose_project": args.compose_project,
            "compose_file": str(Path(args.compose_file).resolve()),
            "service": service,
        },
        "response_id": response_id,
        "before": before,
        "terminal": terminal,
        "expected_terminal_status": args.expected_status,
        "events": events,
        "injected_at": injected_at,
        "recovered_at": _utc_now(),
        "recovery_seconds": round(time.monotonic() - started, 3),
        "compose_before": compose_before,
        "injection": _safe_process_result(inject),
        "recovery": _safe_process_result(recovery),
        "error": error,
    }
    return error is None and terminal.get("status") == args.expected_status, details


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--allow-destructive", action="store_true")
    parser.add_argument("--evidence-output", type=Path)
    parser.add_argument("--compose-project")
    parser.add_argument("--compose-file", default="docker-compose.yml")
    parser.add_argument("--base-url", default="http://127.0.0.1:14100")
    parser.add_argument("--response-id")
    parser.add_argument("--expected-status", choices=sorted(_TERMINAL), default="completed")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    scenario = SCENARIOS[args.scenario]
    plan = {
        "scenario": scenario.name,
        "kind": scenario.kind,
        "expected": scenario.expected,
        "command": list(scenario.command),
        "service": scenario.service,
        "injection": scenario.injection,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if not args.execute:
        return 0
    if args.evidence_output is None:
        parser.error("执行演练必须提供 --evidence-output，禁止产生无审计证据的结果")
    if args.evidence_output.exists():
        parser.error(f"拒绝覆盖既有演练证据: {args.evidence_output}")
    if not 10 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds 必须在 10..1800 之间")
    if scenario.kind == "container" and not args.allow_destructive:
        parser.error("容器故障注入必须显式 --allow-destructive")
    evidence: dict[str, Any] = {
        "schema_version": 1,
        "scenario": scenario.name,
        "kind": scenario.kind,
        "expected": scenario.expected,
        "started_at": _utc_now(),
        "passed": False,
    }
    try:
        if scenario.kind == "contract":
            passed, details = _run_contract(scenario)
        else:
            passed, details = _run_container(scenario, args)
        evidence.update({"passed": passed, "details": details})
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        evidence["error"] = str(exc)
    evidence["finished_at"] = _utc_now()
    try:
        _write_evidence(args.evidence_output, evidence)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
