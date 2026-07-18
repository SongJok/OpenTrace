#!/usr/bin/env bash
# OpenTrace 运行态错误响应统一性校验。
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"
PYTHON_BIN="${PYTHON_BIN:-python}"
VERIFY_EMAIL="${VERIFY_EMAIL:-dev@example.com}"
VERIFY_PASSWORD="${VERIFY_PASSWORD:-opentrace123}"

check_envelope() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import json, sys
name, raw = sys.argv[1:]
obj = json.loads(raw)
required = {"code", "message", "details", "request_id", "timestamp"}
missing = sorted(required - obj.keys())
if missing or not isinstance(obj.get("code"), int):
    raise SystemExit(f"[FAIL] {name}: missing={missing}, body={obj}")
print(f"[PASS] {name}: code={obj['code']}")
PY
}

echo "== OpenTrace error envelope runtime verify =="
check_envelope route_not_found "$(curl -sS --max-time 10 "${BASE_URL}/api/v1/not-exist")"
check_envelope auth_invalid_credentials "$(curl -sS --max-time 10 -X POST \
  "${BASE_URL}/api/v1/auth/login" -H "Content-Type: application/json" \
  -d '{"email":"invalid@example.com","password":"bad"}')"

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
[ -n "$TOKEN" ] || { echo "[FAIL] login"; exit 1; }
validation=$(curl -sS --max-time 10 -X POST "${BASE_URL}/api/v2/responses" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d '{"stream":false}')
check_envelope responses_validation_error "$validation"
echo "✅ 所有错误响应结构校验通过"
