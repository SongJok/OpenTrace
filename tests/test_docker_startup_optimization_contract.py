from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_backend_build_context_excludes_large_local_artifacts():
    dockerignore = _read(".dockerignore")

    for entry in (
        ".venv",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "frontend",
        "node_modules",
        ".git",
        ".env",
        "**/._*",
        "**/__MACOSX",
    ):
        assert entry in dockerignore


def test_api_and_worker_share_one_application_image_and_base():
    compose = _read("docker-compose.yml")

    assert "x-opentrace-build: &opentrace-build" in compose
    assert compose.count("image: ${OPENTRACE_IMAGE:-opentrace-app:local}") == 2
    assert "python:3.11-bookworm" not in compose
    assert compose.count("build: *opentrace-build") == 2


def test_normal_start_reuses_image_and_build_is_explicit():
    docker_up = _read("scripts/docker_up.sh")

    assert 'BUILD_MODE="auto"' in docker_up
    assert "source_fingerprint()" in docker_up
    assert "org.opentrace.build-fingerprint" in docker_up
    assert '"${COMPOSE_CMD[@]}" up -d --no-build' in docker_up
    assert "up -d --build" not in docker_up
    assert "--rebuild" in docker_up
    assert "--no-cache" in docker_up


def test_dockerfile_uses_buildkit_dependency_caches_without_remote_frontend():
    dockerfile = _read("deploy/docker/Dockerfile")

    assert 'LABEL org.opentrace.build-fingerprint="${OPENTRACE_BUILD_FINGERPRINT}"' in dockerfile
    assert "--mount=type=cache,target=/root/.cache/pip" in dockerfile
    assert "apt-get" not in dockerfile
    assert "build-essential" not in dockerfile
    assert "libpq-dev" not in dockerfile
    assert "urllib.request.urlopen" in dockerfile
    assert "PIP_INDEX_URL" in dockerfile
    assert "pip install --prefer-binary" in dockerfile
    assert "# syntax=" not in dockerfile


def test_linux_arm64_uses_available_asyncmy_wheel():
    requirements = _read("requirements.txt")

    assert 'asyncmy==0.2.9; platform_system == "Linux" and platform_machine == "aarch64"' in requirements
