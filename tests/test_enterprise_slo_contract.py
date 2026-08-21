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
        "RESPONSE_APPROVAL_DECISIONS_TOTAL",
        "RESPONSE_APPROVAL_RESOLUTION_DURATION",
        "RESPONSE_APPROVAL_PENDING",
        "RESPONSE_APPROVAL_OLDEST_AGE",
        "RAG_RETRIEVAL_TOTAL",
        "RAG_RETRIEVAL_DURATION",
        "RAG_LANE_REQUESTS_TOTAL",
        "RAG_LANE_DURATION",
        "RAG_EVIDENCE_COUNT",
        "RAG_MAX_SCORE",
        "RAG_ANCHOR_SCORE",
        "DATA_AGENT_RECONCILIATION_TOTAL",
        "CONNECTOR_EXECUTIONS_TOTAL",
        "CONNECTOR_EXECUTION_DURATION",
        "CONNECTOR_RUNTIME_DECISIONS_TOTAL",
        "PRODUCTION_EVIDENCE_CRITIC_TOTAL",
        "PRODUCTION_ASSET_SYNC_TOTAL",
        "PRODUCTION_ASSET_SYNC_DURATION",
    ):
        assert getattr(metrics, name) is not None
    source = (ROOT / "infra" / "observability" / "metrics.py").read_text(encoding="utf-8")
    response_metric_source = source[source.index("# Responses v2 durable execution SLI metrics") :]
    assert '"user_id"' not in response_metric_source
    assert '"response_id"' not in response_metric_source


def test_rag_and_data_agent_sli_metrics_are_wired_to_online_paths():
    rag_source = (ROOT / "agents" / "rag_agent.py").read_text(encoding="utf-8")
    sql_source = (ROOT / "services" / "sql_assets.py").read_text(encoding="utf-8")
    runner_source = (ROOT / "kernel" / "agent_loop" / "runner.py").read_text(encoding="utf-8")

    assert "RAG_RETRIEVAL_TOTAL.labels" in rag_source
    assert "RAG_RETRIEVAL_DURATION.labels" in rag_source
    assert "RAG_LANE_REQUESTS_TOTAL.labels" in rag_source
    assert "RAG_LANE_DURATION.labels" in rag_source
    assert "DATA_AGENT_RECONCILIATION_TOTAL.labels" in sql_source
    assert "RESPONSE_RECONCILIATION_TOTAL.labels" in runner_source
    assert "RESPONSE_TOOL_EXECUTIONS_TOTAL.labels" in runner_source


def test_prometheus_has_rules_and_api_scrape_target():
    config = (ROOT / "deploy" / "docker" / "prometheus.yml").read_text(encoding="utf-8")
    rules = (ROOT / "deploy" / "observability" / "prometheus-rules.yml").read_text(encoding="utf-8")
    assert "/api/v1/metrics/prometheus" in config
    assert "prometheus-rules.yml" in config
    assert "OpenTraceResponseAvailabilityBurnRate" in rules
    assert "OpenTraceResponseQueueBacklog" in rules
    assert "OpenTraceRagErrorRateHigh" in rules
    assert "OpenTraceRagLatencyHigh" in rules
    assert "OpenTraceRagLaneTimeoutRateHigh" in rules
    assert "OpenTraceDataAgentReconciliationRequired" in rules
    assert "OpenTraceConnectorRuntimeControlUnavailable" in rules
    assert "OpenTraceConnectorCircuitOpen" in rules
    assert "OpenTraceProductionAssetSyncFailed" in rules
    assert "OpenTraceProductionActionReconciliationRequired" in rules
    assert "OpenTraceFourEyeApprovalBacklog" in rules
    assert "OpenTraceFourEyeApprovalStalled" in rules
