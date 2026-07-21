#!/bin/bash
# =============================================================================
# OpenTrace — 代码/图表插件离线自检（不依赖已启动的 API）
# 用法: bash scripts/verify_code_plugin.sh
# 可选: 在 start.sh 之后可另跑 E2E：BASE_URL=... TOKEN=... 段内 curl（见文末注释）
# =============================================================================
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="${PYTHON:-python3}"
if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON="python"
fi

echo "== verify_code_plugin (in-process tools) =="
echo "PYTHON=$PYTHON"

$PYTHON <<'PY'
import asyncio
import json
import sys

async def main() -> None:
    from plugins.chart.generator import run_chart_generator
    from plugins.code.interpreter import run_code_interpreter
    from plugins.data.analysis import run_data_analysis
    from plugins.file.sandbox import run_file_sandbox

    chart = await run_chart_generator("正弦曲线")
    d = json.loads(chart)
    b64 = d.get("image_base64") or ""
    assert len(b64) > 200, f"chart image_base64 too short: {len(b64)}"
    print("[PASS] chart_generator: base64 length", len(b64))

    code_out = await run_code_interpreter(
        json.dumps({"code": "print(1 + 1)"}),
        "verify-session",
    )
    c = json.loads(code_out)
    assert "2" in (c.get("stdout") or ""), c
    print("[PASS] code_interpreter: stdout contains 2")

    csv = "a,b\n1,2\n3,4\n"
    da = await run_data_analysis(
        json.dumps({"operation": "describe", "data": csv}),
    )
    dj = json.loads(da)
    assert "result" in dj, da
    print("[PASS] data_analysis: describe")

    w = await asyncio.to_thread(
        run_file_sandbox,
        json.dumps({"operation": "write", "path": "t.txt", "content": "hi"}),
        "verify-fs",
    )
    wj = json.loads(w)
    assert wj.get("ok") is True, w
    r = await asyncio.to_thread(
        run_file_sandbox,
        json.dumps({"operation": "read", "path": "t.txt"}),
        "verify-fs",
    )
    rj = json.loads(r)
    assert rj.get("content") == "hi", r
    print("[PASS] file_sandbox: write/read")

asyncio.run(main())
print("✅ verify_code_plugin 完成")
PY

# 可选：API 探测（需已登录 TOKEN）
# BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"
# curl -sS -X POST "$BASE_URL/api/v2/responses" -H "Authorization: Bearer $TOKEN" \
#   -H "Content-Type: application/json" \
#   -d '{"input":"画一个正弦曲线图表","stream":false}' | head -c 400
