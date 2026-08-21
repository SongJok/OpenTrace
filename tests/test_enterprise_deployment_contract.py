from pathlib import Path

import yaml

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
    assert "enableServiceLinks: false" in combined
    assert "hostNetwork: false" in combined
    assert "hostPID: false" in combined
    assert 'include "opentrace.image"' in combined
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
    assert 'include "opentrace.env"' not in migration
    assert "TOKEN_DB_URL" not in migration
    assert "REDIS_URL" not in migration


def test_chart_defaults_to_immutable_image_and_explicit_network_scopes():
    values = yaml.safe_load((CHART / "values.yaml").read_text(encoding="utf-8"))
    network_policy = (CHART / "templates" / "networkpolicy.yaml").read_text(encoding="utf-8")
    helpers = (CHART / "templates" / "_helpers.tpl").read_text(encoding="utf-8")
    ingress = (CHART / "templates" / "ingress.yaml").read_text(encoding="utf-8")

    assert values["image"]["tag"] != "latest"
    assert "image.digest" in helpers
    assert "production 必须配置不可变的 image.digest" in helpers
    assert "image.tag=latest" in helpers
    assert values["networkPolicy"]["externalHttpsRanges"] == []
    assert values["networkPolicy"]["ingressNamespaceSelector"]
    assert "allow-governed-traffic" in network_policy
    assert "allow-migration" in network_policy
    assert "opentrace.io/network-role: runtime" in network_policy
    assert "opentrace.io/network-role: migration" in network_policy
    assert "namespaceSelector: {}" not in network_policy
    assert "externalHttpsRanges" in network_policy
    assert "ingress.tls" in ingress


def test_release_signs_and_attests_the_pushed_image_digest():
    release = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "deploy" / "docker" / "Dockerfile").read_text(encoding="utf-8")
    health = (ROOT / "gateway" / "api_gateway" / "routers" / "health.py").read_text(
        encoding="utf-8"
    )

    assert "attestations: write" in release
    assert "artifact-metadata: write" in release
    assert "id: build" in release
    assert "provenance: mode=max" in release
    assert "actions/attest@v4" in release
    assert "subject-digest: ${{ steps.build.outputs.digest }}" in release
    assert "sigstore/cosign-installer@v4.1.2" in release
    assert "cosign sign --yes" in release
    assert "cosign verify" in release
    assert "image-ref.txt" in release
    assert "OPENTRACE_RELEASE_REVISION=${{ github.sha }}" in release
    assert "org.opencontainers.image.revision" in dockerfile
    assert 'ENV OPENTRACE_RELEASE_REVISION="${OPENTRACE_RELEASE_REVISION}"' in dockerfile
    assert "release_revision=settings.opentrace_release_revision" in health
