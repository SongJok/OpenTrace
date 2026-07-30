from pathlib import Path

import pytest

from gateway.api_gateway.main import app
from services.dingtalk_workspace import DingTalkWorkspaceClient, DingTalkWorkspaceError


class FakeDingTalkWorkspaceClient(DingTalkWorkspaceClient):
    def __init__(self) -> None:
        super().__init__(binary="/bin/echo", profile="readonly-company")

    async def _run(self, *args: str):
        command = " ".join(args)
        if command.startswith("drive list"):
            if "--folder folder-1" in command:
                return {"result": [{"nodeId": "doc-2", "name": "运营规范", "type": "document"}]}
            return {
                "result": [
                    {"nodeId": "doc-1", "name": "公司制度", "type": "document"},
                    {"nodeId": "folder-1", "name": "资料目录", "type": "folder"},
                ]
            }
        if command.startswith("doc read"):
            return {"result": {"markdown": "# 公司制度\n员工必须遵循信息安全规范。"}}
        if command.startswith("chat list-all-conversations"):
            return {
                "result": [
                    {
                        "openConversationId": "chat-1",
                        "title": "运营协同群",
                        "conversationType": "group",
                    }
                ]
            }
        if command.startswith("chat message list"):
            return {
                "result": [
                    {
                        "senderName": "小王",
                        "createTime": "2026-07-30 09:30:00",
                        "text": "本周活动复盘需要在周五前完成。",
                    }
                ]
            }
        if command.startswith("chat group members"):
            return {
                "result": [
                    {
                        "userId": "ding-user-1",
                        "orgEmail": "member@example.com",
                    }
                ]
            }
        if command.startswith("contact dept list-children"):
            if args[-1] == "1":
                return {"result": [{"deptId": "dept-ops", "name": "运营部", "parentId": "1"}]}
            return {"result": []}
        if command.startswith("contact dept list-members"):
            return {
                "result": [
                    {
                        "deptId": "dept-ops",
                        "userId": "ding-user-1",
                        "orgEmail": "member@example.com",
                    }
                ]
            }
        raise AssertionError(command)


@pytest.mark.asyncio
async def test_dingtalk_collects_documents_chats_and_directory() -> None:
    bundle = await FakeDingTalkWorkspaceClient().collect(
        include_documents=True,
        include_chats=True,
        include_directory=True,
        workspace="workspace-1",
        root_department_id="1",
        chat_since_days=30,
        limit=20,
    )
    assert [item.source_type for item in bundle.knowledge_items] == [
        "document",
        "document",
        "chat",
    ]
    assert bundle.knowledge_items[0].external_id == "dingtalk:document:doc-1"
    assert bundle.knowledge_items[1].external_id == "dingtalk:document:doc-2"
    assert bundle.knowledge_items[2].acl[0]["subject_id"] == "dingtalk:chat-1"
    assert {item["external_id"] for item in bundle.principals} == {
        "dingtalk:chat-1",
        "dept-ops",
    }
    assert {item["principal_type"] for item in bundle.memberships} == {
        "group",
        "department",
    }
    assert all(item["user_email"] == "member@example.com" for item in bundle.memberships)
    assert bundle.cursor


def test_dingtalk_requires_an_explicit_readonly_runtime() -> None:
    with pytest.raises(DingTalkWorkspaceError, match="dingtalk_dws_binary_unavailable"):
        DingTalkWorkspaceClient(binary="/definitely/missing/dws")


def test_dingtalk_sync_enters_existing_governance_surfaces() -> None:
    paths = app.openapi()["paths"]
    operation = paths["/api/v1/knowledge/connectors/{connector_id}/sync-dingtalk"]["post"]
    assert "202" in operation["responses"]
    directory = Path("services/enterprise_directory.py").read_text(encoding="utf-8")
    route = Path("gateway/api_gateway/routers/knowledge_enterprise.py").read_text(encoding="utf-8")
    assert '"dingtalk"' in directory
    assert "sync_enterprise_directory" in route
    assert "push_connector_snapshots" in route
    assert "get_current_admin_user" in route
