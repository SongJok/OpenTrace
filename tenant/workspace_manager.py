"""Workspace scoping within org/tenant."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class WorkspaceRecord:
    workspace_id: str
    tenant_id: str
    org_id: str
    name: str = ""
    policy_overrides: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "tenant_id": self.tenant_id,
            "org_id": self.org_id,
            "name": self.name,
            "policy_overrides": dict(self.policy_overrides),
        }


_workspace_store: dict[str, WorkspaceRecord] = {}


class WorkspaceManager:
    def __init__(self) -> None:
        self._workspaces = _workspace_store

    def _key(self, tenant_id: str, workspace_id: str) -> str:
        return f"{tenant_id}:{workspace_id}"

    def register(self, record: WorkspaceRecord) -> None:
        self._workspaces[self._key(record.tenant_id, record.workspace_id)] = record

    def get(self, tenant_id: str, workspace_id: str) -> WorkspaceRecord | None:
        return self._workspaces.get(self._key(tenant_id, workspace_id))