"""
DataAnalysisPlugin — pandas describe / aggregate / simple clean on JSON or CSV text.
"""
from __future__ import annotations

import asyncio
import io
import json
from typing import Any

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


def _run_sync(query: str) -> dict[str, Any]:
    import pandas as pd

    q = (query or "").strip()
    if not q.startswith("{"):
        return {
            "error": "expected JSON",
            "hint": '{"operation":"describe|aggregate|clean","data":"<csv or json records>","group_by":"","agg":{}}',
        }
    spec = json.loads(q)
    op = spec.get("operation", "describe")
    raw = spec.get("data", "")
    if isinstance(raw, list):
        df = pd.DataFrame(raw)
    elif isinstance(raw, str):
        df = pd.read_csv(io.StringIO(raw))
    else:
        return {"error": "data must be csv string or list of records"}

    if op == "describe":
        return {"operation": op, "result": df.describe(include="all").to_dict()}
    if op == "aggregate":
        g = spec.get("group_by")
        agg = spec.get("agg") or {}
        if not g or not agg:
            return {"error": "aggregate requires group_by and agg dict"}
        out = df.groupby(g).agg(agg)
        return {"operation": op, "result": out.reset_index().to_dict(orient="records")}
    if op == "clean":
        df2 = df.dropna(how="all").drop_duplicates()
        return {
            "operation": op,
            "rows_before": len(df),
            "rows_after": len(df2),
            "preview": df2.head(50).to_csv(index=False),
        }
    return {"error": f"unknown operation: {op}"}


def _fallback_describe_csv(query: str) -> dict[str, Any]:
    q = (query or "").strip()
    if not q.startswith("{"):
        return {"error": "expected JSON"}
    spec = json.loads(q)
    if spec.get("operation", "describe") != "describe":
        return {"error": "fallback only supports describe"}
    raw = spec.get("data", "")
    if not isinstance(raw, str) or not raw.strip():
        return {"error": "data must be non-empty csv string"}
    lines = [line for line in raw.splitlines() if line.strip()]
    if len(lines) < 2:
        return {"operation": "describe", "result": {"rows": 0, "columns": []}}
    headers = [h.strip() for h in lines[0].split(",")]
    rows = [ln.split(",") for ln in lines[1:]]
    return {
        "operation": "describe",
        "result": {
            "rows": len(rows),
            "columns": headers,
            "non_empty": {h: sum(1 for r in rows if i < len(r) and str(r[i]).strip() != "") for i, h in enumerate(headers)},
        },
        "fallback": True,
    }


async def run_data_analysis(query: str) -> str:
    with tracer.start_as_current_span("plugin.data_analysis"):
        try:
            out = await asyncio.to_thread(_run_sync, query)
            return json.dumps(out, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"data_analysis failed: {exc}")
            fallback = _fallback_describe_csv(query)
            if "error" not in fallback:
                return json.dumps(fallback, ensure_ascii=False, default=str)
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
