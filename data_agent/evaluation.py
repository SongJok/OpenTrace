"""冻结结果上的 DataAgent 评测工具。"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return round(float(value), 8)
    if isinstance(value, float):
        return round(value, 8)
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items())}
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    return value


@dataclass(frozen=True)
class ResultComparison:
    exact: bool
    expected_rows: int
    actual_rows: int
    missing_rows: int
    extra_rows: int


class ResultComparator:
    def compare(
        self, expected: list[dict[str, Any]], actual: list[dict[str, Any]]
    ) -> ResultComparison:
        expected_norm = [_normalize(row) for row in expected]
        actual_norm = [_normalize(row) for row in actual]
        expected_counts: dict[str, int] = {}
        actual_counts: dict[str, int] = {}
        import json

        for row in expected_norm:
            key = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
            expected_counts[key] = expected_counts.get(key, 0) + 1
        for row in actual_norm:
            key = json.dumps(row, ensure_ascii=False, sort_keys=True, default=str)
            actual_counts[key] = actual_counts.get(key, 0) + 1
        missing = sum(
            max(0, count - actual_counts.get(key, 0)) for key, count in expected_counts.items()
        )
        extra = sum(
            max(0, count - expected_counts.get(key, 0)) for key, count in actual_counts.items()
        )
        return ResultComparison(
            exact=missing == 0 and extra == 0,
            expected_rows=len(expected),
            actual_rows=len(actual),
            missing_rows=missing,
            extra_rows=extra,
        )


@dataclass(frozen=True)
class PlanComparison:
    matches: bool
    missing_paths: list[str]


class PlanComparator:
    """验证生成计划是否覆盖 Golden Case 规定的业务语义。"""

    def compare(self, expected: dict[str, Any], actual: dict[str, Any]) -> PlanComparison:
        missing: list[str] = []
        self._contains(actual, expected, path="$", missing=missing)
        return PlanComparison(matches=not missing, missing_paths=missing)

    def _contains(
        self,
        actual: Any,
        expected: Any,
        *,
        path: str,
        missing: list[str],
    ) -> None:
        if isinstance(expected, dict):
            if not isinstance(actual, dict):
                missing.append(path)
                return
            for key, value in expected.items():
                if key not in actual:
                    missing.append(f"{path}.{key}")
                    continue
                self._contains(actual[key], value, path=f"{path}.{key}", missing=missing)
            return
        if isinstance(expected, list):
            if not isinstance(actual, list):
                missing.append(path)
                return
            for index, expected_item in enumerate(expected):
                if not any(self._matches(actual_item, expected_item) for actual_item in actual):
                    missing.append(f"{path}[{index}]")
            return
        if _normalize(actual) != _normalize(expected):
            missing.append(path)

    def _matches(self, actual: Any, expected: Any) -> bool:
        missing: list[str] = []
        self._contains(actual, expected, path="$", missing=missing)
        return not missing
