#!/usr/bin/env python3
"""校验 OpenTrace Golden Dataset，或对真实 Responses v2 主链结果执行发布评测。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.runner import (  # noqa: E402
    EvaluationCase,
    evaluate_suite,
    load_dataset,
    validate_dataset_contracts,
)

DATASETS = ROOT / "evals" / "datasets"


def _parse_captured_at(raw_value: object, *, path: Path) -> None:
    try:
        parsed = datetime.fromisoformat(str(raw_value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path}: captured_at 必须是 RFC 3339 时间") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{path}: captured_at 必须包含时区")


class ResultDirectoryExecutor:
    """读取绑定 case、Response 和采集时间的不可歧义发布评测产物。"""

    def __init__(self, results_dir: Path, cases: list[EvaluationCase]) -> None:
        self.results_dir = results_dir
        expected = {f"{case.case_id}.json" for case in cases}
        actual = {path.name for path in results_dir.glob("*.json")}
        missing = sorted(expected - actual)
        if missing:
            raise ValueError(f"真实主链结果缺失: {', '.join(missing)}")

    def __call__(self, case: EvaluationCase) -> dict[str, Any]:
        path = self.results_dir / f"{case.case_id}.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}: 不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"{path}: 结果必须是对象")
        if payload.get("schema_version") != 1:
            raise ValueError(f"{path}: schema_version 必须为 1")
        if payload.get("case_id") != case.case_id:
            raise ValueError(f"{path}: case_id 与文件名不一致")
        if payload.get("source") != "responses_v2":
            raise ValueError(f"{path}: source 必须为 responses_v2")
        if not str(payload.get("response_id") or "").startswith("resp_"):
            raise ValueError(f"{path}: 必须绑定真实 resp_ Response ID")
        _parse_captured_at(payload.get("captured_at"), path=path)
        output = payload.get("output")
        if not isinstance(output, dict):
            raise ValueError(f"{path}: output 必须是主链结构化结果对象")
        return dict(output)


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--validate-contracts",
        action="store_true",
        help="只验证数据集结构；不执行 case，也不报告通过率",
    )
    mode.add_argument("--results-dir", type=Path, help="真实 Responses v2 主链结果目录")
    parser.add_argument(
        "--require-results",
        action="store_true",
        help="兼容发布脚本的显式声明；使用 --results-dir 时结果始终为必需",
    )
    parser.add_argument("--minimum-pass-rate", type=float)
    parser.add_argument(
        "--minimum-metric",
        action="append",
        default=[],
        metavar="DATASET.METRIC=VALUE",
        help="按数据集指标均值设置发布门槛，可重复使用",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.require_results and args.results_dir is None:
        parser.error("--require-results 必须与 --results-dir 一起使用")
    if args.results_dir and not args.results_dir.is_dir():
        parser.error(f"结果目录不存在: {args.results_dir}")
    paths = sorted(DATASETS.glob("*.jsonl"))
    try:
        contract_summaries = validate_dataset_contracts(paths)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    if args.validate_contracts:
        if args.minimum_pass_rate is not None or args.minimum_metric:
            parser.error("合同校验模式不接受通过率或质量指标门槛")
        payload = {
            "mode": "contract_validation",
            "valid": True,
            "total_cases": sum(item["cases"] for item in contract_summaries),
            "datasets": contract_summaries,
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(text, encoding="utf-8")
        print(text, end="")
        return 0

    cases = [case for path in paths for case in load_dataset(path)]
    try:
        executor = ResultDirectoryExecutor(args.results_dir, cases)
        reports = evaluate_suite(paths, executor)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    metric_gates: list[dict[str, Any]] = []
    reports_by_name = {report.dataset: report for report in reports}
    for raw_gate in args.minimum_metric:
        target, separator, raw_value = str(raw_gate).partition("=")
        dataset_and_metric = target.rsplit(".", 1)
        if not separator or len(dataset_and_metric) != 2:
            parser.error("--minimum-metric 格式必须为 DATASET.METRIC=VALUE")
        dataset, metric = dataset_and_metric
        try:
            minimum = float(raw_value)
        except ValueError:
            parser.error("--minimum-metric 的 VALUE 必须是数字")
        report = reports_by_name.get(dataset)
        actual = report.metric_averages.get(metric) if report is not None else None
        passed = actual is not None and actual >= minimum
        metric_gates.append(
            {
                "dataset": dataset,
                "metric": metric,
                "minimum": minimum,
                "actual": actual,
                "passed": passed,
            }
        )
    payload = {
        "mode": "responses_v2_results",
        "reports": [report.to_dict() for report in reports],
        "metric_gates": metric_gates,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    minimum_pass_rate = 1.0 if args.minimum_pass_rate is None else args.minimum_pass_rate
    if not 0 <= minimum_pass_rate <= 1:
        parser.error("--minimum-pass-rate 必须在 0..1 之间")
    pass_rate_ok = all(report.pass_rate >= minimum_pass_rate for report in reports)
    metrics_ok = all(gate["passed"] for gate in metric_gates)
    return 0 if pass_rate_ok and metrics_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
