#!/bin/bash
# =============================================================================
# OpenTrace — 端到端验收脚本（登录/会话/聊天/历史/文档/UI设置）
# 用法: bash scripts/verify_e2e.sh
# 可选: BASE_URL=http://127.0.0.1:14100 bash scripts/verify_e2e.sh
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"

py_get() {
  local json="$1"
  local key="$2"
  /opt/anaconda3/bin/python - "$json" "$key" <<'PY'
import json
import sys
obj = json.loads(sys.argv[1])
key = sys.argv[2]
value = obj
for part in key.split('.'):
    if isinstance(value, dict):
      value = value.get(part)
    else:
      value = None
      break
print('' if value is None else value)
PY
}

assert_json() {
  local name="$1"
  local raw="$2"
  /opt/anaconda3/bin/python - "$name" "$raw" <<'PY'
import json
import sys
name = sys.argv[1]
raw = sys.argv[2]
try:
    json.loads(raw)
except Exception:
    print(f"[FAIL] {name}: 非 JSON 响应 -> {raw[:200]}")
    raise SystemExit(1)
print(f"[PASS] {name}: JSON 有效")
PY
}

assert_messages_non_empty() {
  local raw="$1"
  /opt/anaconda3/bin/python - "$raw" <<'PY'
import json
import sys
arr = json.loads(sys.argv[1])
if not isinstance(arr, list) or len(arr) < 2:
    print(f"[FAIL] messages: 期望至少2条消息，实际={len(arr) if isinstance(arr, list) else 'N/A'}")
    raise SystemExit(1)
user = any((m.get('role') == 'user' and (m.get('content') or '').strip()) for m in arr)
assistant = any((m.get('role') == 'assistant' and (m.get('content') or '').strip()) for m in arr)
if not user or not assistant:
    print(f"[FAIL] messages: 缺少有效 user/assistant 消息")
    raise SystemExit(1)
print("[PASS] messages: user/assistant 历史完整")
PY
}

assert_ui_settings_consistent() {
  local raw="$1"
  /opt/anaconda3/bin/python - "$raw" <<'PY'
import json
import sys
obj = json.loads(sys.argv[1])
if not isinstance(obj, dict):
    print("[FAIL] ui_settings: 返回不是对象")
    raise SystemExit(1)
for k in ("reasoning_default_expanded", "graph_default_expanded"):
    if k not in obj or not isinstance(obj[k], bool):
        print(f"[FAIL] ui_settings: 字段 {k} 缺失或类型错误")
        raise SystemExit(1)
print("[PASS] ui_settings: 字段完整")
PY
}

echo "== OpenTrace E2E Verify =="
echo "BASE_URL=${BASE_URL}"

# 0) Health
health=$(curl -s --max-time 10 "${BASE_URL}/api/v1/health")
assert_json "health" "$health"

# 1) Login
login=$(curl -s --max-time 10 -X POST "${BASE_URL}/api/v1/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"email":"songts@tuwan.com","password":"123456"}')
assert_json "login" "$login"
TOKEN=$(py_get "$login" "access_token")
if [ -z "$TOKEN" ]; then
  echo "[FAIL] login: access_token 为空"
  exit 1
fi
echo "[PASS] login: token_ok"

# 2) Create conversation
conv=$(curl -s --max-time 15 -X POST "${BASE_URL}/api/v1/conversations" \
  -H "Authorization: Bearer ${TOKEN}")
assert_json "create_conversation" "$conv"
SID=$(py_get "$conv" "id")
if [ -z "$SID" ]; then
  echo "[FAIL] create_conversation: session id 为空"
  exit 1
fi
echo "[PASS] create_conversation: session_id=${SID}"

# 3) Chat sync（避免SSE环境差异）
chat=$(curl -s --max-time 30 -X POST "${BASE_URL}/api/v1/chat" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{\"query\":\"请回复一句测试通过\",\"session_id\":\"${SID}\",\"stream\":false}")
assert_json "chat_sync" "$chat"
content=$(py_get "$chat" "content")
if [ -z "$content" ]; then
  echo "[FAIL] chat_sync: content 为空"
  exit 1
fi
echo "[PASS] chat_sync: content_len=${#content}"

# 4) History
messages=$(curl -s --max-time 20 "${BASE_URL}/api/v1/conversations/${SID}/messages" \
  -H "Authorization: Bearer ${TOKEN}")
assert_json "messages" "$messages"
assert_messages_non_empty "$messages"

# 5) Document upload + list
TMP_FILE=$(mktemp /tmp/opentrace-doc-XXXXXX.txt)
printf "OpenTrace document ingest test at %s\n" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > "$TMP_FILE"
upload=$(curl -s --max-time 40 -X POST "${BASE_URL}/api/v1/documents" \
  -H "Authorization: Bearer ${TOKEN}" \
  -F "file=@${TMP_FILE};type=text/plain" \
  -F "title=e2e-doc")
assert_json "upload_document" "$upload"
DOC_ID=$(py_get "$upload" "id")
DOC_STATUS=$(py_get "$upload" "status")
if [ -z "$DOC_ID" ]; then
  echo "[FAIL] upload_document: doc id 为空"
  rm -f "$TMP_FILE"
  exit 1
fi
echo "[PASS] upload_document: doc_id=${DOC_ID} status=${DOC_STATUS}"

list_docs=$(curl -s --max-time 20 "${BASE_URL}/api/v1/documents" \
  -H "Authorization: Bearer ${TOKEN}")
assert_json "list_documents" "$list_docs"

# 6) UI settings round-trip
ui0=$(curl -s --max-time 20 "${BASE_URL}/api/v1/users/ui-settings" \
  -H "Authorization: Bearer ${TOKEN}")
assert_json "ui_settings_get" "$ui0"
assert_ui_settings_consistent "$ui0"

ui_patch=$(curl -s --max-time 20 -X PATCH "${BASE_URL}/api/v1/users/ui-settings" \
  -H "Authorization: Bearer ${TOKEN}" \
  -H "Content-Type: application/json" \
  -d '{"reasoning_default_expanded":false,"graph_default_expanded":true}')
assert_json "ui_settings_patch" "$ui_patch"
assert_ui_settings_consistent "$ui_patch"

r=$(py_get "$ui_patch" "reasoning_default_expanded")
g=$(py_get "$ui_patch" "graph_default_expanded")
if [ "$r" != "False" ] || [ "$g" != "True" ]; then
  echo "[FAIL] ui_settings_patch: 返回值不匹配"
  exit 1
fi

ui1=$(curl -s --max-time 20 "${BASE_URL}/api/v1/users/ui-settings" \
  -H "Authorization: Bearer ${TOKEN}")
assert_json "ui_settings_get_after_patch" "$ui1"
r2=$(py_get "$ui1" "reasoning_default_expanded")
g2=$(py_get "$ui1" "graph_default_expanded")
if [ "$r2" != "False" ] || [ "$g2" != "True" ]; then
  echo "[FAIL] ui_settings_roundtrip: GET 与 PATCH 不一致"
  exit 1
fi
echo "[PASS] ui_settings_roundtrip: PATCH/GET 一致"

rm -f "$TMP_FILE"

echo "✅ E2E 验收通过：登录/会话/聊天/历史/文档/UI设置链路正常"
