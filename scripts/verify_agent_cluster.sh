#!/usr/bin/env bash
# 统一 Worker 与 Responses 专家能力验收。
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"
PYTHON_BIN="${PYTHON_BIN:-python}"
VERIFY_EMAIL="${VERIFY_EMAIL:-dev@example.com}"
VERIFY_PASSWORD="${VERIFY_PASSWORD:-opentrace123}"

echo "=== Unified Agent Worker Verify ==="
"$PYTHON_BIN" -m pytest -q \
  tests/test_rag_agent_contract.py \
  tests/test_responses_contract.py \
  tests/test_scheduler_v2.py \
  tests/test_agent_bus_e2e_contract.py \
  tests/test_all_agent_bus_routing_contract.py \
  tests/test_agent_bus_governance_contract.py \
  tests/test_rag_web_fallback_contract.py \
  tests/test_sql_join_planner_contract.py

login_payload=$("$PYTHON_BIN" - "$VERIFY_EMAIL" "$VERIFY_PASSWORD" <<'PY'
import json, sys
print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))
PY
)
login=$(curl -fsS --max-time 15 -X POST "${BASE_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" -d "$login_payload")
TOKEN=$("$PYTHON_BIN" - "$login" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("access_token") or "")
PY
)
[ -n "$TOKEN" ] || { echo "FAIL: login"; exit 1; }

conversation=$(curl -fsS --max-time 15 -X POST "${BASE_URL}/api/v2/conversations" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d '{}')
SID=$("$PYTHON_BIN" - "$conversation" <<'PY'
import json, sys
print(json.loads(sys.argv[1]).get("id") or "")
PY
)
[ -n "$SID" ] || { echo "FAIL: create conversation"; exit 1; }

response=$(curl -fsS --max-time 150 -X POST "${BASE_URL}/api/v2/responses" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d "{\"input\":\"请根据已发布知识库或上传文档说明 OpenTrace 的主链路；若资料不足请明确说明。\",\"conversation\":\"${SID}\",\"stream\":false}")
"$PYTHON_BIN" - "$response" <<'PY'
import json, sys
obj = json.loads(sys.argv[1])
if obj.get("status") != "completed" or not str(obj.get("output_text") or "").strip():
    raise SystemExit(f"FAIL: response={obj}")
output = obj.get("output") or []
types = {item.get("type") for item in output}
if not {"function_call", "function_call_output", "message"}.issubset(types):
    raise SystemExit(f"FAIL: RAG 专家未完整进入 Responses 投影，types={sorted(types)}")
rag_calls = [item for item in output if item.get("type") == "function_call" and (item.get("payload") or {}).get("name") == "rag"]
if not rag_calls:
    raise SystemExit("FAIL: Responses 输出中没有 rag function_call")
print("PASS: Responses → RAG → Manager 最终回答链路完整")
PY
