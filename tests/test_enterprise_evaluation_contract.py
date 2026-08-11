from __future__ import annotations

from pathlib import Path

from evals.runner import evaluate_dataset, load_dataset, score_output

ROOT = Path(__file__).resolve().parents[1]


def test_enterprise_golden_datasets_are_non_empty_and_uniquely_identified():
    ids: set[str] = set()
    for name in (
        "agent_loop",
        "rag",
        "data_agent",
        "memory",
    ):
        cases = load_dataset(ROOT / "evals" / "datasets" / f"{name}.jsonl")
        assert len(cases) >= 3
        assert not ids.intersection(case.case_id for case in cases)
        ids.update(case.case_id for case in cases)


def test_score_output_reports_failed_contracts():
    score, failures = score_output(
        {"status": "failed", "latency_ms": 200},
        {"exact": {"status": "completed"}, "at_most": {"latency_ms": 100}},
    )
    assert score == 0
    assert len(failures) == 2


def test_dataset_executor_is_pluggable(tmp_path):
    path = tmp_path / "sample.jsonl"
    path.write_text(
        '{"id":"one","input":{},"expected":{"exact":{"status":"completed"}}}\n',
        encoding="utf-8",
    )
    report = evaluate_dataset(path, lambda _: {"status": "completed"})
    assert report.pass_rate == 1.0
    assert report.to_dict()["passed"] == 1
