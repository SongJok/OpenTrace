#!/usr/bin/env python3
"""运行 OpenTrace Golden Dataset。

默认 fixture 模式用于验证评测合同；生产评测通过 --results-dir 读取每个 case 的主路径输出。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.runner import EvaluationCase, evaluate_suite  # noqa: E402

DATASETS = ROOT / "evals" / "datasets"


def _fixture_executor(case: EvaluationCase) -> dict[str, Any]:
    expected = case.expected
    actual: dict[str, Any] = {}
    for key, value in dict(expected.get("exact") or {}).items():
        target = actual
        parts = key.split(".")
        for part in parts[:-1]:
            target = target.setdefault(part, {})
        target[parts[-1]] = value
    for key, values in dict(expected.get("contains") or {}).items():
        value = values[0] if isinstance(values, list) else values
        actual[key] = f"fixture:{value}"
    for key, value in dict(expected.get("at_least") or {}).items():
        actual[key] = value
    for key, value in dict(expected.get("at_most") or {}).items():
        actual[key] = value
    return actual


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-dir", type=Path)
    parser.add_argument("--minimum-pass-rate", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = sorted(DATASETS.glob("*.jsonl"))

    if args.results_dir:

        def executor(case: EvaluationCase) -> dict[str, Any]:
            path = args.results_dir / f"{case.case_id}.json"
            if not path.exists():
                return {}
            return dict(json.loads(path.read_text(encoding="utf-8")))

    else:
        executor = _fixture_executor

    reports = evaluate_suite(paths, executor)
    payload = {"reports": [report.to_dict() for report in reports]}
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0 if all(report.pass_rate >= args.minimum_pass_rate for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
