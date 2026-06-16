"""Canonical V4 orchestrator source for contract tests (implementation lives in legacy/)."""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
V4_ORCHESTRATOR_REL = "legacy/v4/orchestrator.py"
V4_SHIM_REL = "kernel/orchestrator_v4.py"


def read_orchestrator_v4_implementation() -> str:
    return (_ROOT / V4_ORCHESTRATOR_REL).read_text(encoding="utf-8")


def read_orchestrator_v4_shim() -> str:
    return (_ROOT / V4_SHIM_REL).read_text(encoding="utf-8")