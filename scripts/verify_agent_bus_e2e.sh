#!/bin/bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"

echo "=== Agent Bus E2E Verify ==="

if ! command -v jq >/dev/null 2>&1; then
  echo "FAIL: jq is required"
  exit 1
fi

# Ensure bus mode for this check
export KERNEL_ORCHESTRATOR_VERSION="${KERNEL_ORCHESTRATOR_VERSION:-v4}"
export KERNEL_AGENT_BUS_ENABLED="${KERNEL_AGENT_BUS_ENABLED:-true}"
export KERNEL_AGENT_BUS_MODE="${KERNEL_AGENT_BUS_MODE:-stream}"

echo "bus enabled: ${KERNEL_AGENT_BUS_ENABLED}, mode: ${KERNEL_AGENT_BUS_MODE}"

login=$(curl -s --max-time 15 -X POST "${BASE_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"songts@tuwan.com","password":"123456"}')

token=$(echo "$login" | jq -r '.access_token // empty')
if [ -z "$token" ]; then
  echo "FAIL: login failed"
  exit 1
fi

conv=$(curl -s --max-time 15 -X POST "${BASE_URL}/api/v1/conversations" \
  -H "Authorization: Bearer ${token}")
sid=$(echo "$conv" | jq -r '.id // empty')
if [ -z "$sid" ]; then
  echo "FAIL: create conversation failed"
  exit 1
fi

query="根据内部文档总结关键政策，并结合历史记忆给出建议"
resp=$(curl -s --max-time 50 -X POST "${BASE_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${token}" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"${query}\",\"session_id\":\"${sid}\",\"stream\":false}")

echo "$resp" | jq -e '.metadata.orchestrator_version == "v4"' >/dev/null || {
  echo "FAIL: orchestrator_version != v4"
  exit 1
}

echo "$resp" | jq -e '.metadata.plan.subtasks | length >= 1' >/dev/null || {
  echo "FAIL: no subtasks"
  exit 1
}

# We require at least one rag or data task in plan to validate bus path usage.
echo "$resp" | jq -e '.metadata.plan.subtasks[] | select(.agent_type=="rag" or .agent_type=="data")' >/dev/null || {
  echo "FAIL: no rag/data subtask found for bus path"
  exit 1
}

echo "$resp" | jq -e '.metadata.agent_results | length >= 1' >/dev/null || {
  echo "FAIL: no agent_results"
  exit 1
}

echo "PASS"
