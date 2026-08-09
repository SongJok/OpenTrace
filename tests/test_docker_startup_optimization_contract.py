import os
import subprocess
from pathlib import Path

import pytest

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


def test_api_worker_and_storage_init_share_one_application_image_and_base():
    compose = _read("docker-compose.yml")

    assert "x-opentrace-build: &opentrace-build" in compose
    assert compose.count("image: ${OPENTRACE_IMAGE:-opentrace-app:local}") == 3
    assert "python:3.11-bookworm" not in compose
    assert compose.count("build: *opentrace-build") == 3


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
    assert "--mount=type=cache,target=/root/.cache/uv" in dockerfile
    assert "apt-get" not in dockerfile
    assert "build-essential" not in dockerfile
    assert "libpq-dev" not in dockerfile
    assert "urllib.request.urlopen" in dockerfile
    assert "scripts/install_uv.sh" in dockerfile
    assert "scripts/install_python_dependencies.sh" in dockerfile
    assert "PYTHON_DEPENDENCY_FALLBACK_INDEX_URL" in dockerfile
    assert "PYTHON_DEPENDENCY_HTTP_RETRIES" in dockerfile
    assert "UV_BOOTSTRAP_FALLBACK_INDEX_URL" in dockerfile
    assert "UV_BOOTSTRAP_PRIMARY_MAX_SECONDS" in dockerfile
    assert "UV_CONCURRENT_INSTALLS" in dockerfile
    assert "# syntax=" not in dockerfile


def test_uv_bootstrap_uses_one_domestic_index_at_a_time_with_bounded_fallback():
    installer = _read("scripts/install_uv.sh")

    assert 'PIP_EXTRA_INDEX_URL=""' in installer
    assert '--index-url "${index_url}"' in installer
    assert 'timeout "${max_seconds}"' in installer
    assert "UV_BOOTSTRAP_FALLBACK_INDEX_URL" in installer
    assert "pypi.org" not in installer
    assert "files.pythonhosted.org" not in installer


def test_uv_bootstrap_switches_to_fallback_after_primary_failure(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.log"

    fake_timeout = fake_bin / "timeout"
    fake_timeout.write_text('#!/bin/sh\nshift\nexec "$@"\n', encoding="utf-8")
    fake_timeout.chmod(0o755)

    fake_python = fake_bin / "python"
    fake_python.write_text(
        '#!/bin/sh\nprintf "%s|%s\\n" "${PIP_EXTRA_INDEX_URL-unset}" "$*" >> "$UV_TEST_CALLS"\n'
        'case "$*" in *primary.invalid*) exit 9 ;; esac\nexit 0\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "UV_TEST_CALLS": str(calls),
        "UV_BOOTSTRAP_INDEX_URL": "https://primary.invalid/simple",
        "UV_BOOTSTRAP_FALLBACK_INDEX_URL": "https://fallback.invalid/simple",
        "UV_BOOTSTRAP_PRIMARY_MAX_SECONDS": "1",
        "UV_BOOTSTRAP_FALLBACK_MAX_SECONDS": "1",
    }
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/install_uv.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    attempted = calls.read_text(encoding="utf-8").splitlines()
    assert len(attempted) == 2
    assert attempted[0].startswith("|")
    assert "primary.invalid" in attempted[0]
    assert attempted[1].startswith("|")
    assert "fallback.invalid" in attempted[1]


def test_python_dependencies_use_one_domestic_index_at_a_time_with_bounded_fallback():
    installer = _read("scripts/install_python_dependencies.sh")

    assert 'UV_EXTRA_INDEX_URL=""' in installer
    assert 'UV_INDEX_URL="${index_url}"' in installer
    assert 'timeout "${max_seconds}"' in installer
    assert "PYTHON_DEPENDENCY_FALLBACK_INDEX_URL" in installer
    assert "UV_CONCURRENT_DOWNLOADS" in installer
    assert "UV_CONCURRENT_INSTALLS" in installer
    assert "PYTHON_DEPENDENCY_FALLBACK_ATTEMPTS" in installer
    assert "pypi.org" not in installer
    assert "files.pythonhosted.org" not in installer


def test_python_dependencies_switch_to_fallback_after_primary_failure(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.log"

    fake_timeout = fake_bin / "timeout"
    fake_timeout.write_text('#!/bin/sh\nshift\nexec "$@"\n', encoding="utf-8")
    fake_timeout.chmod(0o755)

    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nprintf "%s|%s|%s\\n" "$UV_INDEX_URL" "${UV_EXTRA_INDEX_URL-unset}" "$*" >> "$UV_TEST_CALLS"\n'
        'case "$UV_INDEX_URL" in *primary.invalid*) exit 9 ;; esac\nexit 0\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)

    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "UV_TEST_CALLS": str(calls),
        "PYTHON_DEPENDENCY_INDEX_URL": "https://primary.invalid/simple",
        "PYTHON_DEPENDENCY_FALLBACK_INDEX_URL": "https://fallback.invalid/simple",
        "PYTHON_DEPENDENCY_PRIMARY_MAX_SECONDS": "1",
        "PYTHON_DEPENDENCY_FALLBACK_MAX_SECONDS": "1",
    }
    result = subprocess.run(
        ["sh", str(ROOT / "scripts/install_python_dependencies.sh")],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0
    attempted = calls.read_text(encoding="utf-8").splitlines()
    assert len(attempted) == 2
    assert attempted[0].startswith("https://primary.invalid/simple||")
    assert attempted[1].startswith("https://fallback.invalid/simple||")


def test_mysql_driver_is_platform_independent_and_security_maintained():
    requirements = _read("requirements.txt")

    assert "aiomysql>=0.2.0" in requirements
    assert "asyncmy" not in requirements


@pytest.mark.parametrize(
    "pid_path",
    ("/run/nginx.pid", "/var/run/nginx.pid", "/custom/runtime/nginx.pid"),
)
def test_frontend_rootless_nginx_pid_rewrite_supports_old_and_new_images(
    tmp_path: Path, pid_path: str
):
    config = tmp_path / "nginx.conf"
    config.write_text(f"user nginx;\npid {pid_path};\nevents {{}}\n", encoding="utf-8")

    subprocess.run(
        ["sh", str(ROOT / "frontend/configure-nginx-rootless.sh"), str(config)],
        check=True,
    )

    rewritten = config.read_text(encoding="utf-8")
    assert "pid /tmp/nginx.pid;" in rewritten
    assert pid_path not in rewritten


def test_frontend_rootless_nginx_pid_rewrite_fails_when_base_config_has_no_pid(tmp_path: Path):
    config = tmp_path / "nginx.conf"
    config.write_text("user nginx;\nevents {}\n", encoding="utf-8")

    result = subprocess.run(
        ["sh", str(ROOT / "frontend/configure-nginx-rootless.sh"), str(config)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "/tmp/nginx.pid" in result.stderr
