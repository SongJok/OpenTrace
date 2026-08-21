#!/usr/bin/env python3
"""Responses v2 持久主链容量基线工具。

分别测量命令接收、首持久事件、终态完成率和端到端延迟；HTTP 2xx 只代表命令被接收，绝不
等价于 Response 完成。Token 只能来自环境变量，发布证据文件使用独占创建。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import ipaddress
import json
import math
import os
import re
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

_TERMINAL_STATUSES = frozenset({"completed", "failed", "incomplete", "cancelled"})
_RELEASE_MINIMUM_TOTAL = 100
_RELEASE_MINIMUM_ACCEPTANCE_RATE = 0.99
_RELEASE_MINIMUM_COMPLETION_RATE = 0.99
_RELEASE_MAXIMUM_ACCEPTANCE_P95 = 2.0
_RELEASE_MAXIMUM_FIRST_EVENT_P95 = 2.0
_RELEASE_MAXIMUM_END_TO_END_P95 = 120.0
_DIGEST_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_RESPONSE_ID_PATTERN = re.compile(r"\bresp_[A-Za-z0-9_-]+\b")
_WORKLOAD_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_DEFAULT_INPUT = "仅回复 ok"


@dataclass(frozen=True)
class WorkloadCase:
    id: str
    input: str
    weight: int = 1


@dataclass(frozen=True)
class Sample:
    accepted: bool
    acceptance_seconds: float
    response_id: str | None = None
    terminal_status: str | None = None
    end_to_end_seconds: float | None = None
    first_event_seconds: float | None = None
    error: str | None = None
    workload_id: str = "inline"


def load_workload(path: Path) -> tuple[list[WorkloadCase], str]:
    """读取严格 JSONL 工作负载，并返回不泄露输入正文的规范化摘要哈希。"""

    try:
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("工作负载文件不得超过 2 MiB")
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ValueError(f"无法读取工作负载文件: {exc}") from exc
    cases: list[WorkloadCase] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(lines, start=1):
        if not raw_line.strip():
            continue
        try:
            item = json.loads(raw_line)
        except ValueError as exc:
            raise ValueError(f"工作负载第 {line_number} 行不是有效 JSON") from exc
        if not isinstance(item, dict) or set(item) - {"id", "input", "weight"}:
            raise ValueError(f"工作负载第 {line_number} 行只能包含 id/input/weight")
        case_id = item.get("id")
        request_input = item.get("input")
        weight = item.get("weight", 1)
        if not isinstance(case_id, str) or not _WORKLOAD_ID_PATTERN.fullmatch(case_id):
            raise ValueError(f"工作负载第 {line_number} 行 id 格式无效")
        if case_id in seen_ids:
            raise ValueError(f"工作负载第 {line_number} 行 id 重复")
        if (
            not isinstance(request_input, str)
            or not request_input.strip()
            or len(request_input) > 4000
        ):
            raise ValueError(f"工作负载第 {line_number} 行 input 必须是 1..4000 字符")
        if isinstance(weight, bool) or not isinstance(weight, int) or not 1 <= weight <= 100:
            raise ValueError(f"工作负载第 {line_number} 行 weight 必须在 1..100")
        seen_ids.add(case_id)
        cases.append(WorkloadCase(case_id, request_input, weight))
    if not cases:
        raise ValueError("工作负载文件不能为空")
    if len(cases) > 100 or sum(case.weight for case in cases) > 1000:
        raise ValueError("工作负载最多 100 个 case，权重总和不得超过 1000")
    canonical = json.dumps(
        [{"id": case.id, "input": case.input, "weight": case.weight} for case in cases],
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return cases, hashlib.sha256(canonical.encode()).hexdigest()


def _build_weighted_schedule(cases: list[WorkloadCase], total: int) -> list[WorkloadCase]:
    """使用平滑加权轮询，避免低权重场景被集中到压测尾部或完全漏测。"""

    if not cases or total < 1:
        raise ValueError("工作负载和样本总数必须为正")
    total_weight = sum(case.weight for case in cases)
    current_weights = [0] * len(cases)
    schedule: list[WorkloadCase] = []
    for _ in range(total):
        for index, case in enumerate(cases):
            current_weights[index] += case.weight
        selected = max(range(len(cases)), key=lambda index: (current_weights[index], -index))
        current_weights[selected] -= total_weight
        schedule.append(cases[selected])
    return schedule


def percentile(values: list[float], quantile: float) -> float | None:
    """使用 nearest-rank 口径，空样本显式返回 None，避免伪造 0 延迟。"""

    if not values:
        return None
    if not 0 <= quantile <= 1:
        raise ValueError("quantile 必须在 0..1 之间")
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, math.ceil(quantile * len(ordered)) - 1))
    return round(ordered[index], 6)


def _distribution(values: list[float]) -> dict[str, float | None]:
    return {
        "p50_seconds": percentile(values, 0.50),
        "p95_seconds": percentile(values, 0.95),
        "p99_seconds": percentile(values, 0.99),
        "max_seconds": round(max(values), 6) if values else None,
    }


def _validate_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    host = str(parsed.hostname or "").lower()
    if (
        not host
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("--base-url 必须是无 userinfo、query、fragment 和子路径的 API origin")
    try:
        loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        loopback = host == "localhost"
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise ValueError("负载测试 Token 只允许发送到 HTTPS，HTTP 仅允许 loopback")
    allowed_host = str(os.getenv("OPENTRACE_LOAD_API_HOST") or "").strip().lower()
    if not loopback and allowed_host != host:
        raise ValueError("非本机目标必须通过 OPENTRACE_LOAD_API_HOST 精确绑定主机")
    try:
        parsed_port = parsed.port
    except ValueError as exc:
        raise ValueError("--base-url 端口无效") from exc
    port = f":{parsed_port}" if parsed_port else ""
    origin_host = f"[{host}]" if ":" in host else host
    return f"{parsed.scheme}://{origin_host}{port}"


def _parse_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        return None
    return value.astimezone(UTC)


async def _first_event_duration(
    client: httpx.AsyncClient,
    *,
    base_url: str,
    response_id: str,
    created_at: datetime | None,
) -> float | None:
    if created_at is None:
        return None
    response = await client.get(f"{base_url}/api/v2/responses/{response_id}/events")
    if response.status_code != 200:
        return None
    payload = response.json()
    if not isinstance(payload, list):
        return None
    for expected_sequence, item in enumerate(payload):
        if not isinstance(item, dict) or item.get("sequence_number") != expected_sequence:
            return None
        if item.get("type") != "response.in_progress":
            continue
        event_at = _parse_datetime(item.get("created_at"))
        if event_at is not None:
            duration = (event_at - created_at).total_seconds()
            return duration if duration >= 0 else None
    return None


async def run_load(
    base_url: str,
    token: str,
    total: int,
    concurrency: int,
    *,
    workloads: list[WorkloadCase],
    response_timeout_seconds: float,
    poll_interval_seconds: float,
    expected_release_subject: str | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[list[Sample], float, str, str | None]:
    if not workloads:
        raise ValueError("workloads 不能为空")
    semaphore = asyncio.Semaphore(concurrency)
    samples: list[Sample | None] = [None] * total
    run_id = f"capacity-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:12]}"
    schedule = _build_weighted_schedule(workloads, total)
    timeout = httpx.Timeout(30.0, connect=10.0)
    headers = {"authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(
        timeout=timeout,
        trust_env=False,
        follow_redirects=False,
        headers=headers,
        transport=transport,
    ) as client:
        observed_release_revision: str | None = None
        if expected_release_subject is not None:
            try:
                health_response = await client.get(f"{base_url}/api/v1/health")
            except httpx.HTTPError as exc:
                raise RuntimeError(f"无法读取目标服务修订: {type(exc).__name__}") from exc
            if health_response.status_code != 200:
                raise RuntimeError(f"目标健康投影返回 HTTP {health_response.status_code}")
            try:
                health_payload = health_response.json()
            except ValueError as exc:
                raise RuntimeError("目标健康投影不是有效 JSON") from exc
            if isinstance(health_payload, dict):
                observed_release_revision = str(health_payload.get("release_revision") or "")
            if observed_release_revision != expected_release_subject:
                raise RuntimeError(
                    "目标服务 release_revision 与 --release-subject 不一致，拒绝生成发布证据"
                )

        async def one(index: int) -> None:
            async with semaphore:
                workload = schedule[index]
                started = time.monotonic()
                try:
                    response = await client.post(
                        f"{base_url}/api/v2/responses",
                        headers={"idempotency-key": f"{run_id}-{index}"},
                        json={"input": workload.input, "background": True},
                    )
                except httpx.HTTPError as exc:
                    samples[index] = Sample(
                        False,
                        time.monotonic() - started,
                        error=f"accept:{type(exc).__name__}",
                        workload_id=workload.id,
                    )
                    return
                acceptance_seconds = time.monotonic() - started
                if not 200 <= response.status_code < 300:
                    samples[index] = Sample(
                        False,
                        acceptance_seconds,
                        error=f"accept:http_{response.status_code}",
                        workload_id=workload.id,
                    )
                    return
                try:
                    created = response.json()
                except ValueError:
                    samples[index] = Sample(
                        False,
                        acceptance_seconds,
                        error="accept:invalid_json",
                        workload_id=workload.id,
                    )
                    return
                if not isinstance(created, dict):
                    samples[index] = Sample(
                        False,
                        acceptance_seconds,
                        error="accept:invalid_envelope",
                        workload_id=workload.id,
                    )
                    return
                response_id = str(created.get("id") or "")
                if not response_id.startswith("resp_"):
                    samples[index] = Sample(
                        False,
                        acceptance_seconds,
                        error="accept:missing_response_id",
                        workload_id=workload.id,
                    )
                    return
                created_at = _parse_datetime(created.get("created_at"))
                deadline = started + response_timeout_seconds
                terminal_status: str | None = None
                error: str | None = None
                while time.monotonic() < deadline:
                    try:
                        projection = await client.get(f"{base_url}/api/v2/responses/{response_id}")
                    except httpx.HTTPError as exc:
                        error = f"poll:{type(exc).__name__}"
                        await asyncio.sleep(poll_interval_seconds)
                        continue
                    if projection.status_code != 200:
                        error = f"poll:http_{projection.status_code}"
                    else:
                        try:
                            current = projection.json()
                        except ValueError:
                            current = None
                            error = "poll:invalid_json"
                        if isinstance(current, dict):
                            status = str(current.get("status") or "")
                            if status in _TERMINAL_STATUSES or status == "requires_action":
                                terminal_status = status
                                error = None
                                break
                    await asyncio.sleep(poll_interval_seconds)
                if terminal_status is None:
                    error = error or "response_timeout"
                # 端到端延迟止于终态投影或超时，不能把后续证据查询耗时混入执行 SLO。
                end_to_end_seconds = time.monotonic() - started
                first_event_seconds: float | None = None
                try:
                    first_event_seconds = await _first_event_duration(
                        client,
                        base_url=base_url,
                        response_id=response_id,
                        created_at=created_at,
                    )
                except (httpx.HTTPError, TypeError, ValueError):
                    first_event_seconds = None
                samples[index] = Sample(
                    True,
                    acceptance_seconds,
                    response_id=response_id,
                    terminal_status=terminal_status,
                    end_to_end_seconds=end_to_end_seconds,
                    first_event_seconds=first_event_seconds,
                    error=error,
                    workload_id=workload.id,
                )

        wall_started = time.monotonic()
        await asyncio.gather(*(one(index) for index in range(total)))
        wall_seconds = time.monotonic() - wall_started
    completed_samples = [sample for sample in samples if sample is not None]
    if len(completed_samples) != total:
        raise RuntimeError("容量运行未生成完整样本")
    return completed_samples, wall_seconds, run_id, observed_release_revision


def summarize_samples(
    samples: list[Sample],
    *,
    wall_seconds: float,
    run_id: str,
    base_url: str,
    concurrency: int,
) -> dict[str, Any]:
    total = len(samples)
    accepted = [sample for sample in samples if sample.accepted]
    completed = [sample for sample in accepted if sample.terminal_status == "completed"]
    acceptance_durations = [sample.acceptance_seconds for sample in samples]
    end_to_end_durations = [
        float(sample.end_to_end_seconds)
        for sample in accepted
        if sample.end_to_end_seconds is not None and sample.terminal_status is not None
    ]
    first_event_durations = [
        float(sample.first_event_seconds)
        for sample in accepted
        if sample.first_event_seconds is not None
    ]
    status_counts = Counter(sample.terminal_status or "not_terminal" for sample in accepted)
    error_counts = Counter(sample.error for sample in samples if sample.error)
    response_ids = sorted(
        str(sample.response_id) for sample in accepted if sample.response_id is not None
    )
    response_ids_digest = hashlib.sha256("\n".join(response_ids).encode()).hexdigest()
    workload_summaries: dict[str, Any] = {}
    for workload_id in sorted({sample.workload_id for sample in samples}):
        workload_samples = [sample for sample in samples if sample.workload_id == workload_id]
        workload_accepted = [sample for sample in workload_samples if sample.accepted]
        workload_completed = [
            sample for sample in workload_accepted if sample.terminal_status == "completed"
        ]
        workload_end_to_end = [
            float(sample.end_to_end_seconds)
            for sample in workload_accepted
            if sample.end_to_end_seconds is not None and sample.terminal_status is not None
        ]
        workload_first_event = [
            float(sample.first_event_seconds)
            for sample in workload_accepted
            if sample.first_event_seconds is not None
        ]
        workload_summaries[workload_id] = {
            "total": len(workload_samples),
            "accepted": len(workload_accepted),
            "acceptance_rate": round(len(workload_accepted) / len(workload_samples), 6),
            "completed": len(workload_completed),
            "completion_rate": (
                round(len(workload_completed) / len(workload_accepted), 6)
                if workload_accepted
                else 0.0
            ),
            "first_event_observed": len(workload_first_event),
            "acceptance": _distribution([sample.acceptance_seconds for sample in workload_samples]),
            "first_persisted_event": _distribution(workload_first_event),
            "end_to_end": _distribution(workload_end_to_end),
        }
    return {
        "schema_version": 1,
        "mode": "responses_v2_end_to_end_capacity",
        "generated_at": datetime.now(UTC).isoformat(),
        "run_id": run_id,
        "target_origin": base_url,
        "configuration": {"total": total, "concurrency": concurrency},
        "wall_seconds": round(wall_seconds, 6),
        "completed_throughput_rps": (
            round(len(completed) / wall_seconds, 6) if wall_seconds else 0.0
        ),
        "acceptance": {
            "accepted": len(accepted),
            "rate": round(len(accepted) / total, 6) if total else 0.0,
            **_distribution(acceptance_durations),
        },
        "responses": {
            "completed": len(completed),
            "completion_rate": round(len(completed) / len(accepted), 6) if accepted else 0.0,
            "status_counts": dict(sorted(status_counts.items())),
            **_distribution(end_to_end_durations),
        },
        "first_persisted_event": {
            "observed": len(first_event_durations),
            **_distribution(first_event_durations),
        },
        "errors": dict(sorted(error_counts.items())),
        "workloads": workload_summaries,
        "response_id_count": len(response_ids),
        "response_id_unique_count": len(set(response_ids)),
        "response_ids_sha256": response_ids_digest,
    }


def _meets_thresholds(report: dict[str, Any], args: argparse.Namespace) -> bool:
    acceptance = report["acceptance"]
    responses = report["responses"]
    first_event = report["first_persisted_event"]
    return all(
        (
            acceptance["rate"] >= args.minimum_acceptance_rate,
            responses["completion_rate"] >= args.minimum_completion_rate,
            acceptance["p95_seconds"] is not None
            and acceptance["p95_seconds"] <= args.maximum_acceptance_p95,
            responses["p95_seconds"] is not None
            and responses["p95_seconds"] <= args.maximum_end_to_end_p95,
            first_event["observed"] == acceptance["accepted"],
            first_event["p95_seconds"] is not None
            and first_event["p95_seconds"] <= args.maximum_first_event_p95,
        )
    )


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _contains_raw_response_id(value: object) -> bool:
    if isinstance(value, str):
        return _RESPONSE_ID_PATTERN.search(value) is not None
    if isinstance(value, dict):
        return any(_contains_raw_response_id(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_raw_response_id(item) for item in value)
    return False


def validate_release_report(
    report: object,
    *,
    expected_subject: str,
    max_age_hours: float,
    now: datetime | None = None,
) -> list[str]:
    """验证容量证据本身，而不是信任报告内可调阈值。"""

    errors: list[str] = []
    if not isinstance(report, dict):
        return ["容量证据根节点必须是对象"]
    if report.get("schema_version") != 1:
        errors.append("schema_version 必须为 1")
    if report.get("mode") != "responses_v2_end_to_end_capacity":
        errors.append("mode 不是 Responses v2 端到端容量证据")
    if report.get("source_revision") != expected_subject:
        errors.append("source_revision 与当前发布候选不一致")
    if report.get("observed_release_revision") != expected_subject:
        errors.append("observed_release_revision 未证明目标服务运行当前发布候选")
    generated_at = _parse_datetime(report.get("generated_at"))
    current = (now or datetime.now(UTC)).astimezone(UTC)
    if generated_at is None:
        errors.append("generated_at 必须是带时区的 RFC3339 时间")
    elif generated_at > current + timedelta(minutes=5):
        errors.append("generated_at 不得位于未来")
    elif (current - generated_at).total_seconds() > max_age_hours * 3600:
        errors.append(f"容量证据超过 {max_age_hours:g} 小时有效期")

    target_origin = report.get("target_origin")
    if not isinstance(target_origin, str):
        errors.append("target_origin 缺失")
    else:
        parsed = urlsplit(target_origin)
        try:
            _ = parsed.port
            valid_port = True
        except ValueError:
            valid_port = False
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or not valid_port
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            errors.append("发布容量证据必须来自无凭据、无子路径的 HTTPS origin")

    configuration = report.get("configuration")
    acceptance = report.get("acceptance")
    responses = report.get("responses")
    first_event = report.get("first_persisted_event")
    thresholds = report.get("thresholds")
    workload_summaries = report.get("workloads")
    if not all(
        isinstance(item, dict)
        for item in (
            configuration,
            acceptance,
            responses,
            first_event,
            thresholds,
            workload_summaries,
        )
    ):
        errors.append(
            "configuration/acceptance/responses/first_persisted_event/thresholds/workloads 缺失"
        )
        return errors

    assert isinstance(configuration, dict)
    assert isinstance(acceptance, dict)
    assert isinstance(responses, dict)
    assert isinstance(first_event, dict)
    assert isinstance(thresholds, dict)
    assert isinstance(workload_summaries, dict)
    total = configuration.get("total")
    concurrency = configuration.get("concurrency")
    if isinstance(total, bool) or not isinstance(total, int) or total < _RELEASE_MINIMUM_TOTAL:
        errors.append(f"发布容量样本数不得少于 {_RELEASE_MINIMUM_TOTAL}")
    if (
        isinstance(concurrency, bool)
        or not isinstance(concurrency, int)
        or not isinstance(total, int)
        or not 1 <= concurrency <= min(total, 500)
    ):
        errors.append("concurrency 与 total 不匹配")
    workload_digest = configuration.get("workload_sha256")
    if not isinstance(workload_digest, str) or not _DIGEST_PATTERN.fullmatch(workload_digest):
        errors.append("workload_sha256 缺失或格式无效")
    workload_case_count = configuration.get("workload_case_count")
    if (
        isinstance(workload_case_count, bool)
        or not isinstance(workload_case_count, int)
        or workload_case_count < 4
        or workload_case_count != len(workload_summaries)
    ):
        errors.append("发布容量证据至少需要 4 个工作负载场景且计数必须一致")

    accepted = acceptance.get("accepted")
    completed = responses.get("completed")
    observed = first_event.get("observed")
    if not isinstance(accepted, int) or isinstance(accepted, bool) or not isinstance(total, int):
        errors.append("accepted 计数无效")
    elif not 0 <= accepted <= total:
        errors.append("accepted 计数越界")
    if not isinstance(completed, int) or isinstance(completed, bool):
        errors.append("completed 计数无效")
    elif isinstance(accepted, int) and not 0 <= completed <= accepted:
        errors.append("completed 计数越界")
    if observed != accepted:
        errors.append("每个已接收 Response 都必须观察到首持久事件")

    workload_total = 0
    for workload_id, raw_summary in workload_summaries.items():
        if not isinstance(workload_id, str) or not _WORKLOAD_ID_PATTERN.fullmatch(workload_id):
            errors.append("工作负载场景 ID 格式无效")
            continue
        if not isinstance(raw_summary, dict):
            errors.append(f"工作负载 {workload_id} 汇总无效")
            continue
        case_total = raw_summary.get("total")
        case_accepted = raw_summary.get("accepted")
        case_completed = raw_summary.get("completed")
        case_observed = raw_summary.get("first_event_observed")
        if isinstance(case_total, bool) or not isinstance(case_total, int) or case_total < 10:
            errors.append(f"工作负载 {workload_id} 的样本数不得少于 10")
            continue
        workload_total += case_total
        if (
            not isinstance(case_accepted, int)
            or isinstance(case_accepted, bool)
            or not 0 <= case_accepted <= case_total
            or not isinstance(case_completed, int)
            or isinstance(case_completed, bool)
            or not 0 <= case_completed <= case_accepted
        ):
            errors.append(f"工作负载 {workload_id} 的接收/完成计数无效")
            continue
        if case_observed != case_accepted:
            errors.append(f"工作负载 {workload_id} 缺少首持久事件")
        case_acceptance_rate = _number(raw_summary.get("acceptance_rate"))
        case_completion_rate = _number(raw_summary.get("completion_rate"))
        if (
            case_acceptance_rate is None
            or case_acceptance_rate < _RELEASE_MINIMUM_ACCEPTANCE_RATE
            or abs(case_acceptance_rate - round(case_accepted / case_total, 6)) > 1e-6
        ):
            errors.append(f"工作负载 {workload_id} 接收率未达标或与计数不一致")
        expected_completion_rate = (
            round(case_completed / case_accepted, 6) if case_accepted else 0.0
        )
        if (
            case_completion_rate is None
            or case_completion_rate < _RELEASE_MINIMUM_COMPLETION_RATE
            or abs(case_completion_rate - expected_completion_rate) > 1e-6
        ):
            errors.append(f"工作负载 {workload_id} 完成率未达标或与计数不一致")
        for section_name, limit, label in (
            ("acceptance", _RELEASE_MAXIMUM_ACCEPTANCE_P95, "接收 P95"),
            ("first_persisted_event", _RELEASE_MAXIMUM_FIRST_EVENT_P95, "首事件 P95"),
            ("end_to_end", _RELEASE_MAXIMUM_END_TO_END_P95, "端到端 P95"),
        ):
            section = raw_summary.get(section_name)
            value = _number(section.get("p95_seconds")) if isinstance(section, dict) else None
            if value is None or value < 0 or value > limit:
                errors.append(f"工作负载 {workload_id} {label} 未达标")
    if isinstance(total, int) and workload_total != total:
        errors.append("各工作负载样本数之和与 total 不一致")

    acceptance_rate = _number(acceptance.get("rate"))
    completion_rate = _number(responses.get("completion_rate"))
    if acceptance_rate is None or acceptance_rate < _RELEASE_MINIMUM_ACCEPTANCE_RATE:
        errors.append("接收率未达到发布底线 0.99")
    if completion_rate is None or completion_rate < _RELEASE_MINIMUM_COMPLETION_RATE:
        errors.append("完成率未达到发布底线 0.99")
    if isinstance(total, int) and total > 0 and isinstance(accepted, int):
        if acceptance_rate is None or abs(acceptance_rate - round(accepted / total, 6)) > 1e-6:
            errors.append("接收率与计数不一致")
    if isinstance(accepted, int) and accepted > 0 and isinstance(completed, int):
        if completion_rate is None or abs(completion_rate - round(completed / accepted, 6)) > 1e-6:
            errors.append("完成率与计数不一致")

    measured_limits = (
        (acceptance.get("p95_seconds"), _RELEASE_MAXIMUM_ACCEPTANCE_P95, "接收 P95"),
        (first_event.get("p95_seconds"), _RELEASE_MAXIMUM_FIRST_EVENT_P95, "首事件 P95"),
        (responses.get("p95_seconds"), _RELEASE_MAXIMUM_END_TO_END_P95, "端到端 P95"),
    )
    for raw_value, limit, label in measured_limits:
        value = _number(raw_value)
        if value is None or value < 0 or value > limit:
            errors.append(f"{label} 未达到发布底线 {limit:g} 秒")

    configured_limits = (
        (thresholds.get("minimum_acceptance_rate"), _RELEASE_MINIMUM_ACCEPTANCE_RATE, True),
        (thresholds.get("minimum_completion_rate"), _RELEASE_MINIMUM_COMPLETION_RATE, True),
        (thresholds.get("maximum_acceptance_p95"), _RELEASE_MAXIMUM_ACCEPTANCE_P95, False),
        (thresholds.get("maximum_first_event_p95"), _RELEASE_MAXIMUM_FIRST_EVENT_P95, False),
        (thresholds.get("maximum_end_to_end_p95"), _RELEASE_MAXIMUM_END_TO_END_P95, False),
    )
    for raw_value, baseline, minimum in configured_limits:
        value = _number(raw_value)
        if value is None or (minimum and value < baseline) or (not minimum and value > baseline):
            errors.append("报告运行阈值比发布底线更宽松")
            break

    status_counts = responses.get("status_counts")
    if not isinstance(status_counts, dict) or any(
        isinstance(count, bool) or not isinstance(count, int) or count < 0
        for count in status_counts.values()
    ):
        errors.append("status_counts 无效")
    elif isinstance(accepted, int) and sum(status_counts.values()) != accepted:
        errors.append("status_counts 与 accepted 不一致")
    elif isinstance(completed, int) and status_counts.get("completed", 0) != completed:
        errors.append("status_counts 与 completed 不一致")

    response_id_count = report.get("response_id_count")
    response_id_unique_count = report.get("response_id_unique_count")
    response_ids_digest = report.get("response_ids_sha256")
    if response_id_count != accepted:
        errors.append("response_id_count 与 accepted 不一致")
    if response_id_unique_count != accepted:
        errors.append("response_id_unique_count 与 accepted 不一致，疑似幂等键串线")
    if not isinstance(response_ids_digest, str) or not _DIGEST_PATTERN.fullmatch(
        response_ids_digest
    ):
        errors.append("response_ids_sha256 缺失或格式无效")
    if report.get("thresholds_passed") is not True:
        errors.append("容量运行未通过其声明阈值")
    if _contains_raw_response_id(report):
        errors.append("容量报告不得包含原始 response_id")
    return errors


def _write_report(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError as exc:
        raise ValueError(f"拒绝覆盖既有容量证据: {path}") from exc


def _validate_release_subject(raw: str) -> str:
    subject = raw.strip()
    if not 7 <= len(subject) <= 512 or any(character.isspace() for character in subject):
        raise ValueError("--release-subject 必须是 7..512 字符且不含空白的提交或镜像摘要")
    return subject


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:14100")
    parser.add_argument("--token-env", default="OPENTRACE_LOAD_TOKEN")
    parser.add_argument("--input", default=_DEFAULT_INPUT)
    parser.add_argument("--workload-file", type=Path)
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--response-timeout-seconds", type=float, default=180.0)
    parser.add_argument("--poll-interval-seconds", type=float, default=0.25)
    parser.add_argument("--minimum-acceptance-rate", type=float, default=0.99)
    parser.add_argument("--minimum-completion-rate", type=float, default=0.99)
    parser.add_argument("--maximum-acceptance-p95", type=float, default=2.0)
    parser.add_argument("--maximum-first-event-p95", type=float, default=2.0)
    parser.add_argument("--maximum-end-to-end-p95", type=float, default=120.0)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--release-gate", action="store_true")
    parser.add_argument("--release-subject")
    parser.add_argument("--verify-report", type=Path)
    parser.add_argument("--max-evidence-age-hours", type=float, default=72.0)
    args = parser.parse_args()
    release_subject: str | None = None
    if args.release_subject:
        try:
            release_subject = _validate_release_subject(args.release_subject)
        except ValueError as exc:
            parser.error(str(exc))
    if args.verify_report is not None:
        if args.release_gate or args.output is not None:
            parser.error("--verify-report 不能与 --release-gate/--output 同时使用")
        if release_subject is None:
            parser.error("--verify-report 必须提供 --release-subject 绑定当前候选版本")
        if (
            not math.isfinite(args.max_evidence_age_hours)
            or not 1 <= args.max_evidence_age_hours <= 720
        ):
            parser.error("--max-evidence-age-hours 必须在 1..720")
        try:
            report = json.loads(args.verify_report.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            parser.error(f"无法读取容量证据: {exc}")
        errors = validate_release_report(
            report,
            expected_subject=release_subject,
            max_age_hours=args.max_evidence_age_hours,
        )
        result = {
            "mode": "responses_v2_capacity_evidence_verification",
            "report": str(args.verify_report),
            "source_revision": release_subject,
            "passed": not errors,
            "errors": errors,
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    try:
        base_url = _validate_base_url(args.base_url)
    except ValueError as exc:
        parser.error(str(exc))
    token = os.getenv(args.token_env, "")
    if not token:
        parser.error(f"必须通过环境变量 {args.token_env} 提供 Token")
    if args.release_gate and args.output is None:
        parser.error("--release-gate 必须提供 --output 归档不可覆盖的容量证据")
    if args.release_gate and release_subject is None:
        parser.error("--release-gate 必须提供 --release-subject 绑定当前候选版本")
    if args.release_gate and urlsplit(base_url).scheme != "https":
        parser.error("发布容量证据必须从 HTTPS 目标采集，loopback 仅用于开发验证")
    if args.release_gate and args.workload_file is None:
        parser.error("--release-gate 必须提供多场景 --workload-file，单输入不能作为发布证据")
    if args.output is not None and args.output.exists():
        parser.error(f"拒绝覆盖既有容量证据: {args.output}")
    if not 1 <= args.total <= 10_000 or not 1 <= args.concurrency <= min(args.total, 500):
        parser.error("--total 必须在 1..10000，--concurrency 必须在 1..min(total,500)")
    if not 10 <= args.response_timeout_seconds <= 3600:
        parser.error("--response-timeout-seconds 必须在 10..3600")
    if not 0.1 <= args.poll_interval_seconds <= 5:
        parser.error("--poll-interval-seconds 必须在 0.1..5")
    if not args.input.strip() or len(args.input) > 4000:
        parser.error("--input 必须是 1..4000 字符")
    for name in ("minimum_acceptance_rate", "minimum_completion_rate"):
        if not 0 <= getattr(args, name) <= 1:
            parser.error(f"--{name.replace('_', '-')} 必须在 0..1")
    for name in (
        "maximum_acceptance_p95",
        "maximum_first_event_p95",
        "maximum_end_to_end_p95",
    ):
        value = getattr(args, name)
        if not math.isfinite(value) or value <= 0:
            parser.error(f"--{name.replace('_', '-')} 必须是正有限数")
    if args.release_gate:
        if args.total < _RELEASE_MINIMUM_TOTAL:
            parser.error(f"发布容量样本数不得少于 {_RELEASE_MINIMUM_TOTAL}")
        if (
            args.minimum_acceptance_rate < _RELEASE_MINIMUM_ACCEPTANCE_RATE
            or args.minimum_completion_rate < _RELEASE_MINIMUM_COMPLETION_RATE
            or args.maximum_acceptance_p95 > _RELEASE_MAXIMUM_ACCEPTANCE_P95
            or args.maximum_first_event_p95 > _RELEASE_MAXIMUM_FIRST_EVENT_P95
            or args.maximum_end_to_end_p95 > _RELEASE_MAXIMUM_END_TO_END_P95
        ):
            parser.error("--release-gate 不允许放宽固定发布底线")
    if args.workload_file is not None:
        try:
            workloads, workload_digest = load_workload(args.workload_file)
        except ValueError as exc:
            parser.error(str(exc))
    else:
        workloads = [WorkloadCase("inline", args.input)]
        workload_digest = hashlib.sha256(args.input.encode()).hexdigest()
    if args.release_gate and len(workloads) < 4:
        parser.error("发布容量工作负载至少需要 4 个不同场景")
    planned_counts = Counter(case.id for case in _build_weighted_schedule(workloads, args.total))
    if args.release_gate and min(planned_counts.values()) < 10:
        parser.error("发布容量运行必须为每个工作负载场景提供至少 10 个样本")

    try:
        samples, wall_seconds, run_id, observed_release_revision = asyncio.run(
            run_load(
                base_url,
                token,
                args.total,
                args.concurrency,
                workloads=workloads,
                response_timeout_seconds=args.response_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                expected_release_subject=release_subject if args.release_gate else None,
            )
        )
    except RuntimeError as exc:
        parser.error(str(exc))
    report = summarize_samples(
        samples,
        wall_seconds=wall_seconds,
        run_id=run_id,
        base_url=base_url,
        concurrency=args.concurrency,
    )
    report["source_revision"] = release_subject
    report["observed_release_revision"] = observed_release_revision
    report["configuration"].update(
        {
            "response_timeout_seconds": args.response_timeout_seconds,
            "poll_interval_seconds": args.poll_interval_seconds,
            "workload_case_count": len(workloads),
            "workload_sha256": workload_digest,
        }
    )
    report["thresholds"] = {
        "minimum_acceptance_rate": args.minimum_acceptance_rate,
        "minimum_completion_rate": args.minimum_completion_rate,
        "maximum_acceptance_p95": args.maximum_acceptance_p95,
        "maximum_first_event_p95": args.maximum_first_event_p95,
        "maximum_end_to_end_p95": args.maximum_end_to_end_p95,
    }
    report["thresholds_passed"] = _meets_thresholds(report, args)
    text = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output is not None:
        try:
            _write_report(args.output, text)
        except ValueError as exc:
            parser.error(str(exc))
    print(text, end="")
    return 0 if report["thresholds_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
