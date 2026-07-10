from __future__ import annotations

import urllib.parse
from dataclasses import asdict

from connectors.sdk.protocol import ConnectorResource, CredentialRef, SyncResult


class GitHubConnector:
    name = "github"

    def __init__(self, client_id: str = "", client_secret: str = "") -> None:
        self.client_id = client_id
        self.client_secret = client_secret

    async def authorize_url(self, user_id: str, redirect_uri: str, state: str) -> str:
        q = urllib.parse.urlencode(
            {
                "client_id": self.client_id or "github-client-id",
                "redirect_uri": redirect_uri,
                "scope": "repo read:user",
                "state": state,
            }
        )
        return f"https://github.com/login/oauth/authorize?{q}"

    async def exchange_code(self, user_id: str, code: str, redirect_uri: str) -> CredentialRef:
        # P5 step1: skeleton/mock exchange, real HTTP token exchange in step2
        return CredentialRef(
            provider=self.name,
            account_id=user_id,
            access_token=f"gho_mock_{code}",
            refresh_token="",
            metadata={"redirect_uri": redirect_uri},
        )

    async def refresh_token(self, credential: CredentialRef) -> CredentialRef:
        return credential

    async def list_resources(self, credential: CredentialRef, cursor: str | None = None, limit: int = 20) -> list[ConnectorResource]:
        return [
            ConnectorResource(
                id="repo:opentrace",
                type="repository",
                title="opentrace",
                content="mock repo resource",
                metadata={"provider": self.name, "cursor": cursor, "limit": limit, "account_id": credential.account_id},
            )
        ]

    async def fetch_resource(self, credential: CredentialRef, resource_id: str) -> ConnectorResource:
        return ConnectorResource(
            id=resource_id,
            type="repository",
            title=resource_id,
            content="mock resource content",
            metadata={"provider": self.name, "account_id": credential.account_id},
        )

    async def sync(self, credential: CredentialRef, cursor: str | None = None, limit: int = 20) -> SyncResult:
        items = await self.list_resources(credential, cursor=cursor, limit=limit)
        return SyncResult(items=items, next_cursor=None, has_more=False)

    def to_public_dict(self) -> dict:
        return {"name": self.name, "client_id_configured": bool(self.client_id)}

    @staticmethod
    def credential_to_dict(c: CredentialRef) -> dict:
        return asdict(c)
