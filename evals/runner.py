"""可重复、可审计的 Golden Dataset 评测运行器。

运行器本身不调用模型；它接收主路径产出的结构化结果并执行确定性断言。在线/离线
模型调用由独立适配器负责，避免评测门禁因供应商网络抖动而失去可重复性。
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evals.retrieval import normalize_retrieved_ids, retrieval_quality_metrics

SUPPORTED_EXPECTATIONS = frozenset(
    {"exact", "contains", "not_contains", "at_least", "at_most", "retrieval"}
)
_CASE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{2,127}$")


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
    metrics: dict[str, float] = field(default_factory=dict)


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

    @property
    def metric_averages(self) -> dict[str, float]:
        names = sorted({name for result in self.results for name in result.metrics})
        return {
            name: round(
                sum(result.metrics[name] for result in self.results if name in result.metrics)
                / sum(1 for result in self.results if name in result.metrics),
                6,
            )
            for name in names
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "passed": self.passed,
            "total": self.total,
            "pass_rate": round(self.pass_rate, 6),
            "metric_averages": self.metric_averages,
            "results": [
                {
                    "case_id": result.case_id,
                    "passed": result.passed,
                    "score": result.score,
                    "failures": list(result.failures),
                    "metrics": dict(result.metrics),
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


def _validate_dotted_key(key: object, *, location: str) -> None:
    value = str(key)
    if not value or value != value.strip() or any(not part for part in value.split(".")):
        raise ValueError(f"{location}: 字段路径无效: {value!r}")


def _validate_assertion_map(
    value: object,
    *,
    location: str,
    numeric: bool = False,
) -> None:
    if not isinstance(value, dict) or not value:
        raise ValueError(f"{location}: 必须是非空对象")
    for key, expected in value.items():
        _validate_dotted_key(key, location=location)
        if numeric and (
            isinstance(expected, bool)
            or not isinstance(expected, int | float)
            or not math.isfinite(float(expected))
        ):
            raise ValueError(f"{location}.{key}: 必须是有限数值")
        if not numeric and isinstance(expected, list) and not expected:
            raise ValueError(f"{location}.{key}: 断言值列表不能为空")


def _validate_retrieval(value: object, *, location: str) -> None:
    if not isinstance(value, dict):
        raise ValueError(f"{location}: 必须是对象")
    allowed = {
        "actual_key",
        "relevant_ids",
        "k",
        "min_precision_at_k",
        "min_recall_at_k",
        "min_mrr_at_k",
        "min_ndcg_at_k",
        "min_hit_rate_at_k",
        "max_irrelevant_at_k",
    }
    unsupported = sorted(set(value) - allowed)
    if unsupported:
        raise ValueError(f"{location}: 不支持的字段: {', '.join(unsupported)}")
    _validate_dotted_key(value.get("actual_key") or "retrieved_ids", location=location)
    relevant_ids = normalize_retrieved_ids(value.get("relevant_ids") or [])
    if not relevant_ids:
        raise ValueError(f"{location}.relevant_ids: 必须包含至少一个相关对象 ID")
    try:
        cutoff = int(value.get("k") or 5)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{location}.k: 必须是 1..100 的整数") from exc
    if cutoff < 1 or cutoff > 100:
        raise ValueError(f"{location}.k: 必须是 1..100 的整数")
    for key in allowed - {"actual_key", "relevant_ids", "k", "max_irrelevant_at_k"}:
        threshold = value.get(key)
        if threshold is None:
            continue
        if (
            isinstance(threshold, bool)
            or not isinstance(threshold, int | float)
            or not math.isfinite(float(threshold))
            or not 0 <= float(threshold) <= 1
        ):
            raise ValueError(f"{location}.{key}: 必须是 0..1 的有限数值")
    maximum_irrelevant = value.get("max_irrelevant_at_k")
    if maximum_irrelevant is not None and (
        isinstance(maximum_irrelevant, bool)
        or not isinstance(maximum_irrelevant, int | float)
        or not math.isfinite(float(maximum_irrelevant))
        or float(maximum_irrelevant) < 0
    ):
        raise ValueError(f"{location}.max_irrelevant_at_k: 必须是非负有限数值")


def validate_dataset_contracts(paths: Iterable[Path]) -> list[dict[str, Any]]:
    """只校验评测数据合同，不执行 case，也不产生可能误导的通过率。"""

    summaries: list[dict[str, Any]] = []
    seen_ids: dict[str, str] = {}
    for path in paths:
        cases = load_dataset(path)
        categories: set[str] = set()
        for case in cases:
            location = f"{path}:{case.case_id}"
            if not _CASE_ID_PATTERN.fullmatch(case.case_id):
                raise ValueError(f"{location}: id 必须是 3..128 位小写稳定标识")
            previous = seen_ids.get(case.case_id)
            if previous is not None:
                raise ValueError(f"{location}: id 与 {previous} 重复")
            seen_ids[case.case_id] = str(path)
            if not case.category.strip():
                raise ValueError(f"{location}: category 不能为空")
            if not case.input:
                raise ValueError(f"{location}: input 不能为空")
            if not case.tags or any(not tag.strip() for tag in case.tags):
                raise ValueError(f"{location}: tags 必须包含非空治理标签")
            unsupported = sorted(set(case.expected) - SUPPORTED_EXPECTATIONS)
            if unsupported:
                raise ValueError(f"{location}: 不支持的断言: {', '.join(unsupported)}")
            if not case.expected:
                raise ValueError(f"{location}: expected 至少需要一个断言")
            for name in ("exact", "contains", "not_contains"):
                if name in case.expected:
                    _validate_assertion_map(
                        case.expected[name], location=f"{location}.expected.{name}"
                    )
            for name in ("at_least", "at_most"):
                if name in case.expected:
                    _validate_assertion_map(
                        case.expected[name],
                        location=f"{location}.expected.{name}",
                        numeric=True,
                    )
            if "retrieval" in case.expected:
                _validate_retrieval(
                    case.expected["retrieval"], location=f"{location}.expected.retrieval"
                )
            categories.add(case.category)
        summaries.append(
            {
                "dataset": path.stem,
                "cases": len(cases),
                "categories": sorted(categories),
            }
        )
    if not summaries:
        raise ValueError("没有找到评测数据集")
    return summaries


def _lookup(payload: dict[str, Any], dotted_key: str) -> Any:
    current: Any = payload
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def score_output_details(
    actual: dict[str, Any], expected: dict[str, Any]
) -> tuple[float, tuple[str, ...], dict[str, float]]:
    """执行字段断言与 RAG 检索质量断言，并返回可聚合指标。"""

    checks: list[tuple[bool, str]] = []
    metrics: dict[str, float] = {}
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
    retrieval = expected.get("retrieval")
    if isinstance(retrieval, dict):
        actual_key = str(retrieval.get("actual_key") or "retrieved_ids")
        relevant_ids = normalize_retrieved_ids(retrieval.get("relevant_ids") or [])
        retrieved_ids = normalize_retrieved_ids(_lookup(actual, actual_key))
        cutoff = max(1, int(retrieval.get("k") or 5))
        if not relevant_ids:
            checks.append((False, "retrieval.relevant_ids 不能为空"))
        metrics = retrieval_quality_metrics(retrieved_ids, relevant_ids, k=cutoff)
        minimums = {
            "precision_at_k": retrieval.get("min_precision_at_k"),
            "recall_at_k": retrieval.get("min_recall_at_k"),
            "mrr_at_k": retrieval.get("min_mrr_at_k"),
            "ndcg_at_k": retrieval.get("min_ndcg_at_k"),
            "hit_rate_at_k": retrieval.get("min_hit_rate_at_k"),
        }
        configured_minimum = False
        for name, minimum in minimums.items():
            if minimum is None:
                continue
            configured_minimum = True
            checks.append(
                (
                    metrics[name] >= float(minimum),
                    f"retrieval.{name}@{cutoff} 应大于等于 {float(minimum):.4f}",
                )
            )
        if not configured_minimum:
            checks.append(
                (
                    metrics["recall_at_k"] >= 1.0,
                    f"retrieval.recall_at_k@{cutoff} 应大于等于 1.0000",
                )
            )
        maximum_irrelevant = retrieval.get("max_irrelevant_at_k")
        if maximum_irrelevant is not None:
            checks.append(
                (
                    metrics["irrelevant_at_k"] <= float(maximum_irrelevant),
                    (
                        f"retrieval.irrelevant_at_k@{cutoff} 应小于等于 "
                        f"{float(maximum_irrelevant):.4f}"
                    ),
                )
            )
    if not checks:
        return 0.0, ("expected 至少需要一个断言",), metrics
    failures = tuple(message for passed, message in checks if not passed)
    return (len(checks) - len(failures)) / len(checks), failures, metrics


def score_output(actual: dict[str, Any], expected: dict[str, Any]) -> tuple[float, tuple[str, ...]]:
    """兼容入口：返回断言得分和失败原因。"""

    score, failures, _ = score_output_details(actual, expected)
    return score, failures


def evaluate_dataset(
    path: Path,
    executor: Callable[[EvaluationCase], dict[str, Any]],
) -> EvaluationReport:
    report = EvaluationReport(dataset=path.stem)
    for case in load_dataset(path):
        actual = executor(case)
        score, failures, metrics = score_output_details(actual, case.expected)
        report.results.append(
            CaseResult(
                case_id=case.case_id,
                passed=not failures,
                score=score,
                failures=failures,
                metrics=metrics,
            )
        )
    return report


def evaluate_suite(
    paths: Iterable[Path],
    executor: Callable[[EvaluationCase], dict[str, Any]],
) -> list[EvaluationReport]:
    return [evaluate_dataset(path, executor) for path in paths]
