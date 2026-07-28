from __future__ import annotations

import pytest

from connectors import register_builtin_connectors
from connectors.registry import connector_registry
from connectors.sdk.protocol import ConnectorResource, SyncResult
from kernel.interoperability.a2a import A2AMessage, A2ASigner
from kernel.interoperability.mcp import MCPClient, MCPTool


def test_builtin_enterprise_connectors_are_registered():
    register_builtin_connectors()
    names = {item["name"] for item in connector_registry.list()}
    assert {"github", "slack", "confluence"}.issubset(names)


def test_connector_sync_contract_has_acl_delete_and_reconciliation_fields():
    resource = ConnectorResource(id="1", type="page", title="T", acl=["group:a"], version="2")
    result = SyncResult(
        items=[resource], deleted_ids=["0"], checkpoint={"cursor": "x"}, observed_count=1
    )
    assert result.items[0].acl == ["group:a"]
    assert result.deleted_ids == ["0"]
    assert result.observed_count == 1


def test_mcp_requires_tls_and_governs_write_tools():
    with pytest.raises(ValueError, match="HTTPS"):
        MCPClient("http://example.com/mcp")
    client = MCPClient("https://example.com/mcp", allowed_tools={"read"})
    assert client.allowed_tools == {"read"}
    assert MCPTool("write", "", {}, "write").side_effect_level == "write"


def test_a2a_signature_is_tenant_bound():
    signer = A2ASigner("x" * 32)
    message = A2AMessage("m1", "t1", "a", "b", "tenant-a", "ws", "task", {"x": 1})
    signature = signer.sign(message)
    assert signer.verify(message, signature)
    other = A2AMessage("m1", "t1", "a", "b", "tenant-b", "ws", "task", {"x": 1})
    assert not signer.verify(other, signature)
