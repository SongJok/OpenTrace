from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_worker_runs_dedicated_prometheus_endpoint():
    worker = (ROOT / "agents" / "worker.py").read_text(encoding="utf-8")
    prometheus = (ROOT / "deploy" / "docker" / "prometheus.yml").read_text(encoding="utf-8")
    helm = (
        ROOT / "deploy" / "helm" / "opentrace" / "templates" / "worker-deployment.yaml"
    ).read_text(encoding="utf-8")
    assert "start_http_server" in worker
    assert "agent-worker:9464" in prometheus
    assert 'prometheus.io/scrape: "true"' in helm
    assert "containerPort: 9464" in helm
