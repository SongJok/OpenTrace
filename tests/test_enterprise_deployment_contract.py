from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "opentrace"


def test_helm_chart_has_enterprise_workloads_and_controls():
    required = {
        "api-deployment.yaml",
        "worker-deployment.yaml",
        "migration-job.yaml",
        "service.yaml",
        "hpa.yaml",
        "pdb.yaml",
        "networkpolicy.yaml",
        "serviceaccount.yaml",
    }
    assert required.issubset({path.name for path in (CHART / "templates").glob("*.yaml")})
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in (CHART / "templates").glob("*")
    )
    assert "runAsNonRoot: true" in combined
    assert "readOnlyRootFilesystem: true" in combined
    assert 'capabilities: {drop: ["ALL"]}' in combined
    assert "automountServiceAccountToken: false" in combined
    assert "kind: HorizontalPodAutoscaler" in combined
    assert "kind: PodDisruptionBudget" in combined
    assert "kind: NetworkPolicy" in combined


def test_chart_uses_external_secrets_and_migration_hook():
    values = (CHART / "values.yaml").read_text(encoding="utf-8")
    migration = (CHART / "templates" / "migration-job.yaml").read_text(encoding="utf-8")
    helpers = (CHART / "templates" / "_helpers.tpl").read_text(encoding="utf-8")
    assert "existingSecret" in values
    assert "secretKeyRef" in helpers
    assert "pre-install,pre-upgrade" in migration
    assert "alembic" in migration
