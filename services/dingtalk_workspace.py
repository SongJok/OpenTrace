"""通过钉钉工作台 CLI 读取企业文档、群聊与组织目录。"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


class DingTalkWorkspaceError(RuntimeError):
    pass


@dataclass(frozen=True)
class DingTalkKnowledgeItem:
    external_id: str
    title: str
    content: str
    source_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    acl: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class DingTalkSyncBundle:
    knowledge_items: list[DingTalkKnowledgeItem]
    principals: list[dict[str, Any]]
    memberships: list[dict[str, Any]]
    cursor: str


def _rows(payload: Any) -> list[dict[str, Any]]:
    value = payload.get("result") if isinstance(payload, dict) else payload
    if isinstance(value, dict):
        for key in ("items", "list", "data", "records"):
            if isinstance(value.get(key), list):
                value = value[key]
                break
    return (
        [item for item in (value or []) if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _pick(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


class DingTalkWorkspaceClient:
    """安全执行只读 dws 命令，并把结果规范化到企业知识领域模型。"""

    def __init__(self, *, binary: str, profile: str = "", timeout_seconds: int = 30) -> None:
        resolved = Path(binary).expanduser()
        if not binary or not resolved.is_file():
            raise DingTalkWorkspaceError("dingtalk_dws_binary_unavailable")
        self.binary = str(resolved)
        self.profile = profile.strip()
        self.timeout_seconds = max(5, min(int(timeout_seconds), 120))

    async def _run(self, *args: str) -> Any:
        command = [self.binary, *args, "--format", "json", "--timeout", str(self.timeout_seconds)]
        if self.profile:
            command.extend(["--profile", self.profile])
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout_seconds + 5
            )
        except TimeoutError as exc:
            process.kill()
            await process.communicate()
            raise DingTalkWorkspaceError("dingtalk_command_timeout") from exc
        if process.returncode != 0:
            raise DingTalkWorkspaceError("dingtalk_command_failed")
        if len(stdout) > 8 * 1024 * 1024:
            raise DingTalkWorkspaceError("dingtalk_response_too_large")
        try:
            return json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise DingTalkWorkspaceError("dingtalk_invalid_json_response") from exc

    async def _documents(
        self, *, workspace: str, folder: str, limit: int
    ) -> list[DingTalkKnowledgeItem]:
        results: list[DingTalkKnowledgeItem] = []
        folder_queue = [folder]
        visited_folders: set[str] = set()
        visited_nodes: set[str] = set()
        while folder_queue and len(results) < limit and len(visited_folders) < 200:
            current_folder = folder_queue.pop(0)
            if current_folder in visited_folders:
                continue
            visited_folders.add(current_folder)
            args = ["drive", "list", "--limit", str(max(1, min(limit, 50)))]
            if workspace:
                args.extend(["--workspace", workspace])
            if current_folder:
                args.extend(["--folder", current_folder])
            for item in _rows(await self._run(*args)):
                node_id = _pick(item, "nodeId", "node_id", "dentryUuid", "dentryKey", "id")
                title = _pick(item, "name", "title", "fileName") or node_id
                kind = _pick(item, "type", "fileType", "nodeType").lower()
                if not node_id or node_id in visited_nodes:
                    continue
                visited_nodes.add(node_id)
                if kind in {"folder", "directory"}:
                    folder_queue.append(node_id)
                    continue
                try:
                    payload = await self._run("doc", "read", "--node", node_id)
                except DingTalkWorkspaceError:
                    continue
                raw_content = payload.get("result") if isinstance(payload, dict) else payload
                if isinstance(raw_content, dict):
                    content = _pick(raw_content, "content", "markdown", "text")
                else:
                    content = str(raw_content or "").strip()
                if not content:
                    continue
                results.append(
                    DingTalkKnowledgeItem(
                        external_id=f"dingtalk:document:{node_id}",
                        title=title,
                        content=content,
                        source_type="document",
                        metadata={
                            "provider": "dingtalk",
                            "node_id": node_id,
                            "folder_id": current_folder,
                            "source": item,
                        },
                    )
                )
                if len(results) >= limit:
                    break
        return results

    async def _chats(
        self, *, since_days: int, limit: int
    ) -> tuple[list[DingTalkKnowledgeItem], list[dict[str, Any]], list[dict[str, Any]]]:
        payload = await self._run(
            "chat", "list-all-conversations", "--limit", str(max(1, min(limit, 100)))
        )
        since = datetime.now(UTC) - timedelta(days=max(1, min(since_days, 365)))
        since_text = since.astimezone().strftime("%Y-%m-%d %H:%M:%S")
        results: list[DingTalkKnowledgeItem] = []
        principals: list[dict[str, Any]] = []
        memberships: list[dict[str, Any]] = []
        for item in _rows(payload):
            chat_id = _pick(
                item, "openConversationId", "open_conversation_id", "conversationId", "cid", "id"
            )
            title = _pick(item, "title", "name", "conversationName") or chat_id
            conversation_type = _pick(item, "conversationType", "type").lower()
            if not chat_id or conversation_type in {"single", "oto", "1"}:
                continue
            group_external_id = f"dingtalk:{chat_id}"
            principals.append(
                {
                    "principal_type": "group",
                    "external_id": group_external_id,
                    "display_name": title,
                    "attributes": {"provider": "dingtalk", "chat_id": chat_id},
                }
            )
            try:
                member_payload = await self._run(
                    "chat", "group", "members", "--id", chat_id, "--cursor", "0"
                )
            except DingTalkWorkspaceError:
                member_payload = {"result": []}
            for member in _rows(member_payload):
                email = _pick(member, "email", "orgEmail", "org_email", "workEmail").lower()
                if email:
                    memberships.append(
                        {
                            "user_email": email,
                            "principal_type": "group",
                            "principal_external_id": group_external_id,
                            "metadata": {
                                "provider": "dingtalk",
                                "chat_id": chat_id,
                                "user_id": _pick(member, "userId", "userid", "staffId"),
                            },
                        }
                    )
            messages_payload = await self._run(
                "chat",
                "message",
                "list",
                "--group",
                chat_id,
                "--time",
                since_text,
                "--direction",
                "newer",
                "--limit",
                "200",
            )
            message_lines: list[str] = []
            for message in _rows(messages_payload):
                text = _pick(message, "text", "content", "messageContent", "summary")
                if not text:
                    continue
                sender = _pick(message, "senderName", "senderNick", "sender", "creatorName")
                created = _pick(message, "createTime", "createdAt", "sendTime")
                prefix = " · ".join(value for value in (created, sender) if value)
                message_lines.append(f"[{prefix}] {text}" if prefix else text)
            if message_lines:
                results.append(
                    DingTalkKnowledgeItem(
                        external_id=f"dingtalk:chat:{chat_id}",
                        title=f"群聊：{title}",
                        content="\n".join(message_lines),
                        source_type="chat",
                        metadata={
                            "provider": "dingtalk",
                            "chat_id": chat_id,
                            "since": since.isoformat(),
                        },
                        acl=[
                            {
                                "subject_type": "group",
                                "subject_id": group_external_id,
                                "permission": "view",
                                "inherited": False,
                                "external_ref": chat_id,
                            }
                        ],
                    )
                )
        return results, principals, memberships

    async def _directory(
        self, *, root_department_id: str, max_departments: int
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        queue = [root_department_id or "1"]
        visited: set[str] = set()
        principals: list[dict[str, Any]] = []
        memberships: list[dict[str, Any]] = []
        while queue and len(visited) < max(1, min(max_departments, 2000)):
            parent_id = queue.pop(0)
            if parent_id in visited:
                continue
            visited.add(parent_id)
            children = _rows(
                await self._run("contact", "dept", "list-children", "--dept", parent_id)
            )
            department_ids: list[str] = []
            for item in children:
                department_id = _pick(item, "deptId", "dept_id", "departmentId", "id")
                if not department_id:
                    continue
                department_ids.append(department_id)
                queue.append(department_id)
                principals.append(
                    {
                        "principal_type": "department",
                        "external_id": department_id,
                        "display_name": _pick(item, "name", "deptName", "displayName")
                        or department_id,
                        "parent_external_id": _pick(item, "parentId", "parent_id") or parent_id,
                        "attributes": {"provider": "dingtalk", "raw": item},
                    }
                )
            if parent_id == (root_department_id or "1"):
                department_ids.append(parent_id)
            if not department_ids:
                continue
            members = _rows(
                await self._run(
                    "contact", "dept", "list-members", "--depts", ",".join(department_ids[:30])
                )
            )
            for member in members:
                email = _pick(member, "email", "orgEmail", "org_email", "workEmail").lower()
                department_id = _pick(member, "deptId", "dept_id", "departmentId", "department_id")
                if email and department_id:
                    memberships.append(
                        {
                            "user_email": email,
                            "principal_type": "department",
                            "principal_external_id": department_id,
                            "metadata": {
                                "provider": "dingtalk",
                                "user_id": _pick(member, "userId", "userid", "staffId"),
                            },
                        }
                    )
        return principals, memberships

    async def collect(
        self,
        *,
        include_documents: bool,
        include_chats: bool,
        include_directory: bool,
        workspace: str = "",
        folder: str = "",
        root_department_id: str = "1",
        chat_since_days: int = 30,
        limit: int = 20,
        max_departments: int = 500,
    ) -> DingTalkSyncBundle:
        knowledge_items: list[DingTalkKnowledgeItem] = []
        principals: list[dict[str, Any]] = []
        memberships: list[dict[str, Any]] = []
        if include_documents:
            knowledge_items.extend(
                await self._documents(workspace=workspace, folder=folder, limit=limit)
            )
        if include_chats:
            chat_items, chat_principals, chat_memberships = await self._chats(
                since_days=chat_since_days, limit=limit
            )
            knowledge_items.extend(chat_items)
            principals.extend(chat_principals)
            memberships.extend(chat_memberships)
        if include_directory:
            department_principals, department_memberships = await self._directory(
                root_department_id=root_department_id,
                max_departments=max_departments,
            )
            principals.extend(department_principals)
            memberships.extend(department_memberships)
        return DingTalkSyncBundle(
            knowledge_items=knowledge_items,
            principals=principals,
            memberships=memberships,
            cursor=datetime.now(UTC).isoformat(),
        )
