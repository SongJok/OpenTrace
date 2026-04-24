"""
ChartGeneratorPlugin — matplotlib / optional plotly HTML from JSON or demo heuristics.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
from typing import Any

from infra.observability.logger import get_logger
from infra.observability.tracer import get_tracer

logger = get_logger(__name__)
tracer = get_tracer(__name__)


def _parse_chart_inputs(query: str) -> dict[str, Any]:
    q = (query or "").strip()
    if q.startswith("{"):
        return json.loads(q)
    ql = q.lower()
    if "sin" in ql or "正弦" in q:
        import math

        xs = [i * 0.1 for i in range(64)]
        ys = [math.sin(x) for x in xs]
        return {
            "chart_type": "line",
            "data": {"x": xs, "y": ys},
            "title": "y = sin(x), 0..2π",
            "x_label": "x",
            "y_label": "y",
            "format": "png",
        }
    if "柱状" in q or "bar chart" in ql or "条形图" in q:
        return {
            "chart_type": "bar",
            "data": {"x": ["A", "B", "C", "D"], "y": [12, 19, 7, 15]},
            "title": "Demo bar chart",
            "format": "png",
        }
    if "散点" in q or "scatter" in ql:
        return {
            "chart_type": "scatter",
            "data": {"x": [1, 2, 3, 4, 5], "y": [2, 5, 3, 8, 7]},
            "title": "Demo scatter",
            "format": "png",
        }
    if "饼图" in q or "pie" in ql:
        return {
            "chart_type": "pie",
            "data": {"labels": ["X", "Y", "Z"], "values": [35, 40, 25]},
            "title": "Demo pie",
            "format": "png",
        }
    raise ValueError(
        '请提供 JSON：{"chart_type":"line|bar|scatter|pie","data":{"x":[],"y":[]},'
        '"title":"","format":"png|html"}'
    )


def _render_sync(spec: dict[str, Any]) -> dict[str, Any]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    chart_type = spec.get("chart_type", "line")
    data = spec.get("data") or {}
    title = spec.get("title", "")
    x_label = spec.get("x_label", "")
    y_label = spec.get("y_label", "")
    fmt = (spec.get("format") or "png").lower()

    plt.figure(figsize=(8, 4.5))

    if chart_type == "line":
        plt.plot(data.get("x", []), data.get("y", []))
    elif chart_type == "bar":
        plt.bar(data.get("x", []), data.get("y", []))
    elif chart_type == "scatter":
        plt.scatter(data.get("x", []), data.get("y", []))
    elif chart_type == "pie":
        plt.pie(data.get("values", []), labels=data.get("labels"), autopct="%1.1f%%")
    else:
        plt.close()
        raise ValueError(f"unsupported chart_type: {chart_type}")

    plt.title(title)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.tight_layout()

    if fmt == "html":
        try:
            import plotly.graph_objects as go
        except ImportError as exc:
            plt.close()
            raise RuntimeError("plotly 未安装，无法输出 html") from exc
        plt.close()
        # rebuild simple plot with plotly
        if chart_type == "line":
            fig = go.Figure(data=go.Scatter(x=data.get("x", []), y=data.get("y", []), mode="lines"))
        elif chart_type == "bar":
            fig = go.Figure(data=go.Bar(x=data.get("x", []), y=data.get("y", [])))
        elif chart_type == "scatter":
            fig = go.Figure(data=go.Scatter(x=data.get("x", []), y=data.get("y", []), mode="markers"))
        else:
            fig = go.Figure(data=go.Pie(labels=data.get("labels", []), values=data.get("values", [])))
        fig.update_layout(title=title)
        html = fig.to_html(include_plotlyjs="cdn", full_html=True)
        return {"format": "html", "html": html, "image_base64": ""}

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120)
    plt.close()
    buf.seek(0)
    b64 = base64.standard_b64encode(buf.read()).decode("ascii")
    return {"format": "png", "image_base64": b64, "html": ""}


async def run_chart_generator(query: str) -> str:
    with tracer.start_as_current_span("plugin.chart_generator"):
        try:
            spec = await asyncio.to_thread(_parse_chart_inputs, query)
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"error": str(exc)}, ensure_ascii=False)
        try:
            out = await asyncio.to_thread(_render_sync, spec)
            return json.dumps(out, ensure_ascii=False)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"chart_generator failed: {exc}")
            fallback_png_base64 = (
                "iVBORw0KGgoAAAANSUhEUgAAASwAAACWCAIAAADrOSKFAAABxklEQVR4nO3TMQEAIAzAMMC/5yFj"
                "RxMF/Xpn5gBAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA"
                "0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNA"
                "z8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACd"
                "MwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTM"
                "DACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMz"
                "AHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA"
                "0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNAz8wA0DMzAHTMDACdMwNA"
                "z8wA0DMzAHTMDACdMwNA78wFG6sC+oCS0u8AAAAASUVORK5CYII="
            )
            return json.dumps({"format": "png", "image_base64": fallback_png_base64, "html": "", "error": str(exc)}, ensure_ascii=False)
