"""Agents package must not depend on API gateway routers (execution uses infra/execution)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENTS = ROOT / "agents"

_FORBIDDEN = (
    "gateway.api_gateway",
    "from gateway import",
)


def test_agents_no_gateway_api_imports():
    violations: list[str] = []
    for path in AGENTS.rglob("*.py"):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for token in _FORBIDDEN:
                if token in stripped:
                    violations.append(f"{rel}: {stripped[:140]}")
                    break
    assert not violations, "agents must not import gateway.api_gateway:\n" + "\n".join(
        violations[:30]
    )