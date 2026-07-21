"""发布验收脚本必须覆盖当前 Responses 主链路，而不是已退役入口。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_SCRIPTS = (
    "scripts/verify_e2e.sh",
    "scripts/verify_agent_cluster.sh",
    "scripts/verify_agent_bus_e2e.sh",
    "scripts/verify_error_envelope.sh",
)


def test_runtime_verifiers_do_not_call_retired_chat_api():
    for relative in RUNTIME_SCRIPTS:
        text = (ROOT / relative).read_text(encoding="utf-8")
        assert "/api/v1/chat" not in text, relative


def test_vnext_suite_only_references_existing_test_files():
    script = (ROOT / "scripts/run_vnext_final_tests.sh").read_text(encoding="utf-8")
    paths = [token.strip(" \\") for token in script.splitlines() if "tests/" in token]
    missing = [path for path in paths if not (ROOT / path).exists()]
    assert missing == []


def test_canonical_docker_start_seeds_the_configured_development_user():
    start = (ROOT / "start.sh").read_text(encoding="utf-8")
    seed = (ROOT / "scripts/seed_dev_user.py").read_text(encoding="utf-8")
    assert "python scripts/seed_dev_user.py" in start
    assert 'settings.app_env != "development"' in seed
    assert 'user.status = "active"' in seed
