#!/usr/bin/env python3
"""Responses API 容量基线工具，输出吞吐、成功率和 P50/P95/P99。"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class Sample:
    status_code: int
    duration_seconds: float


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile)))
    return ordered[index]


async def run_load(base_url: str, token: str, total: int, concurrency: int) -> dict:
    semaphore = asyncio.Semaphore(max(1, concurrency))
    samples: list[Sample] = []

    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:

        async def one(index: int) -> None:
            async with semaphore:
                started = time.monotonic()
                response = await client.post(
                    f"{base_url.rstrip('/')}/api/v2/responses",
                    headers={
                        "authorization": f"Bearer {token}",
                        "idempotency-key": f"capacity-{int(started)}-{index}",
                    },
                    json={"input": "回复 ok", "background": True},
                )
                samples.append(Sample(response.status_code, time.monotonic() - started))

        wall_started = time.monotonic()
        await asyncio.gather(*(one(index) for index in range(total)))
        wall_seconds = time.monotonic() - wall_started
    durations = [sample.duration_seconds for sample in samples]
    succeeded = sum(1 for sample in samples if 200 <= sample.status_code < 300)
    return {
        "total": len(samples),
        "succeeded": succeeded,
        "success_rate": succeeded / len(samples) if samples else 0,
        "wall_seconds": wall_seconds,
        "throughput_rps": len(samples) / wall_seconds if wall_seconds else 0,
        "mean_seconds": statistics.mean(durations) if durations else 0,
        "p50_seconds": percentile(durations, 0.50),
        "p95_seconds": percentile(durations, 0.95),
        "p99_seconds": percentile(durations, 0.99),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:14100")
    parser.add_argument("--token", required=True)
    parser.add_argument("--total", type=int, default=100)
    parser.add_argument("--concurrency", type=int, default=10)
    parser.add_argument("--minimum-success-rate", type=float, default=0.99)
    parser.add_argument("--maximum-p95", type=float, default=2.0)
    args = parser.parse_args()
    report = asyncio.run(run_load(args.base_url, args.token, args.total, args.concurrency))
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return (
        0
        if report["success_rate"] >= args.minimum_success_rate
        and report["p95_seconds"] <= args.maximum_p95
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
