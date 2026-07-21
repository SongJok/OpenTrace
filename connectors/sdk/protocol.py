from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class CredentialRef:
    provider: str
    account_id: str
    access_token: str = ""
    refresh_token: str = ""
    expires_at: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConnectorResource:
    id: str
    type: str
    title: str
    content: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SyncResult:
    items: list[ConnectorResource] = field(default_factory=list)
    next_cursor: str | None = None
    has_more: bool = False


class BaseConnector(Protocol):
    name: str

    async def authorize_url(self, user_id: str, redirect_uri: str, state: str) -> str: ...

    async def exchange_code(self, user_id: str, code: str, redirect_uri: str) -> CredentialRef: ...

    async def refresh_token(self, credential: CredentialRef) -> CredentialRef: ...

    async def list_resources(self, credential: CredentialRef, cursor: str | None = None, limit: int = 20) -> list[ConnectorResource]: ...

    async def fetch_resource(self, credential: CredentialRef, resource_id: str) -> ConnectorResource: ...

    async def sync(self, credential: CredentialRef, cursor: str | None = None, limit: int = 20) -> SyncResult: ...
