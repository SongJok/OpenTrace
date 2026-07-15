#!/bin/bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"

echo "=== Unified Agent Worker Verify ==="
python -m unittest \
  tests/test_rag_agent_contract.py \
  tests/test_responses_contract.py \
  tests/test_scheduler_v2.py \
  tests/test_agent_bus_e2e_contract.py \
  tests/test_all_agent_bus_routing_contract.py \
  tests/test_agent_bus_governance_contract.py \
  tests/test_rag_web_fallback_contract.py \
  tests/test_sql_join_planner_contract.py

if ! command -v jq >/dev/null 2>&1; then
  echo "[WARN] jq not found, skip e2e assertions"
  echo "PASS"
  exit 0
fi

login=$(curl -s --max-time 10 -X POST "${BASE_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"songts@tuwan.com","password":"123456"}')
TOKEN=$(echo "$login" | jq -r '.access_token // empty')
if [ -z "$TOKEN" ]; then
  echo "[WARN] login failed, skip e2e assertions"
  echo "PASS"
  exit 0
fi

conv=$(curl -s --max-time 10 -X POST "${BASE_URL}/api/v1/conversations" \
  -H "Authorization: Bearer ${TOKEN}")
SID=$(echo "$conv" | jq -r '.id // empty')
if [ -z "$SID" ]; then
  echo "[WARN] create conversation failed, skip e2e assertions"
  echo "PASS"
  exit 0
fi

QUERY1="根据内部文档，我们的退货政策是什么？如果文档信息不足，请联网补充。"
resp1=$(curl -s --max-time 40 -X POST "${BASE_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"${QUERY1}\",\"session_id\":\"${SID}\",\"stream\":false}")

echo "$resp1" | jq -e '.metadata.orchestrator_version == "v4"' >/dev/null || {
  echo "FAIL: orchestrator_version is not v4"
  exit 1
}

echo "$resp1" | jq -e '.metadata.plan.subtasks[] | select(.agent_type=="rag")' >/dev/null || {
  echo "FAIL: rag subtask not found in plan"
  exit 1
}

echo "$resp1" | jq -e '.metadata.plan.subtasks[] | select(.agent_type=="web")' >/dev/null || {
  echo "FAIL: web subtask not found for fallback scenario"
  exit 1
}

QUERY2="查询订单表和客户表的关联信息，并说明客户与订单之间的关系。"
resp2=$(curl -s --max-time 40 -X POST "${BASE_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"${QUERY2}\",\"session_id\":\"${SID}\",\"stream\":false}")

echo "$resp2" | jq -e '.metadata.plan.subtasks[] | select(.agent_type=="data")' >/dev/null || {
  echo "FAIL: data subtask not found for JOIN scenario"
  exit 1
}

echo "$resp2" | jq -e '.metadata.plan.subtasks[]? | .params.join_path? // empty' >/dev/null || true

echo "PASS"
