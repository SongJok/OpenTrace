#!/usr/bin/env python3
"""检查公开仓库中常见的敏感信息、配置和本地产物问题。"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_EXAMPLE = ROOT / ".env.example"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_FILES = {
    "README.md",
    "LICENSE",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    ".env.example",
}

FORBIDDEN_FILES = {
    ".env",
    "CLAUDE.md",
    "KB_ORCHESTRATION_COMPLETE.md",
    "SUMMARY.md",
    "docs/qa_flow_whoami.md",
    "package-lock.json",
    "scripts/apply_provided_schema_to_docker.sh",
    "scripts/sql/provided_schema.sql",
    "start-local.sh",
}
FORBIDDEN_PREFIXES = (
    ".runtime/",
    ".tmp/",
    ".trae/",
    ".claude/",
    ".idea/",
    ".vscode/",
    "frontend/dist/",
    "frontend/node_modules/",
)

# 这两个值仅用于开箱即用的本地开发，不得用于托管环境。
ALLOWED_DEVELOPMENT_PASSWORDS = {
    "POSTGRES_PASSWORD": "opentrace-dev",
    "DEV_SEED_USER_PASSWORD": "opentrace123",
}

SENSITIVE_KEY = re.compile(
    r"(?:API_KEY|SECRET|TOKEN|PASSWORD|PASSWD|SMTP_PASS|PRIVATE_KEY)$", re.IGNORECASE
)
SECRET_SIGNATURES = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "GitHub token": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "JWT": re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
    "internal account or domain": re.compile(r"(?:song" r"ts@|@tu" r"wan\.com\b)", re.IGNORECASE),
}

# 安全过滤单元测试需要模拟 key 形态；这些文件中的匹配不是可用凭据。
SIGNATURE_FIXTURE_FILES = {
    "tests/test_cognitive_core.py",
    "tests/test_memory_constitution.py",
}


def tracked_files() -> list[str]:
    output = subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        text=False,
    ).decode("utf-8")
    return [item for item in output.split("\0") if item and (ROOT / item).is_file()]


def parse_env(path: Path) -> tuple[dict[str, str], list[str]]:
    values: dict[str, str] = {}
    duplicates: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            continue
        if key in values:
            duplicates.append(key)
        values[key] = value.strip().strip('"').strip("'")
    return values, duplicates


def scan_text_signatures(files: list[str]) -> list[str]:
    errors: list[str] = []
    for relative in files:
        if relative in SIGNATURE_FIXTURE_FILES:
            continue
        path = ROOT / relative
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_SIGNATURES.items():
            if pattern.search(text):
                errors.append(f"{relative}: possible {label}")
    return errors


def dependency_name(requirement: str) -> str:
    """提取 PEP 508 依赖名，用于校验两份运行时依赖清单没有漂移。"""
    name = re.split(r"[<>=!~;\[]", requirement.strip(), maxsplit=1)[0]
    return name.strip().lower().replace("_", "-")


def validate_runtime_dependencies() -> list[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project_requirements = {
        dependency_name(item) for item in pyproject["project"].get("dependencies", [])
    }
    requirements_file = {
        dependency_name(line)
        for line in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "-"))
    }
    errors: list[str] = []
    for name in sorted(project_requirements - requirements_file):
        errors.append(f"runtime dependency missing from requirements.txt: {name}")
    for name in sorted(requirements_file - project_requirements):
        errors.append(f"runtime dependency missing from pyproject.toml: {name}")
    return errors


def main() -> int:
    errors: list[str] = []
    files = tracked_files()
    tracked = set(files)

    for required in sorted(REQUIRED_FILES - tracked):
        errors.append(f"missing public project file: {required}")
    for relative in sorted(tracked & FORBIDDEN_FILES):
        errors.append(f"forbidden tracked local file: {relative}")
    for relative in files:
        if relative.startswith(FORBIDDEN_PREFIXES):
            errors.append(f"forbidden tracked local path: {relative}")
        if relative.lower().endswith((".pem", ".key", ".p12", ".pfx")):
            errors.append(f"forbidden tracked credential file: {relative}")

    if not ENV_EXAMPLE.exists():
        errors.append(".env.example is missing")
    else:
        env_values, duplicates = parse_env(ENV_EXAMPLE)
        for key in sorted(set(duplicates)):
            errors.append(f"duplicate .env.example key: {key}")
        for key, value in env_values.items():
            if not SENSITIVE_KEY.search(key):
                continue
            allowed = ALLOWED_DEVELOPMENT_PASSWORDS.get(key)
            if value and value != allowed:
                errors.append(f"sensitive .env.example value must be blank: {key}")

        try:
            from infra.config.flag_registry import registry_env_keys

            for key in sorted(registry_env_keys() - set(env_values)):
                errors.append(f"registry flag missing from .env.example: {key}")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"unable to validate flag registry: {exc}")

    errors.extend(scan_text_signatures(files))
    errors.extend(validate_runtime_dependencies())

    if errors:
        print("=== Public release check failed ===", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print(f"=== Public release check OK ({len(files)} tracked files) ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
