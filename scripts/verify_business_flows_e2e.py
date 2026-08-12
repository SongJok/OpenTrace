#!/usr/bin/env python3
"""OpenTrace 核心业务资源与跨任务链路的可重复端到端验收。"""

from __future__ import annotations

import os
import socket
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import httpx

from execution.data.database_hosts import is_docker_internal_database_host

BASE_URL = os.getenv("BASE_URL", "http://127.0.0.1:14100").rstrip("/")
EMAIL = os.getenv("VERIFY_EMAIL", "dev@example.com")
PASSWORD = os.getenv("VERIFY_PASSWORD", "opentrace123")


def _env_value(name: str, default: str = "") -> str:
    value = os.getenv(name)
    if value:
        return value
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.exists():
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            key, separator, raw_value = raw_line.partition("=")
            if separator and key.strip() == name:
                return raw_value.strip().strip("\"'")
    return default


def _database_connection() -> dict[str, Any]:
    parsed = urlparse(os.getenv("DATABASE_URL", ""))
    configured_host = os.getenv("VERIFY_DATABASE_HOST") or parsed.hostname or "host.docker.internal"
    if not os.getenv("VERIFY_DATABASE_HOST") and is_docker_internal_database_host(configured_host):
        configured_host = socket.gethostbyname(configured_host)
    return {
        "host": configured_host,
        "port": int(os.getenv("VERIFY_DATABASE_PORT") or parsed.port or 5432),
        "database": os.getenv("VERIFY_DATABASE_NAME") or parsed.path.lstrip("/") or "opentrace_v2",
        "username": os.getenv("VERIFY_DATABASE_USER")
        or (unquote(parsed.username) if parsed.username else "postgres"),
        "password": _env_value("VERIFY_DATABASE_PASSWORD")
        or (unquote(parsed.password) if parsed.password else "")
        or _env_value("POSTGRES_PASSWORD", "changeme"),
    }


class BusinessFlowVerifier:
    def __init__(self) -> None:
        self.client = httpx.Client(base_url=BASE_URL, timeout=180, trust_env=False)
        self.headers: dict[str, str] = {}
        self.conversation_ids: list[str] = []
        self.attachment_ids: list[str] = []
        self.profile_id = ""
        self.database_id = ""
        self.task_id = ""
        self.goal_id = ""
        self.response_ids: list[str] = []
        self.original_instructions: dict[str, Any] | None = None

    def request(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
        data: dict[str, str] | None = None,
        authenticated: bool = True,
        expected_status: int | None = None,
    ) -> Any:
        response = self.client.request(
            method,
            path,
            json=body,
            files=files,
            data=data,
            headers=self.headers if authenticated else None,
        )
        if expected_status is not None:
            if response.status_code != expected_status:
                raise AssertionError(
                    f"{method} {path}: 期望 HTTP {expected_status}，实际 "
                    f"{response.status_code}: {response.text[:500]}"
                )
        else:
            if not response.is_success:
                raise AssertionError(
                    f"{method} {path}: HTTP {response.status_code}: {response.text[:500]}"
                )
        if not response.content:
            return {}
        return response.json()

    @staticmethod
    def passed(name: str) -> None:
        print(f"[PASS] {name}")

    def respond(self, body: dict[str, Any], *, timeout: float = 360) -> dict[str, Any]:
        result = self.request("POST", "/api/v2/responses", body=body)
        response_id = str(result.get("id") or "")
        assert response_id, result
        self.response_ids.append(response_id)
        deadline = time.monotonic() + timeout
        while result.get("status") in {"queued", "in_progress"}:
            if time.monotonic() >= deadline:
                raise AssertionError(f"Response {response_id} 未在限定时间内完成")
            time.sleep(0.5)
            result = self.request("GET", f"/api/v2/responses/{response_id}")
        assert result.get("status") == "completed", result
        return result

    def login(self) -> None:
        health = self.request("GET", "/api/v1/health", authenticated=False)
        assert health
        result = self.request(
            "POST",
            "/api/v1/auth/login",
            body={"email": EMAIL, "password": PASSWORD},
            authenticated=False,
        )
        token = str(result.get("access_token") or "")
        assert token
        self.headers = {"Authorization": f"Bearer {token}"}
        assert self.request("GET", "/api/v1/auth/me").get("email") == EMAIL
        self.passed("健康检查、登录与当前用户")

    def personalization(self, marker: str) -> None:
        self.original_instructions = self.request(
            "GET", "/api/v2/personalization/custom-instructions"
        )
        updated = self.request(
            "PUT",
            "/api/v2/personalization/custom-instructions",
            body={
                "about_user": f"业务验收用户 {marker}",
                "response_style": "回答简洁并优先引用当前附件",
                "enabled": True,
            },
        )
        assert marker in updated["about_user"] and updated["enabled"] is True
        loaded = self.request("GET", "/api/v2/personalization/custom-instructions")
        assert loaded["about_user"] == updated["about_user"]
        self.passed("个性化指令保存与读取")

    def resources(self, marker: str) -> None:
        profile = self.request(
            "POST",
            "/api/v2/assistant-profiles",
            body={
                "name": f"验收助手-{marker}",
                "personality": "pragmatic",
                "instructions": "只使用当前工作区已授权的资源。",
                "memory_policy": {"enabled": True},
            },
        )
        self.profile_id = profile["id"]
        profile = self.request(
            "PATCH",
            f"/api/v2/assistant-profiles/{self.profile_id}",
            body={
                "name": f"验收助手更新-{marker}",
                "personality": "friendly",
                "instructions": "优先使用附件和已授权数据。",
                "memory_policy": {"enabled": True},
            },
        )
        assert profile["personality"] == "friendly"

        database_connection = _database_connection()
        database = self.request(
            "POST",
            "/api/v1/databases",
            body={
                "name": f"验收数据源-{marker}",
                "source_type": "postgres",
                **database_connection,
            },
        )
        self.database_id = database["id"]
        connection = self.request("POST", f"/api/v1/databases/{self.database_id}/test-connection")
        assert connection["ok"] is True, connection
        schema = self.request("POST", f"/api/v1/databases/{self.database_id}/sync-schema")
        assert schema["synced"] is True and schema["table_count"] > 0
        query = self.request(
            "POST",
            f"/api/v1/databases/{self.database_id}/query",
            body={
                "question": "统计当前用户表的总行数",
                "sql": "SELECT COUNT(*) AS total FROM users",
            },
        )
        assert query.get("executed") is False, query
        draft_id = str(query.get("draft_id") or "")
        candidates = query.get("candidates") or []
        assert draft_id and candidates, query
        candidate_id = str(candidates[0].get("id") or "")
        assert candidate_id, query
        executed = self.request(
            "POST",
            f"/api/v1/databases/{self.database_id}/sql-drafts/{draft_id}/execute",
            body={"candidate_ids": [candidate_id], "execute_all": False},
        )
        executed_candidates = executed.get("candidates") or []
        rows = executed_candidates[0].get("rows") if executed_candidates else []
        assert executed.get("status") == "completed" and rows and "total" in rows[0], executed

        self.passed("助手角色与工作区数据源查询")

    def conversation_flow(self, marker: str) -> None:
        conversation = self.request(
            "POST",
            "/api/v2/conversations",
            body={
                "assistant_profile_id": self.profile_id,
                "instructions": "本会话用于业务验收。",
            },
        )
        conversation_id = conversation["id"]
        self.conversation_ids.append(conversation_id)
        assert conversation["assistant_profile_id"] == self.profile_id

        cleared = self.request(
            "PATCH",
            f"/api/v2/conversations/{conversation_id}",
            body={"assistant_profile_id": None},
        )
        assert cleared["assistant_profile_id"] is None
        rebound = self.request(
            "PATCH",
            f"/api/v2/conversations/{conversation_id}",
            body={
                "title": f"业务验收会话-{marker}",
                "assistant_profile_id": self.profile_id,
                "pinned": True,
                "tags": ["e2e", "business"],
            },
        )
        assert rebound["pinned"] is True and rebound["assistant_profile_id"] == self.profile_id

        attachment = self.request(
            "POST",
            "/api/v2/files",
            files={
                "file": (
                    "business-flow.txt",
                    f"当前附件唯一验收标记：{marker}".encode(),
                    "text/plain",
                )
            },
            data={"session_id": conversation_id},
        )
        attachment_id = attachment["attachment_id"]
        self.attachment_ids.append(attachment_id)
        listed = self.request("GET", f"/api/v2/files/{conversation_id}")
        assert attachment_id in {item["id"] for item in listed["attachments"]}

        first = self.respond(
            {
                "input": "附件内的唯一验收标记是什么？只回复标记。",
                "conversation": conversation_id,
                "stream": False,
                "opentrace": {"attachment_ids": [attachment_id]},
            },
        )
        assert first["status"] == "completed" and marker in first["output_text"], first
        second_marker = f"第二轮-{marker}"
        second = self.respond(
            {
                "input": f"请只回复：{second_marker}",
                "conversation": conversation_id,
                "stream": False,
            },
        )
        assert second["status"] == "completed" and second["output_text"]

        messages = self.request("GET", f"/api/v2/conversations/{conversation_id}/messages")
        first_input = next(item for item in messages if item["role"] == "user")
        branch = self.request(
            "POST",
            f"/api/v2/conversations/{conversation_id}/branch",
            body={"message_id": first_input["id"]},
        )
        self.conversation_ids.append(branch["conversation_id"])
        original_messages = self.request("GET", f"/api/v2/conversations/{conversation_id}/messages")
        assert any(second_marker in item["content"] for item in original_messages)

        feedback = self.request(
            "POST",
            f"/api/v2/responses/{second['id']}/feedback",
            body={"feedback_type": "positive", "score": 5},
        )
        assert feedback["status"] == "accepted"
        share = self.request("POST", f"/api/v2/conversations/{conversation_id}/share")
        snapshot = self.request(
            "GET",
            f"/api/v2/shared/{share['public_id']}/{share['token']}",
            authenticated=False,
        )
        assert snapshot["messages"]
        revoked = self.request("DELETE", f"/api/v2/conversations/{conversation_id}/share")
        assert revoked["revoked"] is True
        self.request(
            "GET",
            f"/api/v2/shared/{share['public_id']}/{share['token']}",
            authenticated=False,
            expected_status=404,
        )
        assert (
            self.request(
                "POST",
                f"/api/v2/conversations/{conversation_id}/archive",
                body={"archived": True},
            )["archived"]
            is True
        )
        assert (
            self.request(
                "POST",
                f"/api/v2/conversations/{conversation_id}/archive",
                body={"archived": False},
            )["archived"]
            is False
        )
        self.passed("附件、Responses、多轮历史、分支、反馈、分享与归档")

    def automation_flow(self, marker: str) -> None:
        conversation_id = self.conversation_ids[0]
        preview = self.request(
            "POST",
            "/api/v2/scheduled-tasks/preview",
            body={"expression": "每天 09:00", "timezone": "Asia/Shanghai"},
        )
        assert preview["rrule"] and preview["next_run_at"]
        task = self.request(
            "POST",
            "/api/v2/scheduled-tasks",
            body={
                "title": f"业务验收任务-{marker}",
                "prompt": "检查工作区状态并生成简报",
                "rrule": preview["rrule"],
                "timezone": "Asia/Shanghai",
                "conversation_id": conversation_id,
                "enabled": False,
            },
        )
        self.task_id = task["id"]
        enabled = self.request("POST", f"/api/v2/scheduled-tasks/{self.task_id}/actions/enable")
        assert enabled["status"] == "active" and enabled["next_run_at"]
        paused = self.request("POST", f"/api/v2/scheduled-tasks/{self.task_id}/actions/pause")
        assert paused["status"] == "paused"

        goal = self.request(
            "POST",
            "/api/v2/goals",
            body={
                "objective": f"完成一次可取消的业务验收目标 {marker}",
                "success_criteria": "目标能创建、暂停、恢复和取消",
                "conversation_id": conversation_id,
                "execution_profile": "fast",
            },
        )
        self.goal_id = goal["id"]
        assert goal["response_id"]
        updated = self.request(
            "PATCH",
            f"/api/v2/goals/{self.goal_id}",
            body={"success_criteria": "生命周期接口全部返回有效状态"},
        )
        assert "生命周期" in updated["success_criteria"]
        assert self.request("POST", f"/api/v2/goals/{self.goal_id}/pause")["status"] == "paused"
        resumed = self.request("POST", f"/api/v2/goals/{self.goal_id}/resume")
        assert resumed["status"] == "queued" and resumed["response_id"]
        cancelled = self.request("POST", f"/api/v2/goals/{self.goal_id}/cancel")
        assert cancelled["status"] == "cancelled"
        self.passed("定时任务预览/启停与 Goal 生命周期")

    def cleanup(self) -> None:
        for response_id in reversed(self.response_ids):
            try:
                current = self.request("GET", f"/api/v2/responses/{response_id}")
                if current.get("status") in {"queued", "in_progress", "requires_action"}:
                    self.request("POST", f"/api/v2/responses/{response_id}/cancel")
            except Exception:
                pass
        for attachment_id in reversed(self.attachment_ids):
            self._cleanup_request("DELETE", f"/api/v2/files/{attachment_id}")
        for conversation_id in reversed(self.conversation_ids):
            self._delete_conversation_when_idle(conversation_id)
        if self.task_id:
            self._cleanup_request("POST", f"/api/v2/scheduled-tasks/{self.task_id}/actions/cancel")
        if self.profile_id:
            self._cleanup_request("DELETE", f"/api/v2/assistant-profiles/{self.profile_id}")
        if self.database_id:
            self._cleanup_request("DELETE", f"/api/v1/databases/{self.database_id}")
        if self.original_instructions is not None:
            original = self.original_instructions
            if int(original.get("version") or 0) == 0:
                self._cleanup_request("DELETE", "/api/v2/personalization/custom-instructions")
            else:
                self._cleanup_request(
                    "PUT",
                    "/api/v2/personalization/custom-instructions",
                    body={
                        "about_user": original.get("about_user", ""),
                        "response_style": original.get("response_style", ""),
                        "enabled": bool(original.get("enabled", True)),
                    },
                )
        self.client.close()

    def _delete_conversation_when_idle(self, conversation_id: str) -> None:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                self.request("DELETE", f"/api/v2/conversations/{conversation_id}")
                return
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code != 409:
                    return
                time.sleep(0.5)

    def _cleanup_request(self, method: str, path: str, body: dict[str, Any] | None = None) -> None:
        try:
            self.request(method, path, body=body)
        except Exception:
            pass

    def run(self) -> None:
        marker = uuid.uuid4().hex[:10]
        try:
            self.login()
            self.personalization(marker)
            self.resources(marker)
            self.conversation_flow(marker)
            self.automation_flow(marker)
            print("✅ 核心业务流程 E2E 验收通过")
        finally:
            self.cleanup()


if __name__ == "__main__":
    started = time.monotonic()
    BusinessFlowVerifier().run()
    print(f"总耗时：{time.monotonic() - started:.1f}s")
