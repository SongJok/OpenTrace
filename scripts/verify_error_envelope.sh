#!/bin/bash
# =============================================================================
# OpenTrace — 运行态错误响应统一性校验
# 用法: bash scripts/verify_error_envelope.sh
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"

check_envelope() {
  local name="$1"
  local response="$2"

  /opt/anaconda3/bin/python - "$name" "$response" <<'PY'
import json
import sys

name = sys.argv[1]
raw = sys.argv[2]

try:
    obj = json.loads(raw)
except Exception:
    print(f"[FAIL] {name}: 非 JSON 响应 -> {raw[:200]}")
    sys.exit(1)

required = ["code", "message", "details", "request_id", "timestamp"]
missing = [k for k in required if k not in obj]
if missing:
    print(f"[FAIL] {name}: 缺少字段 {missing}, body={obj}")
    sys.exit(1)

if not isinstance(obj["code"], int):
    print(f"[FAIL] {name}: code 必须是 int, got={type(obj['code']).__name__}")
    sys.exit(1)

print(f"[PASS] {name}: code={obj['code']} message={obj['message']}")
PY
}

echo "== OpenTrace error envelope runtime verify =="
echo "BASE_URL=${BASE_URL}"

# Case 1: 路由不存在 -> 404
resp_404=$(curl -s --max-time 10 "${BASE_URL}/api/v1/not-exist")
check_envelope "route_not_found" "$resp_404"

# Case 2: 登录失败 -> 认证错误
resp_login=$(curl -s --max-time 10 -X POST "${BASE_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"invalid@example.com","password":"bad"}')
check_envelope "auth_invalid_credentials" "$resp_login"

# Case 3: Chat 参数校验失败（缺 query）
resp_chat=$(curl -s --max-time 10 -X POST "${BASE_URL}/api/v1/chat" \
  -H "Content-Type: application/json" \
  -d '{"stream":false}')
check_envelope "chat_validation_error" "$resp_chat"

echo "✅ 所有错误响应结构校验通过"
