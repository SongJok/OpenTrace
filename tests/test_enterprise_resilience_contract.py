from pathlib import Path

import pytest

from scripts.chaos_responses import (
    SCENARIOS,
    _assert_contiguous,
    _validate_base_url,
    _write_evidence,
    main,
)

ROOT = Path(__file__).resolve().parents[1]


def test_required_failure_scenarios_are_defined():
    assert {
        "redis-outage",
        "worker-kill",
        "duplicate-delivery",
        "model-timeout",
        "unknown-side-effect",
        "connector-control-outage",
        "asset-sync-race",
        "four-eye-replay",
    }.issubset(SCENARIOS)
    assert all(item.expected for item in SCENARIOS.values())
    assert all(
        "::test_" in " ".join(item.command)
        for item in SCENARIOS.values()
        if item.kind == "contract"
    )


def test_chaos_execution_requires_an_exclusive_evidence_file(tmp_path):
    with pytest.raises(SystemExit):
        main(["duplicate-delivery", "--execute"])

    evidence = tmp_path / "existing.json"
    evidence.write_text("{}", encoding="utf-8")
    with pytest.raises(SystemExit):
        main(
            [
                "duplicate-delivery",
                "--execute",
                "--evidence-output",
                str(evidence),
            ]
        )


def test_chaos_event_evidence_requires_sequence_from_zero_without_gaps():
    _assert_contiguous(
        [
            {"sequence_number": 0, "type": "response.created"},
            {"sequence_number": 1, "type": "response.in_progress"},
        ]
    )
    with pytest.raises(RuntimeError, match="不连续"):
        _assert_contiguous(
            [
                {"sequence_number": 0, "type": "response.created"},
                {"sequence_number": 2, "type": "response.completed"},
            ]
        )


def test_chaos_evidence_writer_never_overwrites_a_previous_drill(tmp_path):
    path = tmp_path / "drill.json"
    _write_evidence(path, {"schema_version": 1, "passed": True})
    with pytest.raises(RuntimeError, match="拒绝覆盖"):
        _write_evidence(path, {"schema_version": 1, "passed": False})


def test_chaos_api_token_is_bound_to_https_or_loopback(monkeypatch):
    _validate_base_url("http://127.0.0.1:14100")
    monkeypatch.setenv("CHAOS_API_HOST", "staging.example.com")
    _validate_base_url("https://staging.example.com")
    with pytest.raises(RuntimeError, match="HTTPS"):
        _validate_base_url("http://staging.example.com")
    with pytest.raises(RuntimeError, match="精确绑定"):
        _validate_base_url("https://evil.example.com")
    with pytest.raises(RuntimeError, match="userinfo"):
        _validate_base_url("https://user@staging.example.com")


def test_backup_and_restore_scripts_are_fail_closed():
    backup = (ROOT / "scripts" / "backup_postgres.sh").read_text(encoding="utf-8")
    restore = (ROOT / "scripts" / "restore_postgres.sh").read_text(encoding="utf-8")
    assert "pg_restore --list" in backup
    assert "sha256sum" in backup
    assert "RESTORE_DATABASE_URL" in restore
    assert "ALLOW_PRODUCTION_RESTORE" in restore
