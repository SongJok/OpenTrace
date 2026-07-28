from pathlib import Path

from infra.reliability.failure_policy import FailureMode, FailurePolicy, policy_metadata
from scripts.check_enterprise_boundaries import legacy_dependents

ROOT = Path(__file__).resolve().parents[1]


def test_legacy_runtime_dependencies_are_frozen():
    allowlist = {
        line.strip()
        for line in (ROOT / "architecture" / "legacy_runtime_allowlist.txt")
        .read_text()
        .splitlines()
        if line.strip()
    }
    assert legacy_dependents().issubset(allowlist)


def test_reconciliation_policy_forbids_retry():
    policy = FailurePolicy(
        FailureMode.RECONCILE,
        reason="unknown external result",
        metric="reconciliation_total",
    )
    assert policy_metadata(policy)["retry_limit"] == 0
