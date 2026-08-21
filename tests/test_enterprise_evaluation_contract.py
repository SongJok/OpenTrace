from __future__ import annotations

from pathlib import Path

from evals.retrieval import normalize_retrieved_ids, retrieval_quality_metrics
from evals.runner import (
    EvaluationCase,
    evaluate_dataset,
    load_dataset,
    score_output,
    score_output_details,
    validate_dataset_contracts,
)
from scripts.run_enterprise_evals import ResultDirectoryExecutor

ROOT = Path(__file__).resolve().parents[1]


def test_enterprise_golden_datasets_are_non_empty_and_uniquely_identified():
    ids: set[str] = set()
    for name in (
        "agent_loop",
        "rag",
        "data_agent",
        "memory",
        "production_intelligence",
        "production_intelligence_security",
    ):
        cases = load_dataset(ROOT / "evals" / "datasets" / f"{name}.jsonl")
        assert len(cases) >= 3
        assert not ids.intersection(case.case_id for case in cases)
        ids.update(case.case_id for case in cases)


def test_production_intelligence_dataset_covers_required_scenarios():
    cases = load_dataset(ROOT / "evals" / "datasets" / "production_intelligence.jsonl")

    assert len(cases) == 8
    assert {case.category for case in cases} == {
        "online_bug",
        "business_query",
        "config_check",
        "release_issue",
        "system_anomaly",
        "customer_service",
        "operations",
        "product",
    }
    assert all(case.tags for case in cases)


def test_production_intelligence_security_dataset_covers_fail_closed_controls():
    cases = load_dataset(ROOT / "evals" / "datasets" / "production_intelligence_security.jsonl")

    assert len(cases) >= 10
    assert {case.category for case in cases} == {
        "tenant_isolation",
        "prompt_injection",
        "evidence_freshness",
        "environment_binding",
        "causal_safety",
        "connector_ssrf",
        "approval_integrity",
        "side_effect_verification",
        "config_dry_run",
        "asset_sync_integrity",
    }
    assert all("security" in case.tags for case in cases)


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


def test_contract_validator_does_not_execute_or_synthesize_expected_output(tmp_path):
    path = tmp_path / "contract.jsonl"
    path.write_text(
        '{"id":"safe-case","category":"contract","input":{"query":"x"},'
        '"expected":{"exact":{"status":"completed"}},"tags":["contract"]}\n',
        encoding="utf-8",
    )

    assert validate_dataset_contracts([path]) == [
        {"dataset": "contract", "cases": 1, "categories": ["contract"]}
    ]


def test_real_result_executor_requires_provenance_and_never_reads_expected(tmp_path):
    case = EvaluationCase(
        case_id="real-result",
        category="contract",
        input={"query": "x"},
        expected={"exact": {"status": "completed"}},
        tags=("contract",),
    )
    result_path = tmp_path / "real-result.json"
    result_path.write_text(
        """{
  "schema_version": 1,
  "case_id": "real-result",
  "source": "responses_v2",
  "response_id": "resp_real",
  "captured_at": "2026-08-20T12:00:00+08:00",
  "output": {"status": "failed"}
}
""",
        encoding="utf-8",
    )

    actual = ResultDirectoryExecutor(tmp_path, [case])(case)
    score, failures = score_output(actual, case.expected)
    assert score == 0
    assert failures == ("status 应等于 'completed'",)


def test_retrieval_metrics_are_rank_aware_and_deduplicate_ids():
    retrieved = normalize_retrieved_ids(
        [{"id": "irrelevant"}, {"chunk_id": "relevant"}, {"id": "relevant"}]
    )
    metrics = retrieval_quality_metrics(retrieved, ["relevant", "missing"], k=3)

    assert retrieved == ["irrelevant", "relevant"]
    assert metrics["precision_at_k"] == 1 / 3
    assert metrics["recall_at_k"] == 0.5
    assert metrics["mrr_at_k"] == 0.5
    assert 0 < metrics["ndcg_at_k"] < 1
    assert metrics["irrelevant_at_k"] == 1


def test_retrieval_expectation_emits_metrics_and_fails_below_gate():
    score, failures, metrics = score_output_details(
        {"evidence": {"ids": ["irrelevant", "relevant"]}},
        {
            "retrieval": {
                "actual_key": "evidence.ids",
                "relevant_ids": ["relevant", "missing"],
                "k": 2,
                "min_recall_at_k": 1.0,
                "min_mrr_at_k": 0.5,
            }
        },
    )

    assert score == 0.5
    assert len(failures) == 1
    assert metrics["recall_at_k"] == 0.5
    assert metrics["mrr_at_k"] == 0.5


def test_evaluation_report_aggregates_retrieval_metrics(tmp_path):
    path = tmp_path / "rag.jsonl"
    path.write_text(
        '{"id":"one","input":{},"expected":{"retrieval":{"relevant_ids":["a"],'
        '"k":2,"min_recall_at_k":1.0}}}\n',
        encoding="utf-8",
    )
    report = evaluate_dataset(path, lambda _: {"retrieved_ids": ["a", "noise"]})

    assert report.pass_rate == 1.0
    assert report.metric_averages["recall_at_k"] == 1.0
    assert report.metric_averages["precision_at_k"] == 0.5
    assert report.to_dict()["results"][0]["metrics"]["mrr_at_k"] == 1.0
