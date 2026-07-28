"""可重复、可审计的 Golden Dataset 评测运行器。

运行器本身不调用模型；它接收主路径产出的结构化结果并执行确定性断言。在线/离线
模型调用由独立适配器负责，避免评测门禁因供应商网络抖动而失去可重复性。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    category: str
    input: dict[str, Any]
    expected: dict[str, Any]
    tags: tuple[str, ...] = ()


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    passed: bool
    score: float
    failures: tuple[str, ...] = ()


@dataclass
class EvaluationReport:
    dataset: str
    results: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for result in self.results if result.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def pass_rate(self) -> float:
        return self.passed / self.total if self.total else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "passed": self.passed,
            "total": self.total,
            "pass_rate": round(self.pass_rate, 6),
            "results": [
                {
                    "case_id": result.case_id,
                    "passed": result.passed,
                    "score": result.score,
                    "failures": list(result.failures),
                }
                for result in self.results
            ],
        }


def load_dataset(path: Path) -> list[EvaluationCase]:
    cases: list[EvaluationCase] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        payload = json.loads(line)
        case_id = str(payload.get("id") or "").strip()
        if not case_id:
            raise ValueError(f"{path}:{line_number}: id 不能为空")
        cases.append(
            EvaluationCase(
                case_id=case_id,
                category=str(payload.get("category") or path.stem),
                input=dict(payload.get("input") or {}),
                expected=dict(payload.get("expected") or {}),
                tags=tuple(str(tag) for tag in payload.get("tags") or []),
            )
        )
    if not cases:
        raise ValueError(f"评测集为空: {path}")
    return cases


def _lookup(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def score_output(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[float, tuple[str, ...]]:
    """支持 exact/contains/not_contains/at_least/at_most 四类稳定断言。"""
    checks: list[tuple[bool, str]] = []
    for key, value in dict(expected.get("exact") or {}).items():
        checks.append((_lookup(actual, key) == value, f"{key} 应等于 {value!r}"))
    for key, values in dict(expected.get("contains") or {}).items():
        haystack = _lookup(actual, key)
        required = values if isinstance(values, list) else [values]
        checks.extend(
            (str(value) in str(haystack or ""), f"{key} 应包含 {value!r}") for value in required
        )
    for key, values in dict(expected.get("not_contains") or {}).items():
        haystack = _lookup(actual, key)
        forbidden = values if isinstance(values, list) else [values]
        checks.extend(
            (str(value) not in str(haystack or ""), f"{key} 不应包含 {value!r}")
            for value in forbidden
        )
    for key, value in dict(expected.get("at_least") or {}).items():
        actual_value = _lookup(actual, key)
        checks.append(
            (
                isinstance(actual_value, int | float) and actual_value >= value,
                f"{key} 应大于等于 {value!r}",
            )
        )
    for key, value in dict(expected.get("at_most") or {}).items():
        actual_value = _lookup(actual, key)
        checks.append(
            (
                isinstance(actual_value, int | float) and actual_value <= value,
                f"{key} 应小于等于 {value!r}",
            )
        )
    if not checks:
        return 0.0, ("expected 至少需要一个断言",)
    failures = tuple(message for passed, message in checks if not passed)
    return (len(checks) - len(failures)) / len(checks), failures


def evaluate_dataset(
    path: Path,
    executor: Callable[[EvaluationCase], dict[str, Any]],
) -> EvaluationReport:
    report = EvaluationReport(dataset=path.stem)
    for case in load_dataset(path):
        actual = executor(case)
        score, failures = score_output(actual, case.expected)
        report.results.append(
            CaseResult(case_id=case.case_id, passed=not failures, score=score, failures=failures)
        )
    return report


def evaluate_suite(
    paths: Iterable[Path],
    executor: Callable[[EvaluationCase], dict[str, Any]],
) -> list[EvaluationReport]:
    return [evaluate_dataset(path, executor) for path in paths]
