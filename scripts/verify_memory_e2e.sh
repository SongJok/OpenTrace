#!/usr/bin/env bash
# OpenTrace 记忆主链路验收：学习、跨会话召回、作用域隔离与清理。
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:14100}"
PYTHON_BIN="${PYTHON_BIN:-python}"
VERIFY_EMAIL="${VERIFY_EMAIL:-dev@example.com}"
VERIFY_PASSWORD="${VERIFY_PASSWORD:-opentrace123}"

"$PYTHON_BIN" - "$BASE_URL" "$VERIFY_EMAIL" "$VERIFY_PASSWORD" <<'PY'
from __future__ import annotations

import atexit
import json
import sys
import time
import urllib.error
import urllib.request
import uuid

base_url, email, password = sys.argv[1:]
token = ""
conversation_ids: list[str] = []
memory_ids: list[str] = []
project_ids: list[str] = []
original_settings: dict | None = None
original_constitution: dict | None = None
constitution_changed = False


def request(path: str, method: str = "GET", body: dict | None = None, timeout: int = 180):
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(base_url + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        raise RuntimeError(f"{method} {path}: HTTP {exc.code}: {raw}") from exc


def expect_error(path: str, body: dict) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        base_url + path,
        data=data,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as exc:
        return json.loads(exc.read().decode("utf-8"))
    raise AssertionError(f"{path} 应拒绝无效请求")


def create_conversation(**payload) -> str:
    conversation_id = request("/api/v2/conversations", "POST", payload)["id"]
    conversation_ids.append(conversation_id)
    return conversation_id


def create_memory(**payload) -> str:
    memory_id = request("/api/v2/memories", "POST", payload)["id"]
    memory_ids.append(memory_id)
    return memory_id


def wait_for_response(result: dict, *, timeout: float = 180.0) -> dict:
    response_id = result.get("id")
    assert response_id, result
    terminal_statuses = {"completed", "failed", "incomplete", "cancelled", "requires_action"}
    deadline = time.monotonic() + timeout
    while result.get("status") not in terminal_statuses and time.monotonic() < deadline:
        time.sleep(0.5)
        result = request(f"/api/v2/responses/{response_id}")
    if result.get("status") not in terminal_statuses:
        raise AssertionError(
            f"Response {response_id} 未在 {timeout:.0f}s 内完成，当前状态：{result.get('status')}"
        )
    return result


def respond(conversation_id: str, text: str, *, memory_mode: str = "enabled") -> dict:
    result = request(
        "/api/v2/responses",
        "POST",
        {
            "input": text,
            "conversation": conversation_id,
            "stream": False,
            "opentrace": {"memory_mode": memory_mode},
        },
    )
    result = wait_for_response(result)
    assert result.get("status") == "completed", result
    return result


def response_memory_ids(result: dict) -> set[str]:
    return set(result.get("metadata", {}).get("memory_ids") or [])


def memories() -> list[dict]:
    return request("/api/v2/memories")["items"]


def wait_for_memory(marker: str, *, should_exist: bool, timeout: float = 20.0) -> dict | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = next((item for item in memories() if marker in item.get("content", "")), None)
        if (found is not None) == should_exist:
            return found
        time.sleep(0.5)
    found = next((item for item in memories() if marker in item.get("content", "")), None)
    if (found is not None) != should_exist:
        expectation = "生成" if should_exist else "不生成"
        raise AssertionError(f"记忆 {marker} 应{expectation}，实际为 {found}")
    return found


def wait_for_memory_state(
    memory_id: str,
    *,
    enabled: bool,
    status: str,
    timeout: float = 20.0,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = next((item for item in memories() if item.get("id") == memory_id), None)
        if found is not None and found.get("enabled") is enabled and found.get("status") == status:
            return found
        time.sleep(0.5)
    raise AssertionError(
        f"记忆 {memory_id} 未在 {timeout:.0f}s 内变为 enabled={enabled}, status={status}"
    )


def wait_for_candidate(marker: str, *, observations: int, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        pending = request("/api/v2/memories/inbox")["items"]
        found = next((item for item in pending if marker in item.get("content", "")), None)
        if found is not None and int(found.get("observations") or 0) >= observations:
            return found
        time.sleep(0.5)
    raise AssertionError(f"记忆候选 {marker} 未在 {timeout:.0f}s 内达到 {observations} 次观察")


def cleanup() -> None:
    global constitution_changed
    if not token:
        return
    for memory_id in reversed(memory_ids):
        try:
            request(f"/api/v2/memories/{memory_id}", "DELETE", timeout=20)
        except Exception:
            pass
    for conversation_id in reversed(conversation_ids):
        try:
            request(f"/api/v2/conversations/{conversation_id}", "DELETE", timeout=20)
        except Exception:
            pass
    for project_id in reversed(project_ids):
        try:
            request(f"/api/v2/projects/{project_id}", "DELETE", timeout=20)
        except Exception:
            pass
    if original_settings is not None:
        try:
            request("/api/v2/memories/settings", "POST", original_settings, timeout=20)
        except Exception:
            pass
    if original_constitution is not None and constitution_changed:
        try:
            request(
                "/api/v1/admin/memory/constitution",
                "PUT",
                {
                    "content": original_constitution["content"],
                    "rules": original_constitution["rules"],
                },
                timeout=20,
            )
            constitution_changed = False
        except Exception:
            pass


atexit.register(cleanup)
print("== OpenTrace Memory E2E ==")
request("/api/v1/health", timeout=10)
login = request(
    "/api/v1/auth/login",
    "POST",
    {"email": email, "password": password},
    timeout=20,
)
token = login["access_token"]
original_settings = request("/api/v2/memories/settings")
original_constitution = request("/api/v1/admin/memory/constitution")
request(
    "/api/v2/memories/settings",
    "POST",
    {"memory_learning_enabled": True, "preference_learning_enabled": True},
)
suffix = uuid.uuid4().hex[:8]
print("[PASS] 登录与记忆设置")

invalid = expect_error(
    "/api/v2/memories",
    {
        "memory_type": "semantic",
        "content": "无效 Project 记忆",
        "scope_type": "project",
    },
)
assert invalid.get("code") == 1003, invalid
print("[PASS] 作用域写入校验")

user_marker = f"跨会话-{suffix}"
user_memory_id = create_memory(
    memory_type="semantic",
    kind="fact",
    memory_key=f"verify.user.{suffix}",
    content=f"我的记忆验收代号是 {user_marker}",
    scope_type="user",
)
regular = create_conversation()
recalled = respond(regular, "我的记忆验收代号是什么？")
assert user_memory_id in response_memory_ids(recalled), recalled.get("metadata")
assert user_marker in recalled.get("output_text", ""), recalled.get("output_text")
print("[PASS] 用户记忆跨会话召回")

disabled = create_conversation()
disabled_result = respond(disabled, "我的记忆验收代号是什么？", memory_mode="disabled")
assert user_memory_id not in response_memory_ids(disabled_result)
temporary = create_conversation(temporary=True)
temporary_result = respond(temporary, "我的记忆验收代号是什么？")
assert user_memory_id not in response_memory_ids(temporary_result)
print("[PASS] 禁用模式与临时会话隔离")

conversation = create_conversation()
conversation_marker = f"会话暗号-{suffix}"
conversation_memory_id = create_memory(
    memory_type="semantic",
    kind="fact",
    memory_key=f"verify.conversation.{suffix}",
    content=f"当前会话暗号是 {conversation_marker}",
    scope_type="conversation",
    scope_id=conversation,
)
same_conversation = respond(conversation, "当前会话暗号是什么？")
assert conversation_memory_id in response_memory_ids(same_conversation)
other_conversation = create_conversation()
other_result = respond(other_conversation, "当前会话暗号是什么？")
assert conversation_memory_id not in response_memory_ids(other_result)
request(f"/api/v2/conversations/{conversation}", "DELETE")
conversation_ids.remove(conversation)
assert all(item["id"] != conversation_memory_id for item in memories())
memory_ids.remove(conversation_memory_id)
print("[PASS] 会话记忆隔离与级联清理")

project = request(
    "/api/v2/projects",
    "POST",
    {"name": f"memory-e2e-{suffix}", "memory_mode": "default"},
)
project_id = project["id"]
project_ids.append(project_id)
project_conversation = create_conversation(project_id=project_id)
project_marker = f"项目暗号-{suffix}"
project_memory_id = create_memory(
    memory_type="semantic",
    kind="fact",
    memory_key=f"verify.project.{suffix}",
    content=f"当前项目暗号是 {project_marker}",
    scope_type="project",
    scope_id=project_id,
)
project_result = respond(project_conversation, "当前项目暗号是什么？")
assert project_memory_id in response_memory_ids(project_result)
general = create_conversation()
general_result = respond(general, "当前项目暗号是什么？")
assert project_memory_id not in response_memory_ids(general_result)
print("[PASS] Project 记忆隔离")

request(
    "/api/v2/memories/settings",
    "POST",
    {"memory_learning_enabled": False, "preference_learning_enabled": True},
)
learning_off_marker = f"学习关闭-{suffix}"
learning_off = create_conversation()
respond(learning_off, f"请记住：我的学习关闭测试代号是 {learning_off_marker}。")
wait_for_memory(learning_off_marker, should_exist=False, timeout=3)
print("[PASS] 记忆学习开关生效")

request(
    "/api/v2/memories/settings",
    "POST",
    {"memory_learning_enabled": True, "preference_learning_enabled": False},
)
preference_marker = f"偏好关闭-{suffix}"
preference_off = create_conversation()
respond(preference_off, f"请记住：我偏好使用 {preference_marker} 风格回答。")
wait_for_memory(preference_marker, should_exist=False, timeout=3)
print("[PASS] 偏好学习开关生效")

request(
    "/api/v2/memories/settings",
    "POST",
    {"memory_learning_enabled": True, "preference_learning_enabled": True},
)
proactive_marker = f"主动学习-{suffix}"
proactive_conversation = create_conversation()
respond(
    proactive_conversation,
    f"我的代号是 {proactive_marker}。以后我们会在不同会话里继续合作。",
)
proactive_memory = wait_for_memory(proactive_marker, should_exist=True)
assert proactive_memory is not None
assert proactive_memory.get("metadata", {}).get("learning_mode") == "proactive"
memory_ids.append(proactive_memory["id"])
proactive_recall_conversation = create_conversation()
proactive_recall = respond(proactive_recall_conversation, "我的代号是什么？")
assert proactive_memory["id"] in response_memory_ids(proactive_recall)
assert proactive_marker in proactive_recall.get("output_text", "")
print("[PASS] 无需明确指令的主动学习与跨会话召回")

reinforce_conversation = create_conversation()
respond(reinforce_conversation, f"我的代号是 {proactive_marker}。")
reinforced_rows = [item for item in memories() if proactive_marker in item.get("content", "")]
assert len(reinforced_rows) == 1, reinforced_rows
assert reinforced_rows[0]["id"] == proactive_memory["id"]
assert int(reinforced_rows[0].get("metadata", {}).get("observations") or 0) >= 2
print("[PASS] 重复观察强化同一记忆且不生成重复节点")

forget_conversation = create_conversation()
respond(forget_conversation, "请忘记我的代号。")
forgotten_memory = wait_for_memory_state(
    proactive_memory["id"],
    enabled=False,
    status="rejected",
)
assert forgotten_memory.get("metadata", {}).get("forgotten", {}).get("response_id")
forget_recall_conversation = create_conversation()
forgotten_recall = respond(forget_recall_conversation, "我的代号是什么？")
assert proactive_memory["id"] not in response_memory_ids(forgotten_recall)
print("[PASS] 具名遗忘立即停止跨会话召回且保留审计证据")

reinforcement_rules = dict(original_constitution["rules"])
reinforcement_rules["proactive_activation_observations"] = 2
request(
    "/api/v1/admin/memory/constitution",
    "PUT",
    {"content": original_constitution["content"], "rules": reinforcement_rules},
)
constitution_changed = True
reinforcement_marker = f"重复观察-{suffix}"
first_observation = create_conversation()
respond(first_observation, f"我的常用技术栈是 {reinforcement_marker}。")
wait_for_memory(reinforcement_marker, should_exist=False, timeout=3)
candidate = wait_for_candidate(reinforcement_marker, observations=1)
assert candidate["observations"] == 1
second_observation = create_conversation()
respond(second_observation, f"我的常用技术栈是 {reinforcement_marker}。")
reinforced_memory = wait_for_memory(reinforcement_marker, should_exist=True)
assert reinforced_memory is not None
assert reinforced_memory.get("metadata", {}).get("observations") == 2
memory_ids.append(reinforced_memory["id"])
request(
    "/api/v1/admin/memory/constitution",
    "PUT",
    {
        "content": original_constitution["content"],
        "rules": original_constitution["rules"],
    },
)
constitution_changed = False
print("[PASS] 主动记忆可配置为重复观察后激活")

sensitive_marker = f"敏感过滤-{suffix}"
sensitive_conversation = create_conversation()
respond(
    sensitive_conversation,
    f"我的银行卡号是 6222021234567890，备注 {sensitive_marker}。",
)
wait_for_memory(sensitive_marker, should_exist=False, timeout=3)
transient_marker = f"一次性-{suffix}"
transient_conversation = create_conversation()
respond(
    transient_conversation,
    f"今天仅这一次请用 {transient_marker} 风格回答当前问题。",
)
wait_for_memory(transient_marker, should_exist=False, timeout=3)
print("[PASS] 敏感信息与一次性请求不会持久化")

automatic_marker = f"自动记忆-{suffix}"
learning_conversation = create_conversation()
respond(
    learning_conversation,
    f"请记住：我的自动记忆验收代号是 {automatic_marker}。以后问到时直接回答。",
)
automatic_memory = wait_for_memory(automatic_marker, should_exist=True)
assert automatic_memory is not None
memory_ids.append(automatic_memory["id"])
recall_conversation = create_conversation()
automatic_recall = respond(recall_conversation, "我的自动记忆验收代号是什么？")
assert automatic_memory["id"] in response_memory_ids(automatic_recall)
assert automatic_marker in automatic_recall.get("output_text", "")
print("[PASS] 对话自动学习与新会话召回")

updated_marker = f"自动更新-{suffix}"
update_conversation = create_conversation()
respond(
    update_conversation,
    f"请记住：我的自动记忆验收代号是 {updated_marker}。以后以新代号为准。",
)
updated_memory = wait_for_memory(updated_marker, should_exist=True)
assert updated_memory is not None
memory_ids.append(updated_memory["id"])
memory_rows = {item["id"]: item for item in memories()}
assert memory_rows[automatic_memory["id"]]["status"] == "superseded"
assert memory_rows[automatic_memory["id"]]["enabled"] is False
assert updated_memory["supersedes_id"] == automatic_memory["id"]
updated_recall_conversation = create_conversation()
updated_recall = respond(updated_recall_conversation, "我的自动记忆验收代号是什么？")
assert updated_memory["id"] in response_memory_ids(updated_recall)
assert automatic_memory["id"] not in response_memory_ids(updated_recall)
assert updated_marker in updated_recall.get("output_text", "")
print("[PASS] 冲突记忆替代与旧值失效")

correction_marker = f"明确纠正-{suffix}"
correction_conversation = create_conversation()
respond(
    correction_conversation,
    f"更正一下，我的常用技术栈是 {correction_marker}。",
)
corrected_memory = wait_for_memory(correction_marker, should_exist=True)
assert corrected_memory is not None
memory_ids.append(corrected_memory["id"])
memory_rows = {item["id"]: item for item in memories()}
assert memory_rows[reinforced_memory["id"]]["status"] == "superseded"
assert memory_rows[reinforced_memory["id"]]["enabled"] is False
assert corrected_memory["supersedes_id"] == reinforced_memory["id"]
correction_recall_conversation = create_conversation()
correction_recall = respond(correction_recall_conversation, "我的常用技术栈是什么？")
assert corrected_memory["id"] in response_memory_ids(correction_recall)
assert reinforced_memory["id"] not in response_memory_ids(correction_recall)
assert correction_marker in correction_recall.get("output_text", "")
print("[PASS] 无需记住指令的明确纠正会替代旧记忆")

request(f"/api/v2/memories/{user_memory_id}", "PATCH", {"enabled": False})
disabled_memory_conversation = create_conversation()
disabled_memory_result = respond(disabled_memory_conversation, "我的记忆验收代号是什么？")
assert user_memory_id not in response_memory_ids(disabled_memory_result)
print("[PASS] 单条记忆禁用生效")

print("✅ 记忆 E2E 验收通过")
PY
