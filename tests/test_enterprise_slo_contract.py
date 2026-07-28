from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_response_sli_metrics_exist_without_high_cardinality_labels():
    from infra.observability import metrics

    for name in (
        "RESPONSE_COMPLETED_TOTAL",
        "RESPONSE_END_TO_END_DURATION",
        "RESPONSE_FIRST_EVENT_DURATION",
        "RESPONSE_QUEUE_DEPTH",
        "RESPONSE_OUTBOX_PENDING",
        "RESPONSE_LEASE_RECOVERY_TOTAL",
        "RESPONSE_RECONCILIATION_TOTAL",
    ):
        assert getattr(metrics, name) is not None
    source = (ROOT / "infra" / "observability" / "metrics.py").read_text(encoding="utf-8")
    response_metric_source = source[source.index("# Responses v2 durable execution SLI metrics") :]
    assert '"user_id"' not in response_metric_source
    assert '"response_id"' not in response_metric_source


def test_prometheus_has_rules_and_api_scrape_target():
    config = (ROOT / "deploy" / "docker" / "prometheus.yml").read_text(encoding="utf-8")
    rules = (ROOT / "deploy" / "observability" / "prometheus-rules.yml").read_text(encoding="utf-8")
    assert "/api/v1/metrics/prometheus" in config
    assert "prometheus-rules.yml" in config
    assert "OpenTraceResponseAvailabilityBurnRate" in rules
    assert "OpenTraceResponseQueueBacklog" in rules
