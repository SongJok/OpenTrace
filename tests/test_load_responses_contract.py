from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from argparse import Namespace
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from scripts.load_responses import (
    Sample,
    WorkloadCase,
    _meets_thresholds,
    _validate_base_url,
    _write_report,
    load_workload,
    main,
    percentile,
    run_load,
    summarize_samples,
    validate_release_report,
)


def _valid_release_report() -> dict:
    report = summarize_samples(
        [
            Sample(
                True,
                0.1,
                f"resp_{index}",
                "completed",
                1.0,
                0.2,
                workload_id=f"case-{index % 4}",
            )
            for index in range(100)
        ],
        wall_seconds=10.0,
        run_id="capacity-release-test",
        base_url="https://staging.example.com",
        concurrency=10,
    )
    report["source_revision"] = "a" * 40
    report["observed_release_revision"] = "a" * 40
    report["configuration"].update(
        {
            "response_timeout_seconds": 180.0,
            "poll_interval_seconds": 0.25,
            "workload_case_count": 4,
            "workload_sha256": hashlib.sha256(b"test-workload").hexdigest(),
        }
    )
    report["thresholds"] = {
        "minimum_acceptance_rate": 0.99,
        "minimum_completion_rate": 0.99,
        "maximum_acceptance_p95": 2.0,
        "maximum_first_event_p95": 2.0,
        "maximum_end_to_end_p95": 120.0,
    }
    report["thresholds_passed"] = True
    return report


def test_capacity_percentile_uses_nearest_rank_and_never_fabricates_empty_latency():
    assert percentile([], 0.95) is None
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.0
    with pytest.raises(ValueError):
        percentile([1.0], 1.1)


def test_capacity_summary_separates_acceptance_from_terminal_completion():
    report = summarize_samples(
        [
            Sample(True, 0.1, "resp_1", "completed", 1.0, 0.2),
            Sample(True, 0.2, "resp_2", "failed", 2.0, 0.3),
            Sample(False, 0.4, error="accept:http_503"),
        ],
        wall_seconds=2.0,
        run_id="capacity-test",
        base_url="https://staging.example.com",
        concurrency=2,
    )

    assert report["acceptance"]["rate"] == pytest.approx(2 / 3, abs=1e-6)
    assert report["responses"]["completion_rate"] == 0.5
    assert report["responses"]["status_counts"] == {"completed": 1, "failed": 1}
    assert report["completed_throughput_rps"] == 0.5
    assert report["response_id_count"] == 2
    assert "resp_1" not in report["response_ids_sha256"]


def test_capacity_threshold_requires_first_event_for_every_accepted_response():
    report = summarize_samples(
        [Sample(True, 0.1, "resp_1", "completed", 1.0, None)],
        wall_seconds=1.0,
        run_id="capacity-test",
        base_url="http://127.0.0.1:14100",
        concurrency=1,
    )
    args = Namespace(
        minimum_acceptance_rate=0.99,
        minimum_completion_rate=0.99,
        maximum_acceptance_p95=2.0,
        maximum_end_to_end_p95=120.0,
        maximum_first_event_p95=2.0,
    )

    assert _meets_thresholds(report, args) is False


def test_capacity_target_rejects_token_exfiltration(monkeypatch):
    assert _validate_base_url("http://127.0.0.1:14100/") == "http://127.0.0.1:14100"
    monkeypatch.setenv("OPENTRACE_LOAD_API_HOST", "staging.example.com")
    assert _validate_base_url("https://staging.example.com") == "https://staging.example.com"
    with pytest.raises(ValueError, match="HTTPS"):
        _validate_base_url("http://staging.example.com")
    with pytest.raises(ValueError, match="精确绑定"):
        _validate_base_url("https://evil.example.com")
    with pytest.raises(ValueError, match="origin"):
        _validate_base_url("https://user@staging.example.com/api")


def test_capacity_report_is_exclusive(tmp_path):
    path = tmp_path / "capacity.json"
    _write_report(path, "{}\n")
    with pytest.raises(ValueError, match="拒绝覆盖"):
        _write_report(path, "{}\n")


def test_capacity_workload_contract_is_strict_and_hashes_canonical_content(tmp_path):
    path = tmp_path / "workload.jsonl"
    path.write_text(
        '{"id":"rag-read","input":"查询知识库证据","weight":2}\n'
        '{"id":"data-read","input":"查询数据指标"}\n',
        encoding="utf-8",
    )

    cases, digest = load_workload(path)

    assert cases == [
        WorkloadCase("rag-read", "查询知识库证据", 2),
        WorkloadCase("data-read", "查询数据指标", 1),
    ]
    assert len(digest) == 64


def test_capacity_release_evidence_is_bound_to_revision_and_fixed_policy():
    report = _valid_release_report()

    assert (
        validate_release_report(
            report,
            expected_subject="a" * 40,
            max_age_hours=72,
        )
        == []
    )


def test_capacity_release_evidence_rejects_stale_relaxed_or_sensitive_report():
    report = _valid_release_report()
    report["generated_at"] = (datetime.now(UTC) - timedelta(hours=73)).isoformat()
    report["thresholds"]["minimum_completion_rate"] = 0.5
    report["debug_response"] = "resp_secret"

    errors = validate_release_report(
        report,
        expected_subject="b" * 40,
        max_age_hours=72,
    )

    assert any("source_revision" in error for error in errors)
    assert any("有效期" in error for error in errors)
    assert any("更宽松" in error for error in errors)
    assert any("原始 response_id" in error for error in errors)


def test_capacity_release_evidence_cli_verifies_without_runtime_token(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / "capacity.json"
    path.write_text(json.dumps(_valid_release_report()), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "load_responses.py",
            "--verify-report",
            str(path),
            "--release-subject",
            "a" * 40,
        ],
    )

    assert main() == 0
    assert json.loads(capsys.readouterr().out)["passed"] is True


def test_capacity_runner_follows_real_response_to_terminal_and_events():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/health":
            return httpx.Response(200, json={"release_revision": "a" * 40})
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"id": "resp_real", "created_at": "2026-08-20T10:00:00+00:00"},
            )
        if request.url.path.endswith("/events"):
            return httpx.Response(
                200,
                json=[
                    {
                        "sequence_number": 0,
                        "type": "response.created",
                        "created_at": "2026-08-20T10:00:00+00:00",
                    },
                    {
                        "sequence_number": 1,
                        "type": "response.in_progress",
                        "created_at": "2026-08-20T10:00:01+00:00",
                    },
                ],
            )
        return httpx.Response(200, json={"id": "resp_real", "status": "completed"})

    samples, wall_seconds, run_id, observed_revision = asyncio.run(
        run_load(
            "https://staging.example.com",
            "secret-token",
            1,
            1,
            workloads=[WorkloadCase("inline", "只回复 ok")],
            response_timeout_seconds=10,
            poll_interval_seconds=0.1,
            expected_release_subject="a" * 40,
            transport=httpx.MockTransport(handler),
        )
    )

    assert wall_seconds >= 0
    assert run_id.startswith("capacity-")
    assert observed_revision == "a" * 40
    assert samples[0].accepted is True
    assert samples[0].terminal_status == "completed"
    assert samples[0].first_event_seconds == 1.0


def test_capacity_runner_rejects_stale_target_before_sending_workload():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"release_revision": "old-revision"})

    with pytest.raises(RuntimeError, match="release_revision"):
        asyncio.run(
            run_load(
                "https://staging.example.com",
                "secret-token",
                1,
                1,
                workloads=[WorkloadCase("inline", "只回复 ok")],
                response_timeout_seconds=10,
                poll_interval_seconds=0.1,
                expected_release_subject="a" * 40,
                transport=httpx.MockTransport(handler),
            )
        )

    assert [request.url.path for request in requests] == ["/api/v1/health"]
