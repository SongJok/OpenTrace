#!/usr/bin/env bash
# OpenTrace 当前主链路验收：登录 → 会话 → Responses → 历史 → 文档 → UI 设置。
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"
PYTHON_BIN="${PYTHON_BIN:-python}"
VERIFY_EMAIL="${VERIFY_EMAIL:-dev@example.com}"
VERIFY_PASSWORD="${VERIFY_PASSWORD:-opentrace123}"

json_get() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import json
import sys

value = json.loads(sys.argv[1])
for part in sys.argv[2].split("."):
    value = value.get(part) if isinstance(value, dict) else None
print("" if value is None else value)
PY
}

assert_json() {
  "$PYTHON_BIN" - "$1" "$2" <<'PY'
import json
import sys

name, raw = sys.argv[1:]
try:
    json.loads(raw)
except Exception as exc:
    raise SystemExit(f"[FAIL] {name}: 非 JSON 响应 {raw[:200]!r}: {exc}")
print(f"[PASS] {name}")
PY
}

echo "== OpenTrace Responses E2E =="
health=$(curl -fsS --max-time 10 "${BASE_URL}/api/v1/health")
assert_json health "$health"

login_payload=$("$PYTHON_BIN" - "$VERIFY_EMAIL" "$VERIFY_PASSWORD" <<'PY'
import json, sys
print(json.dumps({"email": sys.argv[1], "password": sys.argv[2]}))
PY
)
login=$(curl -fsS --max-time 15 -X POST "${BASE_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" -d "$login_payload")
TOKEN=$(json_get "$login" access_token)
[ -n "$TOKEN" ] || { echo "[FAIL] login: access_token 为空"; exit 1; }
echo "[PASS] login"

conversation=$(curl -fsS --max-time 15 -X POST "${BASE_URL}/api/v2/conversations" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" -d '{}')
SID=$(json_get "$conversation" id)
[ -n "$SID" ] || { echo "[FAIL] conversation: id 为空"; exit 1; }
echo "[PASS] conversation"

response=$(curl -fsS --max-time 150 -X POST "${BASE_URL}/api/v2/responses" \
  -H "Authorization: Bearer ${TOKEN}" -H "Content-Type: application/json" \
  -d "{\"input\":\"请只回复：主链路测试通过\",\"conversation\":\"${SID}\",\"stream\":false}")
assert_json response "$response"
status=$(json_get "$response" status)
output_text=$(json_get "$response" output_text)
[ "$status" = "completed" ] || { echo "[FAIL] response: status=${status}"; exit 1; }
[ -n "$output_text" ] || { echo "[FAIL] response: output_text 为空"; exit 1; }
echo "[PASS] Responses API"

messages=$(curl -fsS --max-time 20 "${BASE_URL}/api/v2/conversations/${SID}/messages" \
  -H "Authorization: Bearer ${TOKEN}")
"$PYTHON_BIN" - "$messages" <<'PY'
import json, sys
rows = json.loads(sys.argv[1])
roles = {row.get("role") for row in rows if str(row.get("content") or "").strip()}
if not {"user", "assistant"}.issubset(roles):
    raise SystemExit(f"[FAIL] history: roles={sorted(roles)}")
print("[PASS] Responses 历史投影")
PY

tmp_file=$(mktemp "${TMPDIR:-/tmp}/opentrace-doc-XXXXXX.txt")
delete_body=$(mktemp "${TMPDIR:-/tmp}/opentrace-doc-delete-XXXXXX.json")
trap 'rm -f "$tmp_file" "$delete_body"' EXIT
printf 'OpenTrace main path document test %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$tmp_file"
existing_documents=$(curl -fsS --max-time 20 "${BASE_URL}/api/v1/documents" \
  -H "Authorization: Bearer ${TOKEN}")
DOC_ID=$("$PYTHON_BIN" - "$existing_documents" <<'PY'
import json, sys
rows = json.loads(sys.argv[1])
print(next((str(row.get("id") or "") for row in rows if row.get("title") == "e2e-doc"), ""))
PY
)
if [ -n "$DOC_ID" ]; then
  upload=$(curl -fsS --max-time 60 -X PUT "${BASE_URL}/api/v1/documents/${DOC_ID}" \
    -H "Authorization: Bearer ${TOKEN}" -F "file=@${tmp_file};type=text/plain" -F "title=e2e-doc")
else
  upload=$(curl -fsS --max-time 60 -X POST "${BASE_URL}/api/v1/documents" \
    -H "Authorization: Bearer ${TOKEN}" -F "file=@${tmp_file};type=text/plain" -F "title=e2e-doc")
  DOC_ID=$(json_get "$upload" id)
fi
[ -n "$DOC_ID" ] || { echo "[FAIL] document: id 为空"; exit 1; }
curl -fsS --max-time 20 "${BASE_URL}/api/v1/documents" \
  -H "Authorization: Bearer ${TOKEN}" >/dev/null
delete_status=$(curl -sS --max-time 20 -o "$delete_body" -w '%{http_code}' \
  -X DELETE "${BASE_URL}/api/v1/documents/${DOC_ID}" \
  -H "Authorization: Bearer ${TOKEN}")
if [ "$delete_status" = "200" ]; then
  echo "[PASS] 文档上传/更新、列表与清理"
elif [ "$delete_status" = "409" ]; then
  "$PYTHON_BIN" - "$delete_body" <<'PY'
import json, pathlib, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
if "治理" not in str(payload.get("message") or ""):
    raise SystemExit(f"[FAIL] document delete protection: {payload}")
print("[PASS] 文档上传/更新、列表与治理删除保护")
PY
else
  echo "[FAIL] document delete: HTTP $delete_status $(cat "$delete_body")"
  exit 1
fi

ui=$(curl -fsS --max-time 20 "${BASE_URL}/api/v1/users/ui-settings" \
  -H "Authorization: Bearer ${TOKEN}")
"$PYTHON_BIN" - "$ui" <<'PY'
import json, sys
value = json.loads(sys.argv[1])
for key in ("reasoning_default_expanded", "graph_default_expanded"):
    if not isinstance(value.get(key), bool):
        raise SystemExit(f"[FAIL] ui_settings: {key} 缺失或类型错误")
print("[PASS] UI 设置")
PY

deleted=$(curl -fsS --max-time 20 -X DELETE "${BASE_URL}/api/v2/conversations/${SID}" \
  -H "Authorization: Bearer ${TOKEN}")
[ "$(json_get "$deleted" deleted)" = "True" ] || { echo "[FAIL] conversation cleanup"; exit 1; }
echo "[PASS] 会话级联清理"

echo "✅ E2E 验收通过：文档与 Responses 主链路均可达"
